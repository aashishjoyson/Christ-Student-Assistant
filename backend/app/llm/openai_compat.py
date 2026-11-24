"""Chat Completions client for any OpenAI-compatible endpoint.

Chat Completions is used (not the Responses API) because OpenAI, OpenRouter and vLLM all
implement it, so Models 1, 2 and 3 share one client class and one request shape (ADR-004).
Optional parameters are only sent when configured, because reasoning models reject
`temperature` and older servers may not know `reasoning_effort`.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from app.llm.base import ChatResult, LLMError


class OpenAICompatibleChatClient:
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        max_output_tokens: int = 800,
        output_limit_field: str = "max_completion_tokens",
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self._max_output_tokens = max_output_tokens
        # Name of the request field that caps output length: OpenAI's newer models use
        # `max_completion_tokens`; OpenRouter and vLLM use `max_tokens`.
        self._output_limit_field = output_limit_field
        self._temperature = temperature
        self._reasoning_effort = reasoning_effort
        # The SDK retries 408/409/429/5xx and connection errors with exponential backoff.
        self._client = OpenAI(
            api_key=api_key or "not-needed",
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=extra_headers,
        )

    # ---------------------------------------------------------------- shared helpers
    def _request(self, messages: list[dict[str, str]]) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            self._output_limit_field: self._max_output_tokens,
        }
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort
        return kwargs

    def _translate(self, exc: Exception) -> LLMError | None:
        """Map SDK errors to our stable error codes; None means 'not an SDK error, re-raise as is'."""
        if isinstance(exc, AuthenticationError):
            return LLMError("provider_auth_failed", f"{self.provider}: authentication failed - check the API key.")
        if isinstance(exc, RateLimitError):
            return LLMError("provider_rate_limited", f"{self.provider}: rate limited or out of credit.", retryable=True,
                            http_status=429)
        if isinstance(exc, APIStatusError):
            return LLMError("provider_error", f"{self.provider}: request failed with HTTP {exc.status_code}.")
        if isinstance(exc, APITimeoutError):  # before APIConnectionError: it is a subclass
            return LLMError("provider_timeout", f"{self.provider}: request timed out.", retryable=True, http_status=504)
        if isinstance(exc, APIConnectionError):
            return LLMError("provider_unreachable", f"{self.provider}: endpoint unreachable.", retryable=True)
        return None

    def _empty(self, finish_reason: str | None) -> LLMError:
        return LLMError(
            "empty_completion",
            f"{self.provider}: empty answer (finish_reason={finish_reason}). "
            "If this is a reasoning model, raise LLM_MAX_OUTPUT_TOKENS or lower LLM_REASONING_EFFORT.",
        )

    # ---------------------------------------------------------------- one-shot
    def complete(self, messages: list[dict[str, str]]) -> ChatResult:
        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(**self._request(messages))  # type: ignore[call-overload]
        except Exception as exc:
            translated = self._translate(exc)
            if translated is None:
                raise
            raise translated from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        if not text:
            raise self._empty(choice.finish_reason)
        usage = response.usage
        return ChatResult(
            text=text,
            provider=self.provider,
            model=response.model or self.model,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            latency_ms=latency_ms,
            finish_reason=choice.finish_reason,
        )

    # ---------------------------------------------------------------- streaming
    def stream(self, messages: list[dict[str, str]]) -> Iterator[str | ChatResult]:
        """Yield text deltas as they arrive, then one final ChatResult (full text + usage).

        Errors are raised as LLMError, whether they happen before the first token or midway. Reasoning models stream only the
        visible answer, so the first token still arrives after their hidden thinking."""
        started = time.perf_counter()
        parts: list[str] = []
        first_token_ms: int | None = None
        finish_reason: str | None = None
        model_id: str | None = None
        usage = None
        try:
            kwargs = self._request(messages)
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}  # usage arrives in a final chunk with no choices
            for chunk in self._client.chat.completions.create(**kwargs):  # type: ignore[call-overload]
                model_id = getattr(chunk, "model", None) or model_id
                usage = getattr(chunk, "usage", None) or usage
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                text = getattr(choice.delta, "content", None)
                if text:
                    if first_token_ms is None:
                        first_token_ms = int((time.perf_counter() - started) * 1000)
                    parts.append(text)
                    yield text
                finish_reason = choice.finish_reason or finish_reason
        except Exception as exc:
            translated = self._translate(exc)
            if translated is None:
                raise
            raise translated from exc

        full = "".join(parts).strip()
        if not full:
            raise self._empty(finish_reason)
        yield ChatResult(
            text=full,
            provider=self.provider,
            model=model_id or self.model,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=finish_reason,
            first_token_ms=first_token_ms,
        )

"""Chat Completions client for any OpenAI-compatible endpoint.

Chat Completions is used (not the Responses API) because OpenAI, OpenRouter and vLLM all
implement it, so Models 1, 2 and 3 share one client class and one request shape (ADR-004).
Optional parameters are only sent when configured, because reasoning models reject
`temperature` and older servers may not know `reasoning_effort`.
"""

from __future__ import annotations

import time

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

    def complete(self, messages: list[dict[str, str]]) -> ChatResult:
        kwargs: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            self._output_limit_field: self._max_output_tokens,
        }
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort

        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
        except AuthenticationError as exc:
            raise LLMError("provider_auth_failed", f"{self.provider}: authentication failed - check the API key.") from exc
        except RateLimitError as exc:
            raise LLMError(
                "provider_rate_limited", f"{self.provider}: rate limited or out of credit.", retryable=True,
                http_status=429,
            ) from exc
        except APIStatusError as exc:
            raise LLMError("provider_error", f"{self.provider}: request failed with HTTP {exc.status_code}.") from exc
        except APITimeoutError as exc:
            raise LLMError("provider_timeout", f"{self.provider}: request timed out.", retryable=True,
                           http_status=504) from exc
        except APIConnectionError as exc:
            raise LLMError("provider_unreachable", f"{self.provider}: endpoint unreachable.", retryable=True) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        if not text:
            raise LLMError(
                "empty_completion",
                f"{self.provider}: empty answer (finish_reason={choice.finish_reason}). "
                "If this is a reasoning model, raise LLM_MAX_OUTPUT_TOKENS or lower LLM_REASONING_EFFORT.",
            )
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

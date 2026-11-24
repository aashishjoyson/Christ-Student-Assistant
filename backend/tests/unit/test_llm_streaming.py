"""OpenAICompatibleChatClient.stream against a stub SDK client (no network)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, AuthenticationError

from app.llm.base import ChatResult, LLMError
from app.llm.openai_compat import OpenAICompatibleChatClient


def chunk(text: str | None = None, *, finish: str | None = None, usage: tuple[int, int] | None = None, model: str = "m-1"):  # type: ignore[no-untyped-def]
    choices = [] if usage else [SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=finish)]
    u = SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]) if usage else None
    return SimpleNamespace(model=model, choices=choices, usage=u)


class StubCompletions:
    def __init__(self, items=None, raises: Exception | None = None, fail_midway: Exception | None = None) -> None:  # type: ignore[no-untyped-def]
        self.items, self.raises, self.fail_midway = items or [], raises, fail_midway
        self.kwargs: dict = {}

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.kwargs = kwargs
        if self.raises:
            raise self.raises
        return self._iterate()

    def _iterate(self):  # type: ignore[no-untyped-def]
        yield from self.items
        if self.fail_midway:
            raise self.fail_midway


def client_with(stub: StubCompletions) -> OpenAICompatibleChatClient:
    c = OpenAICompatibleChatClient(provider="openai", model="m", api_key="k")
    c._client = SimpleNamespace(chat=SimpleNamespace(completions=stub))  # type: ignore[assignment]
    return c


def test_deltas_then_one_final_result_with_usage_and_first_token_time() -> None:
    stub = StubCompletions([chunk("Hel"), chunk("lo "), chunk("world", finish="stop"), chunk(usage=(11, 3))])
    items = list(client_with(stub).stream([{"role": "user", "content": "hi"}]))
    assert items[:3] == ["Hel", "lo ", "world"]
    final = items[3]
    assert isinstance(final, ChatResult) and final.text == "Hello world" and final.finish_reason == "stop"
    assert (final.input_tokens, final.output_tokens, final.model) == (11, 3, "m-1") and final.first_token_ms is not None
    assert stub.kwargs["stream"] is True and stub.kwargs["stream_options"] == {"include_usage": True}


def test_empty_content_chunks_are_skipped_and_an_empty_answer_is_an_error() -> None:
    ok = list(client_with(StubCompletions([chunk(None), chunk(""), chunk("Yes", finish="stop")])).stream([]))
    assert ok[0] == "Yes" and isinstance(ok[-1], ChatResult)
    with pytest.raises(LLMError) as exc:
        list(client_with(StubCompletions([chunk(None, finish="length")])).stream([]))
    assert exc.value.code == "empty_completion" and "length" in exc.value.message


def test_provider_errors_become_stable_codes_before_and_during_the_stream() -> None:
    request = httpx.Request("POST", "https://api.example/v1/chat/completions")
    auth = AuthenticationError("bad key", response=httpx.Response(401, request=request), body=None)
    with pytest.raises(LLMError) as before:
        list(client_with(StubCompletions(raises=auth)).stream([]))
    assert before.value.code == "provider_auth_failed"

    midway = APIConnectionError(request=request)
    with pytest.raises(LLMError) as during:
        it = client_with(StubCompletions([chunk("partial ")], fail_midway=midway)).stream([])
        assert next(it) == "partial "
        next(it)
    assert during.value.code == "provider_unreachable" and during.value.retryable is True


def test_unexpected_exceptions_are_not_swallowed() -> None:
    with pytest.raises(KeyError):
        list(client_with(StubCompletions(raises=KeyError("bug"))).stream([]))

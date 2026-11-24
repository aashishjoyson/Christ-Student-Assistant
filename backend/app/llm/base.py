"""Provider-neutral chat interface and error types (stdlib only)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChatResult:
    text: str
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    finish_reason: str | None = None
    first_token_ms: int | None = None  # streaming only: time until the first visible token


class LLMError(Exception):
    """A provider call failed. `code` is stable and shown to the UI; `http_status` is used by the API."""

    def __init__(self, code: str, message: str, *, retryable: bool = False, http_status: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status

    def as_error(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "http_status": self.http_status}


class ChatClient(Protocol):
    provider: str
    model: str

    def complete(self, messages: list[dict[str, str]]) -> ChatResult: ...


class StreamingChatClient(ChatClient, Protocol):
    def stream(self, messages: list[dict[str, str]]) -> Iterator[str | ChatResult]:
        """Yield text deltas (str) as they arrive, then ONE final ChatResult holding the full text and usage."""
        ...

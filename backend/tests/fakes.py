"""Test doubles for every external dependency. Tests never call paid APIs or send email."""

from __future__ import annotations

from app.domain.documents import RetrievedChunk
from app.llm.base import ChatResult, LLMError
from app.services.email.base import OutgoingEmail, SendResult


class FakeChatClient:
    def __init__(self, provider: str = "fake", model: str = "fake-model", reply: str = "Classes begin on 1 July [1].",
                 error: LLMError | None = None) -> None:
        self.provider = provider
        self.model = model
        self.reply = reply
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> ChatResult:
        self.calls.append(messages)
        if self.error:
            raise self.error
        return ChatResult(self.reply, self.provider, self.model, input_tokens=120, output_tokens=20, latency_ms=5,
                          finish_reason="stop")


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk] | None = None, ready: bool = True) -> None:
        self._ready = ready
        self.chunks = chunks if chunks is not None else [
            RetrievedChunk("cal:v1:0000", "SYNTHETIC: Classes begin on 1 July.", "SYNTHETIC_academic_calendar.md",
                           "cal", section="Key dates", distance=0.2),
            RetrievedChunk("hb:v1:0002", "SYNTHETIC: Minimum attendance is 85%.", "SYNTHETIC_student_handbook.md",
                           "hb", section="Attendance", distance=0.4),
        ]
        self.calls: list[str] = []

    @property
    def ready(self) -> bool:
        return self._ready

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.calls.append(query)
        return self.chunks[:top_k]

    def describe(self) -> dict[str, object]:
        return {"backend": "fake", "ready": self._ready}


class RecordingEmailProvider:
    name = "recording"

    def __init__(self, status: str = "simulated", raise_error: bool = False) -> None:
        self.status = status
        self.raise_error = raise_error
        self.sent: list[OutgoingEmail] = []

    def send(self, email: OutgoingEmail) -> SendResult:
        if self.raise_error:
            raise RuntimeError("smtp exploded")
        self.sent.append(email)
        if self.status == "failed":
            return SendResult(status="failed", provider=self.name, error="provider rejected")
        return SendResult(status=self.status, provider=self.name, provider_message_id=f"msg-{len(self.sent)}")  # type: ignore[arg-type]

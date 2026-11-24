"""Test doubles for every external dependency. Tests never call paid APIs or send email."""

from __future__ import annotations

from app.domain.documents import RetrievedChunk
from app.domain.intent_fallback import INTENT_SYSTEM_PROMPT
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


class ScriptedChatClient(FakeChatClient):
    """Like FakeChatClient, but intent-classifier calls (recognised by their system prompt) get a scripted label.

    classifier_reply=None -> "academic_qa"; "__error__" -> the classifier call raises (provider timeout).
    """

    def __init__(self, classifier_reply: str | None = None, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self.classifier_reply = classifier_reply

    def complete(self, messages: list[dict[str, str]]) -> ChatResult:
        if messages and messages[0].get("role") == "system" and messages[0]["content"] == INTENT_SYSTEM_PROMPT:
            self.calls.append(messages)
            if self.classifier_reply == "__error__":
                raise LLMError("provider_timeout", "scripted classifier failure", retryable=True, http_status=504)
            return ChatResult(self.classifier_reply or "academic_qa", self.provider, self.model, input_tokens=90,
                              output_tokens=4, latency_ms=3, finish_reason="stop")
        return super().complete(messages)


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


class FakeEmbedder:
    """Deterministic bag-of-words embeddings (64 dims): texts that share words are close. Counts calls; can fail or block."""

    model = "fake-embed-1"

    def __init__(self) -> None:
        self.calls = 0
        self.texts_embedded = 0
        self.fail = False
        self.gate: object | None = None  # a threading.Event: embed() waits for it (single-flight test)
        self.entered: object | None = None  # a threading.Event set when embed() starts

    @staticmethod
    def _vector(text: str) -> list[float]:
        import math
        import re
        import zlib

        vec = [0.0] * 64
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            vec[zlib.crc32(word.encode()) % 64] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec] if any(vec) else [1.0 / 8] * 64

    def embed(self, texts):  # type: ignore[no-untyped-def]
        from app.rag.embeddings import EmbeddingError, EmbedResult

        if self.entered is not None:
            self.entered.set()  # type: ignore[attr-defined]
        if self.gate is not None:
            self.gate.wait(timeout=10)  # type: ignore[attr-defined]
        if self.fail:
            raise EmbeddingError("scripted embedding failure")
        self.calls += 1
        self.texts_embedded += len(texts)
        return EmbedResult(vectors=[self._vector(t) for t in texts], tokens=sum(max(1, len(t) // 4) for t in texts), calls=1)

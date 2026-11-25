"""Live flow events: what each part of the system is doing, as it happens. They feed the #/flow dashboard.

Rules (pinned by tests/unit/test_flow_bus.py):
- An event says WHICH component did WHAT and HOW LONG it took. It never carries message text, an answer, a passage, a prompt, a search query,
  applicant data or an unmasked address: detail keys that could hold them are dropped and every string goes through the e-mail masker.
  (The trace log, ADR-022, follows the same rule.)
- Events live in memory only, in a ring buffer: restarting the API clears them and nothing is written to disk.
- Reading them needs the admin key (api/routes_flow.py).
- Everything here is a no-op until the container installs a bus, so tests, scripts and the evaluation runner are unaffected, and a bug in
  this module can never break a chat turn: every emit is guarded.
"""

from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.domain.masking import mask_email

log = logging.getLogger(__name__)

# One entry per box on the dashboard's maps: id -> label, group and a one-sentence role (shown when a box is selected).
SERVICES: dict[str, dict[str, str]] = {
    "browser": {"label": "Browser", "group": "client", "role": "The React chat widget. It sends the message and shows the streamed answer."},
    "api": {"label": "FastAPI", "group": "app", "role": "Receives the message, applies the per-client rate limit, runs the turn and writes the trace line."},
    "graph": {"label": "LangGraph", "group": "app", "role": "The workflow: one node per step and plain-Python routing between them, over one shared state."},
    "rules": {"label": "Intent rules", "group": "app", "role": "Deterministic rules decide what the message is about. Free and instant; a model is asked only when they are unsure."},
    "sqlite": {"label": "SQLite", "group": "app", "role": "Applicants, the email audit, feedback and the Drive indexing history. The model never writes SQL: only fixed queries run."},
    "email": {"label": "Email", "group": "app", "role": "SMTP to a real inbox, or a local outbox file in simulated mode. The recipient always comes from the database."},
    "traces": {"label": "Trace log", "group": "app", "role": "One text-free JSON line per request: model, tokens, cost, distances and the path taken."},
    "llm_openai": {"label": "Hosted LLM", "group": "model", "role": "The OpenAI model behind Models 1 and 2. Also used for the rare intent label and the follow-up rewrite."},
    "llm_modal": {"label": "Model 3 on Modal", "group": "model", "role": "Qwen3-4B with our LoRA adapter, served by vLLM on a rented GPU. It never falls back to another model."},
    "embedder": {"label": "Embeddings", "group": "data", "role": "OpenAI text-embedding-3-small turns the question (and, at indexing time, every chunk) into a vector."},
    "chroma": {"label": "Chroma index", "group": "data", "role": "The vector store of document chunks. It finds the passages whose meaning is closest to the question."},
    "rerank": {"label": "Re-ranker", "group": "data", "role": "Rewards passages that contain the question's rare words, then keeps the best 8 of 150 candidates."},
    "drive": {"label": "Google Drive", "group": "data", "role": "The folder of university documents: the source of truth. Nothing about the university is written in code."},
    "poller": {"label": "Poller", "group": "data", "role": "Checks Drive on a timer, one sync at a time, with backoff when something fails."},
    "ingest": {"label": "Ingestion", "group": "data", "role": "Parse, chunk, embed and upsert. Only files whose checksum changed are reprocessed; the old version leaves after the new one is in."},
    "eval": {"label": "Evaluation", "group": "ops", "role": "Runs the 38-question golden set against each model and freezes the exact configuration in the run folder."},
    "evidently": {"label": "Evidently", "group": "ops", "role": "Turns each run into outcome counts per model and category, with one critical test: no invalid citation."},
    "gate": {"label": "Promotion gate", "group": "ops", "role": "Compares a run with the accepted baseline. A critical regression blocks promotion; the reason is recorded."},
    "monitor": {"label": "Monitoring", "group": "ops", "role": "Latency, cost, refusal and distance drift, alerts, and the thumbs-up/down feedback, all from text-free traces."},
    "ci": {"label": "CI", "group": "ops", "role": "GitHub Actions: lint, tests, frontend build and secret scan on every push, with no key and no network."},
    "training": {"label": "Colab + Hugging Face", "group": "ops", "role": "QLoRA training on a Colab T4; the adapter lives in a private Hugging Face repository, pinned by commit."},
}

# A key is dropped when it could hold private text (exact names) or a secret (name endings).
_BLOCKED_KEYS = frozenset({
    "message", "text", "question", "answer", "prompt", "query", "email", "subject", "body", "passage", "passages", "content", "password",
    "secret", "api_key", "authorization", "recipient", "to",
})
_BLOCKED_ENDINGS = ("_text", "_password", "_secret", "_key", "_email", "_query", "_answer", "_question", "_body")
MAX_STRING = 160
MAX_ITEMS = 12
# An address is masked unless it is ALREADY masked (a "*" right before it), so "a***o@example.com" is not masked twice.
_ADDRESS = re.compile(r"(?<![*\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# The mail server's Message-ID (generated by our own code, with the sender's domain only) looks like an address but is not one.
_UNMASKED_KEYS = frozenset({"mail_id"})


def _mask(text: str) -> str:
    return _ADDRESS.sub(lambda match: mask_email(match.group(0)), text)


def _clean_value(value: Any, depth: int = 0, mask: bool = True) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, str):
        return " ".join((_mask(value) if mask else value).split())[:MAX_STRING]
    if depth >= 3:
        return None
    if isinstance(value, dict):
        return clean_detail(value, depth + 1)
    if isinstance(value, list | tuple | set | frozenset):
        return [_clean_value(item, depth + 1, mask) for item in list(value)[:MAX_ITEMS]]
    return _clean_value(str(value), depth, mask)


def clean_detail(detail: dict[str, Any] | None, depth: int = 0) -> dict[str, Any]:
    """Keep only what is safe to show: drops keys that could hold text or secrets, masks addresses, truncates, rounds."""
    out: dict[str, Any] = {}
    for key, value in (detail or {}).items():
        name = str(key).lower()
        if name in _BLOCKED_KEYS or name.endswith(_BLOCKED_ENDINGS):
            continue
        out[str(key)] = _clean_value(value, depth, mask=name not in _UNMASKED_KEYS)
    return out


@dataclass(frozen=True)
class FlowEvent:
    seq: int
    ts: str
    trace_id: str  # one chat request, one sync ("sync-12") or "system"
    kind: str  # request | node | step | ingest
    name: str  # stable machine name: "retrieve_context", "embed_query", "smtp_login"
    phase: str  # start | end | error
    service: str  # a key of SERVICES: which box on the map this belongs to
    label: str  # one plain sentence
    ms: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FlowBus:
    """A bounded in-memory log with increasing sequence numbers. Readers keep a cursor (the last seq they saw) and ask for what is newer."""

    def __init__(self, capacity: int = 1000) -> None:
        self._events: deque[FlowEvent] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def publish(self, *, trace_id: str, kind: str, name: str, phase: str, service: str, label: str,
                ms: int | None = None, detail: dict[str, Any] | None = None) -> FlowEvent:
        cleaned = clean_detail(detail)
        text = " ".join(_mask(label).split())[:MAX_STRING * 2]
        with self._lock:
            self._seq += 1
            event = FlowEvent(self._seq, datetime.now(UTC).isoformat(timespec="milliseconds"), trace_id or "system", kind, name, phase,
                              service, text, ms, cleaned)
            self._events.append(event)
        return event

    def since(self, seq: int = 0, limit: int = 500) -> list[FlowEvent]:
        with self._lock:
            newer = [e for e in self._events if e.seq > seq]
        return newer[:limit]


# ---------------------------------------------------------------------------------------------- the process-wide hook
_bus: FlowBus | None = None
_trace: contextvars.ContextVar[str] = contextvars.ContextVar("flow_trace", default="")


def install(bus: FlowBus | None) -> None:
    """Called once by the container. None switches the stream off (every emit becomes a no-op)."""
    global _bus
    _bus = bus


def current_bus() -> FlowBus | None:
    return _bus


@contextmanager
def trace_scope(trace_id: str) -> Iterator[None]:
    """Everything emitted inside belongs to this request unless it names another trace."""
    token = _trace.set(trace_id)
    try:
        yield
    finally:
        _trace.reset(token)


def emit(kind: str, name: str, phase: str, service: str, label: str, *, ms: int | None = None, trace_id: str | None = None,
         detail: dict[str, Any] | None = None) -> None:
    bus = _bus
    if bus is None:
        return
    try:
        bus.publish(trace_id=trace_id or _trace.get() or "system", kind=kind, name=name, phase=phase, service=service, label=label,
                    ms=ms, detail=detail)
    except Exception:  # observability must never break the thing it observes
        log.debug("flow event dropped", exc_info=True)


@contextmanager
def span(name: str, service: str, label: str, *, kind: str = "step", trace_id: str | None = None, **detail: Any) -> Iterator[dict[str, Any]]:
    """Time a block and publish ONE event when it ends (or fails). The yielded dict can collect more detail while the block runs."""
    info: dict[str, Any] = dict(detail)
    started = time.perf_counter()
    try:
        yield info
    except Exception as exc:
        emit(kind, name, "error", service, label, ms=round((time.perf_counter() - started) * 1000), trace_id=trace_id,
             detail={**info, "error": type(exc).__name__})
        raise
    emit(kind, name, "end", service, label, ms=round((time.perf_counter() - started) * 1000), trace_id=trace_id, detail=info)

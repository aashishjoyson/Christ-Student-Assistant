"""Runs one chat turn through the graph, writes the trace and builds the API response."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domain.intents import Intent
from app.domain.masking import hash_identifier
from app.graph.state import new_turn_input
from app.schemas.chat import ActionResult, ChatRequest, ChatResponse, CitationOut, HandledBy, Usage
from app.services.history_store import HistoryStore
from app.services.tracing import TraceRecorder

log = logging.getLogger("chat")


class ChatError(Exception):
    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class ChatService:
    def __init__(self, graph: Any, tracer: TraceRecorder, history: HistoryStore | None = None) -> None:
        self._graph = graph
        self._tracer = tracer
        self._history = history  # None: memory lives only in the graph and is lost on restart

    def _turn_input(self, conversation_id: UUID, message_id: str, request: ChatRequest, applicant_token: str | None,
                    stream: bool = False) -> dict[str, Any]:
        turn = new_turn_input(conversation_id=str(conversation_id), request_id=message_id, message=request.message,
                              model_mode=request.model_mode, applicant_token=applicant_token, stream=stream)
        if self._history is not None:
            config = {"configurable": {"thread_id": str(conversation_id)}}
            known = self._graph.get_state(config).values.get("history")
            if not known:  # a conversation the graph has not seen (the server restarted): put its stored turns back first
                turn["history"] = [*self._history.load(str(conversation_id)), *turn["history"]]
        return turn

    def forget(self, conversation_id: UUID) -> bool:
        """Delete everything remembered about a conversation: the stored turns and the graph's in-memory copy. True if anything was stored."""
        stored = self._history.delete(str(conversation_id)) if self._history is not None else False
        saver = getattr(self._graph, "checkpointer", None)
        if saver is not None and hasattr(saver, "delete_thread"):
            saver.delete_thread(str(conversation_id))
        return stored

    def _remember(self, conversation_id: UUID, final_state: dict[str, Any]) -> None:
        if self._history is not None and final_state.get("history"):
            self._history.save(str(conversation_id), list(final_state["history"]))

    def handle(self, request: ChatRequest, applicant_token: str | None) -> ChatResponse:
        conversation_id: UUID = request.conversation_id or uuid.uuid4()
        message_id = request.client_message_id or uuid.uuid4().hex
        started = time.perf_counter()
        out: dict[str, Any] = self._graph.invoke(
            self._turn_input(conversation_id, message_id, request, applicant_token),
            config={"configurable": {"thread_id": str(conversation_id)}},
        )
        self._remember(conversation_id, out)
        latency_ms = int((time.perf_counter() - started) * 1000)
        self._tracer.record(self._trace(out, request, conversation_id, message_id, latency_ms))

        error = out.get("error")
        if error:
            raise ChatError(str(error["code"]), str(error["message"]), int(error.get("http_status", 502)))
        return self._response(out, request, conversation_id, message_id, latency_ms)

    def stream(self, request: ChatRequest, applicant_token: str | None) -> Iterator[dict[str, Any]]:
        """Same turn as handle(), but yields events as they happen: {"type": "start" | "delta" | "error" | "final", ...}.

        start/delta come from the answer nodes (LLM answers only; template answers produce just "final"). "final" carries the
        complete ChatResponse (citations, usage, workflow path), so the client can replace the streamed text with the canonical
        one. An "error" event ends the stream. The trace is written once, exactly like handle()."""
        conversation_id: UUID = request.conversation_id or uuid.uuid4()
        message_id = request.client_message_id or uuid.uuid4().hex
        started = time.perf_counter()
        state: dict[str, Any] = {}
        try:
            for mode, payload in self._graph.stream(
                self._turn_input(conversation_id, message_id, request, applicant_token, stream=True),
                config={"configurable": {"thread_id": str(conversation_id)}},
                stream_mode=["custom", "values"],
            ):
                if mode == "custom":
                    yield dict(payload)
                else:
                    state = payload
        except Exception as exc:  # an unexpected failure must end the stream cleanly, not hang the client
            log.exception("streaming turn failed")
            yield {"type": "error", "code": "internal_error", "message": "The assistant hit an unexpected error.",
                   "http_status": 500, "detail": type(exc).__name__}
            return
        self._remember(conversation_id, state)
        latency_ms = int((time.perf_counter() - started) * 1000)
        self._tracer.record(self._trace(state, request, conversation_id, message_id, latency_ms))
        error = state.get("error")
        if error:
            yield {"type": "error", "code": str(error["code"]), "message": str(error["message"]),
                   "http_status": int(error.get("http_status", 502))}
            return
        yield {"type": "final", "response": self._response(state, request, conversation_id, message_id, latency_ms)
               .model_dump(mode="json")}

    # ---------- mapping ----------
    def _action(self, out: dict[str, Any]) -> ActionResult | None:
        status = out.get("action_status")
        if not status:
            return None
        if status == "verification_required":
            return ActionResult(type="verification", status=status)
        notification = out.get("notification") or {}
        eligibility = out.get("eligibility") or {}
        return ActionResult(
            type="interview_email_resend",
            status=status,
            masked_recipient=notification.get("masked_recipient"),
            reason=eligibility.get("reason"),
        )

    @staticmethod
    def _truthful_handled_by(handled_by: dict[str, Any] | None, intent_llm_called: bool) -> dict[str, Any]:
        """Template/database answers say "no LLM". If an LLM only read the request to choose the route, say so."""
        info = dict(handled_by or {"kind": "helpdesk", "label": "Helpdesk"})
        if intent_llm_called and info.get("kind") in ("applicant_service", "helpdesk"):
            info["label"] = (
                "Applicant service (answer from the database; an LLM only read the request)"
                if info["kind"] == "applicant_service"
                else "Helpdesk (template answer; an LLM only read the request)"
            )
        return info

    def _response(
        self, out: dict[str, Any], request: ChatRequest, conversation_id: UUID, message_id: str, latency_ms: int
    ) -> ChatResponse:
        llm = out.get("llm") or {}
        intent_llm_called = bool((out.get("intent_llm") or {}).get("called"))
        return ChatResponse(
            conversation_id=conversation_id,
            message_id=message_id,
            answer=out.get("response", ""),
            intent=out.get("intent", Intent.ACADEMIC_QA.value),
            model_mode_requested=request.model_mode,
            handled_by=HandledBy(**self._truthful_handled_by(out.get("handled_by"), intent_llm_called)),
            grounded=out.get("grounded"),
            notice=out.get("notice"),
            citations=[CitationOut(**c) for c in out.get("citations", [])],
            action=self._action(out),
            workflow_path=out.get("node_path", []),
            usage=Usage(
                latency_ms=latency_ms,
                first_token_ms=llm.get("first_token_ms"),
                llm_called=bool(llm.get("called")),
                intent_llm_called=intent_llm_called,
                condense_llm_called=bool((out.get("condense_llm") or {}).get("called")),
                input_tokens=llm.get("input_tokens"),
                output_tokens=llm.get("output_tokens"),
                est_cost_usd=llm.get("est_cost_usd"),
            ),
        )

    def _trace(
        self, out: dict[str, Any], request: ChatRequest, conversation_id: UUID, message_id: str, latency_ms: int
    ) -> dict[str, Any]:
        """No raw applicant data and no message text unless TRACE_INCLUDE_TEXT=true (then redacted)."""
        llm = out.get("llm") or {}
        intent_llm = out.get("intent_llm") or {}
        condense_llm = out.get("condense_llm") or {}
        handled_by = out.get("handled_by") or {}
        trace: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "message_id": message_id,
            "conversation": hash_identifier(str(conversation_id)),
            "intent": out.get("intent"),
            "intent_rule": out.get("intent_rule"),
            "model_mode_requested": request.model_mode,
            "handled_by": handled_by.get("kind"),
            "provider": llm.get("provider") or handled_by.get("provider"),
            "model": llm.get("model") or handled_by.get("model"),
            "base_model_id": handled_by.get("base_model_id"),
            "adapter_id": handled_by.get("adapter_id"),
            "prompt_version": llm.get("prompt_version"),
            "llm_called": llm.get("called", False),
            "input_tokens": llm.get("input_tokens"),
            "output_tokens": llm.get("output_tokens"),
            "est_cost_usd": llm.get("est_cost_usd"),
            "llm_latency_ms": llm.get("latency_ms"),
            "ttft_ms": llm.get("first_token_ms"),  # NOT named *token*: the redaction layer blanks any key containing "token"
            "streamed": bool(out.get("stream")),
            "intent_llm_called": bool(intent_llm.get("called")),
            "intent_llm_label": intent_llm.get("label"),
            "intent_llm_error": intent_llm.get("error"),
            "intent_llm_input_tokens": intent_llm.get("input_tokens"),
            "intent_llm_output_tokens": intent_llm.get("output_tokens"),
            "intent_llm_est_cost_usd": intent_llm.get("est_cost_usd"),
            "intent_llm_latency_ms": intent_llm.get("latency_ms"),
            "retrieval_query_rewritten": (condense_llm.get("used") if condense_llm else None),  # "llm" | "fallback" | None
            "condense_llm_called": bool(condense_llm.get("called")),
            "condense_llm_error": condense_llm.get("error"),
            "condense_llm_input_tokens": condense_llm.get("input_tokens"),
            "condense_llm_output_tokens": condense_llm.get("output_tokens"),
            "condense_llm_est_cost_usd": condense_llm.get("est_cost_usd"),
            "total_latency_ms": latency_ms,
            "retrieval": out.get("retrieval"),
            "retrieved_chunk_ids": [c["chunk_id"] for c in out.get("retrieved", [])],
            "cited_sources": [c["source_name"] for c in out.get("citations", []) if c.get("cited")],
            "grounded": out.get("grounded"),
            "action_status": out.get("action_status"),
            "eligibility_reason": (out.get("eligibility") or {}).get("reason"),
            "error_code": (out.get("error") or {}).get("code"),
            "node_path": out.get("node_path", []),
        }
        if self._tracer.include_text and handled_by.get("kind") != "applicant_service":
            trace["question"] = request.message
            trace["answer"] = out.get("response")
        return trace

"""Academic Q&A nodes: the three model paths.

Model 1: check_model_available -> direct_answer                      (no retriever call)
Model 2: check_model_available -> retrieve_context -> rag_answer      (primary LLM)
Model 3: check_model_available -> retrieve_context -> rag_peft_answer (LoRA endpoint)
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from langgraph.config import get_stream_writer

from app.domain.citations import build_citations
from app.domain.contextualize import (
    CONDENSE_PROMPT_VERSION,
    build_condense_messages,
    fallback_query,
    needs_condense,
    parse_standalone,
)
from app.domain.documents import RetrievedChunk
from app.domain.model_modes import MODE_LABELS, PROMPT_VERSIONS, ModelMode
from app.domain.pricing import estimate_cost_usd
from app.domain.prompts import (
    MODEL1_NOTICE,
    NO_EVIDENCE_ANSWER,
    NOT_INDEXED_ANSWER,
    build_direct_messages,
    build_rag_messages,
)
from app.graph.deps import GraphDeps
from app.graph.state import HelpdeskState, step
from app.llm.base import ChatClient, ChatResult, LLMError


def _error(code: str, message: str, http_status: int) -> dict[str, Any]:
    return {"code": code, "message": message, "http_status": http_status}


class AcademicNodes:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps

    # ---------- helpers ----------
    def _prior_turns(self, state: HelpdeskState) -> list[dict[str, str]]:
        history = state.get("history", [])[:-1]  # last item is the current user message
        return history[-self.deps.settings.history_turns :] if self.deps.settings.history_turns > 0 else []

    def _handled_by(self, mode: ModelMode, client: ChatClient) -> dict[str, Any]:
        info: dict[str, Any] = {
            "kind": "llm",
            "mode": mode.value,
            "label": MODE_LABELS[mode],
            "provider": client.provider,
            "model": client.model,
        }
        if mode == ModelMode.RAG_PEFT:
            info["base_model_id"] = self.deps.settings.model3_base_model_id
            info["adapter_id"] = self.deps.settings.model3_adapter_id
        return info

    def _llm_meta(self, mode: ModelMode, result: ChatResult | None) -> dict[str, Any]:
        meta: dict[str, Any] = {"prompt_version": PROMPT_VERSIONS[mode], "called": result is not None}
        if result:
            meta.update(
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
                finish_reason=result.finish_reason,
                first_token_ms=result.first_token_ms,
                est_cost_usd=estimate_cost_usd(result.model, result.input_tokens, result.output_tokens),
            )
        return meta

    def _generate(
        self, state: HelpdeskState, client: ChatClient, messages: list[dict[str, str]], announce: dict[str, Any]
    ) -> ChatResult:
        """One-shot by default. When this turn was started with streaming (POST /api/chat/stream) and the client can stream,
        text deltas go out through LangGraph's custom writer as they arrive; the 'start' event (which model answers, plus the
        Model 1 notice) is sent just before the FIRST delta, so an error before any text can still become a proper HTTP error."""
        if not (state.get("stream") and hasattr(client, "stream")):
            return client.complete(messages)
        write = get_stream_writer()
        result: ChatResult | None = None
        announced = False
        for item in client.stream(messages):  # type: ignore[attr-defined]
            if isinstance(item, str):
                if not announced:
                    write({"type": "start", **announce})
                    announced = True
                write({"type": "delta", "text": item})
            else:
                result = item
        if result is None:  # a streaming client must end with a ChatResult
            raise LLMError("empty_completion", f"{client.provider}: the stream ended without a result.")
        return result

    # ---------- nodes ----------
    def check_model_available(self, state: HelpdeskState) -> dict[str, Any]:
        mode = ModelMode(state["model_mode"])
        path = step(state, "check_model_available")
        if mode == ModelMode.RAG_PEFT and self.deps.model3_llm is None:
            return {
                "node_path": path,
                "error": _error(
                    "model3_not_configured",
                    "Model 3 is not configured. Deploy the LoRA adapter endpoint and set the MODEL3_* variables. "
                    "No other model is used as a substitute.",
                    503,
                ),
            }
        if mode in (ModelMode.DIRECT, ModelMode.RAG) and self.deps.primary_llm is None:
            return {
                "node_path": path,
                "error": _error(
                    "llm_not_configured",
                    "Models 1 and 2 need an LLM API key and chat model id (see .env.example).",
                    503,
                ),
            }
        return {"node_path": path}

    def direct_answer(self, state: HelpdeskState) -> dict[str, Any]:
        """Model 1: no retrieval, no university context."""
        client = self.deps.primary_llm
        assert client is not None  # guaranteed by check_model_available
        path = step(state, "direct_answer")
        try:
            result = self._generate(
                state, client, build_direct_messages(state["message"], self._prior_turns(state)),
                {"handled_by": self._handled_by(ModelMode.DIRECT, client), "notice": MODEL1_NOTICE},
            )
        except LLMError as exc:
            return {"node_path": path, "error": exc.as_error()}
        return {
            "response": result.text,
            "notice": MODEL1_NOTICE,
            "grounded": False,
            "citations": [],
            "handled_by": self._handled_by(ModelMode.DIRECT, client),
            "llm": self._llm_meta(ModelMode.DIRECT, result),
            "history": [{"role": "assistant", "content": result.text}],
            "node_path": path,
        }

    def retrieve_context(self, state: HelpdeskState) -> dict[str, Any]:
        """Shared by Models 2 and 3 so both see identical evidence."""
        s = self.deps.settings
        path = step(state, "retrieve_context")
        retriever = self.deps.retriever
        if not retriever.ready:
            return {"retrieval": {"ready": False, "returned": 0, "kept": 0}, "retrieved": [], "node_path": path}
        query, condense_meta = self._retrieval_query(state)
        try:
            chunks = retriever.retrieve(query, s.rag_top_k)
        except Exception as exc:  # embedding/vector-store failure must not crash the graph
            return {"node_path": path, "error": _error("retrieval_failed", f"Retrieval failed: {exc}", 502),
                    "condense_llm": condense_meta}
        kept = [c for c in chunks if c.distance is None or c.distance <= s.rag_max_distance]
        return {
            "retrieval": {"ready": True, "returned": len(chunks), "kept": len(kept),
                          "query_rewritten": condense_meta is not None},
            "retrieved": [asdict(c) for c in kept],
            "condense_llm": condense_meta,
            "node_path": path,
        }

    def _retrieval_query(self, state: HelpdeskState) -> tuple[str, dict[str, Any] | None]:
        """The text to search with. A follow-up ("and for the mid semester ones?") is restated as a standalone question using
        the conversation; the same step serves Models 2 and 3 so both retrieve identically. Used for retrieval ONLY."""
        message, history = state["message"], state.get("history", [])
        if not needs_condense(message, history):
            return message, None
        meta: dict[str, Any] = {"called": False, "prompt_version": CONDENSE_PROMPT_VERSION, "used": "fallback", "error": None}
        client = self.deps.primary_llm
        if client is not None:
            meta["called"] = True
            try:
                result = client.complete(build_condense_messages(message, history))
            except Exception as exc:  # never break retrieval because the rewriter failed
                meta["error"] = getattr(exc, "code", type(exc).__name__)
            else:
                meta.update(provider=result.provider, model=result.model, input_tokens=result.input_tokens,
                            output_tokens=result.output_tokens, latency_ms=result.latency_ms,
                            est_cost_usd=estimate_cost_usd(result.model, result.input_tokens, result.output_tokens))
                standalone = parse_standalone(result.text)
                if standalone:
                    meta["used"] = "llm"
                    return standalone, meta
        return fallback_query(message, history), meta

    def rag_answer(self, state: HelpdeskState) -> dict[str, Any]:
        """Model 2: same hosted LLM as Model 1, plus retrieved evidence."""
        assert self.deps.primary_llm is not None
        return self._grounded_answer(state, ModelMode.RAG, self.deps.primary_llm, "rag_answer")

    def rag_peft_answer(self, state: HelpdeskState) -> dict[str, Any]:
        """Model 3: same evidence and prompt as Model 2, answered by the LoRA-adapted endpoint."""
        assert self.deps.model3_llm is not None
        return self._grounded_answer(state, ModelMode.RAG_PEFT, self.deps.model3_llm, "rag_peft_answer")

    def _grounded_answer(self, state: HelpdeskState, mode: ModelMode, client: ChatClient, node: str) -> dict[str, Any]:
        path = step(state, node)
        handled_by = self._handled_by(mode, client)
        chunks = [RetrievedChunk(**c) for c in state.get("retrieved", [])]

        canned: str | None = None
        if not state.get("retrieval", {}).get("ready"):
            canned = NOT_INDEXED_ANSWER
        elif not chunks and self.deps.settings.rag_no_evidence_short_circuit:
            canned = NO_EVIDENCE_ANSWER
        if canned is not None:  # deterministic answer, no LLM call, nothing invented
            return {
                "response": canned,
                "grounded": False,
                "citations": [],
                "handled_by": handled_by,
                "llm": self._llm_meta(mode, None),
                "history": [{"role": "assistant", "content": canned}],
                "node_path": path,
            }

        try:
            result = self._generate(
                state, client, build_rag_messages(state["message"], chunks, self._prior_turns(state)),
                {"handled_by": handled_by},
            )
        except LLMError as exc:
            return {"node_path": path, "error": exc.as_error()}
        citations = [asdict(c) for c in build_citations(result.text, chunks)]
        return {
            "response": result.text,
            "grounded": True,
            "citations": citations,
            "handled_by": handled_by,
            "llm": self._llm_meta(mode, result),
            "history": [{"role": "assistant", "content": result.text}],
            "node_path": path,
        }

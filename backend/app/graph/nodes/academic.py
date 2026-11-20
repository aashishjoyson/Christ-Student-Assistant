"""Academic Q&A nodes: the three model paths.

Model 1: check_model_available -> direct_answer                      (no retriever call)
Model 2: check_model_available -> retrieve_context -> rag_answer      (primary LLM)
Model 3: check_model_available -> retrieve_context -> rag_peft_answer (LoRA endpoint)
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.domain.citations import build_citations
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
                est_cost_usd=estimate_cost_usd(result.model, result.input_tokens, result.output_tokens),
            )
        return meta

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
            result = client.complete(build_direct_messages(state["message"], self._prior_turns(state)))
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
        try:
            chunks = retriever.retrieve(state["message"], s.rag_top_k)
        except Exception as exc:  # embedding/vector-store failure must not crash the graph
            return {"node_path": path, "error": _error("retrieval_failed", f"Retrieval failed: {exc}", 502)}
        kept = [c for c in chunks if c.distance is None or c.distance <= s.rag_max_distance]
        return {
            "retrieval": {"ready": True, "returned": len(chunks), "kept": len(kept)},
            "retrieved": [asdict(c) for c in kept],
            "node_path": path,
        }

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
            result = client.complete(build_rag_messages(state["message"], chunks, self._prior_turns(state)))
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

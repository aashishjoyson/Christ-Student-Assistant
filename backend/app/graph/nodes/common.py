"""Entry, help and fallback nodes. Answers are templates; the only LLM use here is the optional intent-label fallback."""

from __future__ import annotations

from typing import Any

from app.domain.intent_fallback import (
    INTENT_PROMPT_VERSION,
    build_intent_messages,
    needs_llm_fallback,
    parse_intent_label,
)
from app.domain.intents import Intent, IntentResult, classify_intent
from app.domain.pricing import estimate_cost_usd
from app.graph.deps import GraphDeps
from app.graph.state import HelpdeskState, step
from app.llm.base import ChatClient

HELPDESK = {"kind": "helpdesk", "label": "Helpdesk (template, no LLM)"}

HELP_TEXT = (
    "Hi! I'm the student helpdesk prototype. I can:\n"
    "- answer academic questions (calendar, handbook, courses) - pick a model at the top;\n"
    "- show your application status or interview details after you verify with your application ID "
    "and registered email;\n"
    "- re-send your interview email to your registered address if you didn't receive it."
)

FALLBACK_TEXT = (
    "I can't do that here. This helpdesk can answer questions and look up your application or interview, "
    "but it cannot change grades, attendance, fees, applications or interview slots. "
    "Please contact the relevant university office for that."
)


class CommonNodes:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps

    def _llm_intent(self, client: ChatClient, message: str) -> tuple[Intent | None, dict[str, Any]]:
        """Ask the hosted LLM for ONE label. Any failure or unclear reply returns None (the caller keeps academic_qa)."""
        meta: dict[str, Any] = {"called": True, "prompt_version": INTENT_PROMPT_VERSION, "label": None, "error": None}
        try:
            result = client.complete(build_intent_messages(message))
        except Exception as exc:  # a classifier failure must never break the chat; the message is just treated as a question
            meta["error"] = getattr(exc, "code", type(exc).__name__)
            return None, meta
        label = parse_intent_label(result.text)
        meta.update(
            label=label.value if label else None,
            provider=result.provider,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            est_cost_usd=estimate_cost_usd(result.model, result.input_tokens, result.output_tokens),
        )
        return label, meta

    def classify_intent(self, state: HelpdeskState) -> dict[str, Any]:
        message = state["message"]
        result = classify_intent(message)
        update: dict[str, Any] = {"node_path": step(state, "classify_intent")}
        client = self.deps.primary_llm
        # Rules first (free, instant, deterministic). Only when they fell through to the default AND the message
        # looks like a personal request do we spend one small classification call (ADR-015).
        if (
            result.rule == "default_academic"
            and client is not None
            and self.deps.settings.intent_llm_fallback
            and needs_llm_fallback(message)
        ):
            label, meta = self._llm_intent(client, message)
            update["intent_llm"] = meta
            if label is not None and label != Intent.ACADEMIC_QA:
                result = IntentResult(label, "llm_fallback")
        update["intent"] = result.intent.value
        update["intent_rule"] = result.rule
        return update

    def general_help(self, state: HelpdeskState) -> dict[str, Any]:
        return {
            "response": HELP_TEXT,
            "handled_by": HELPDESK,
            "history": [{"role": "assistant", "content": HELP_TEXT}],
            "node_path": step(state, "general_help"),
        }

    def safe_fallback(self, state: HelpdeskState) -> dict[str, Any]:
        return {
            "response": FALLBACK_TEXT,
            "handled_by": HELPDESK,
            "history": [{"role": "assistant", "content": FALLBACK_TEXT}],
            "node_path": step(state, "safe_fallback"),
        }

"""Entry, help and fallback nodes. All deterministic (no LLM calls)."""

from __future__ import annotations

from typing import Any

from app.domain.intents import classify_intent
from app.graph.deps import GraphDeps
from app.graph.state import HelpdeskState, step

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

    def classify_intent(self, state: HelpdeskState) -> dict[str, Any]:
        result = classify_intent(state["message"])
        return {"intent": result.intent.value, "intent_rule": result.rule, "node_path": step(state, "classify_intent")}

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

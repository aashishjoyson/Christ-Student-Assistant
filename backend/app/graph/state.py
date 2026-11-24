"""Typed shared state for the helpdesk graph.

The graph is compiled with a checkpointer keyed by conversation_id (LangGraph thread_id),
so `history` persists across turns. Every other field is per-turn and is reset by
new_turn_input() at the start of each request.

Privacy: applicant-service answers are stored in history as a placeholder, so the LLM
can never repeat an applicant's details in a later turn. Recipient email addresses are
never put in state; nodes re-read them from the database when needed.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

MAX_STORED_TURNS = 20
APPLICANT_HISTORY_PLACEHOLDER = "[Applicant-service answer withheld from conversation memory]"


class ChatTurn(TypedDict):
    role: str  # "user" | "assistant"
    content: str


def append_turns(left: list[ChatTurn] | None, right: list[ChatTurn] | None) -> list[ChatTurn]:
    """Reducer: append new turns and keep only the most recent MAX_STORED_TURNS."""
    return ((left or []) + (right or []))[-MAX_STORED_TURNS:]


class HelpdeskState(TypedDict, total=False):
    # ---- persisted across turns ----
    history: Annotated[list[ChatTurn], append_turns]

    # ---- per-turn input ----
    conversation_id: str
    request_id: str
    message: str
    model_mode: str  # ModelMode value
    applicant_token: str | None

    # ---- per-turn derived ----
    intent: str
    intent_rule: str
    intent_llm: dict[str, Any] | None  # set only when the LLM fallback ran: tokens, latency, label, error
    verified: bool
    applicant_id: int | None
    retrieval: dict[str, Any]  # {"ready": bool, "returned": int, "kept": int}
    retrieved: list[dict[str, Any]]  # RetrievedChunk as dicts
    citations: list[dict[str, Any]]
    grounded: bool | None
    application: dict[str, Any] | None
    interview: dict[str, Any] | None
    eligibility: dict[str, Any] | None
    notification: dict[str, Any] | None
    action_status: str | None  # verification_required | sent | simulated | failed | not_eligible
    response: str
    notice: str | None
    handled_by: dict[str, Any]
    llm: dict[str, Any] | None  # provider, model, prompt_version, tokens, latency
    error: dict[str, Any] | None  # {"code", "message", "http_status"}
    node_path: list[str]


PER_TURN_DEFAULTS: dict[str, Any] = {
    "intent": "",
    "intent_rule": "",
    "intent_llm": None,
    "verified": False,
    "applicant_id": None,
    "retrieval": {},
    "retrieved": [],
    "citations": [],
    "grounded": None,
    "application": None,
    "interview": None,
    "eligibility": None,
    "notification": None,
    "action_status": None,
    "response": "",
    "notice": None,
    "handled_by": {},
    "llm": None,
    "error": None,
    "node_path": [],
}


def new_turn_input(
    *,
    conversation_id: str,
    request_id: str,
    message: str,
    model_mode: str,
    applicant_token: str | None,
) -> dict[str, Any]:
    """Input for one graph invocation: resets per-turn fields and appends the user turn."""
    return {
        **PER_TURN_DEFAULTS,
        "conversation_id": conversation_id,
        "request_id": request_id,
        "message": message,
        "model_mode": model_mode,
        "applicant_token": applicant_token,
        "history": [{"role": "user", "content": message}],
    }


def step(state: HelpdeskState, node_name: str) -> list[str]:
    """Return node_path with this node appended (no reducer, so each turn starts empty)."""
    return [*state.get("node_path", []), node_name]

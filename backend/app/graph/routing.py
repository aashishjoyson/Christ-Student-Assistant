"""Conditional-edge functions. Pure: they read state and return the next node name.

Kept free of langgraph imports so they are unit-testable on their own.
END_NODE equals langgraph's END constant (asserted in builder.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.domain.intents import Intent
from app.domain.model_modes import ModelMode

END_NODE = "__end__"

State = Mapping[str, Any]


def route_by_intent(state: State) -> str:
    intent = state.get("intent")
    if intent == Intent.ACADEMIC_QA:
        return "check_model_available"
    if intent in (Intent.APPLICANT_STATUS, Intent.INTERVIEW_DETAILS, Intent.RESEND_INTERVIEW_EMAIL):
        return "verify_identity"
    if intent == Intent.GENERAL_HELP:
        return "general_help"
    return "safe_fallback"


def route_by_mode(state: State) -> str:
    if state.get("error"):
        return END_NODE
    if state.get("model_mode") == ModelMode.DIRECT:
        return "direct_answer"
    return "retrieve_context"


def route_after_retrieval(state: State) -> str:
    if state.get("error"):
        return END_NODE
    if state.get("model_mode") == ModelMode.RAG_PEFT:
        return "rag_peft_answer"
    return "rag_answer"


def route_after_verify(state: State) -> str:
    if not state.get("verified"):
        return END_NODE  # verify_identity already wrote the "please verify" response
    if state.get("intent") == Intent.APPLICANT_STATUS:
        return "fetch_application_status"
    return "fetch_interview_details"


def route_after_interview(state: State) -> str:
    if state.get("intent") == Intent.RESEND_INTERVIEW_EMAIL:
        return "check_resend_eligibility"
    return "compose_applicant_response"


def route_after_eligibility(state: State) -> str:
    eligibility = state.get("eligibility") or {}
    return "send_interview_email" if eligibility.get("eligible") else "compose_applicant_response"

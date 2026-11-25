"""Wraps every graph node so the live dashboard can show what it did: which component, a plain sentence, how long, and safe detail.

The wrapper changes nothing about the node: it calls it, returns exactly what it returned and re-raises what it raised. All the description
logic is in `describe` (pure; tested without a bus). Detail never includes message text, answers or passages (app/core/flow.py drops them)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

from app.core import flow
from app.graph.state import HelpdeskState

NodeFn = Callable[[HelpdeskState], dict[str, Any]]

# What each node is about to do, and which box on the map is doing it.
START: dict[str, tuple[str, str]] = {
    "classify_intent": ("rules", "Deciding what the message is about"),
    "check_model_available": ("graph", "Checking that the chosen model is configured"),
    "direct_answer": ("llm_openai", "Asking the model directly, with no documents"),
    "retrieve_context": ("chroma", "Searching the university documents"),
    "rag_answer": ("llm_openai", "Writing the answer from the passages"),
    "rag_peft_answer": ("llm_modal", "Writing the answer with the fine-tuned model"),
    "verify_identity": ("graph", "Checking the applicant's signed session"),
    "fetch_application_status": ("sqlite", "Reading the applicant's own application record"),
    "fetch_interview_details": ("sqlite", "Reading the applicant's own interview record"),
    "check_resend_eligibility": ("sqlite", "Applying the resend rules and reserving the send"),
    "send_interview_email": ("email", "Sending the interview email"),
    "record_notification": ("sqlite", "Recording the outcome in the audit table"),
    "compose_applicant_response": ("graph", "Writing the answer from a fixed template"),
    "general_help": ("graph", "Replying with the help text"),
    "safe_fallback": ("graph", "Refusing a request this helpdesk cannot do"),
}

SMTP_STEP_LABELS = {
    "connect": "Connected to the mail server",
    "starttls": "Upgraded the connection to TLS (certificate and host name checked)",
    "login": "Logged in with the app password",
    "send": "Handed the message to the server",
}


@dataclass(frozen=True)
class Step:
    name: str
    service: str
    label: str
    ms: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Summary:
    service: str
    label: str
    detail: dict[str, Any] = field(default_factory=dict)
    steps: tuple[Step, ...] = ()


def _provider_service(provider: str | None) -> str:
    return "llm_modal" if provider == "model3-endpoint" else "llm_openai"


def _llm_detail(llm: dict[str, Any]) -> dict[str, Any]:
    if not llm.get("called"):
        return {"llm_called": False}
    return {"llm_called": True, "provider": llm.get("provider"), "model": llm.get("model"), "prompt_version": llm.get("prompt_version"),
            "input_tokens": llm.get("input_tokens"), "output_tokens": llm.get("output_tokens"), "first_token_ms": llm.get("first_token_ms"),
            "llm_ms": llm.get("latency_ms"), "est_cost_usd": llm.get("est_cost_usd"), "finish_reason": llm.get("finish_reason")}


def _side_call(name: str, label: str, meta: dict[str, Any]) -> Step:
    return Step(name, _provider_service(meta.get("provider")), label, meta.get("latency_ms"),
                {"model": meta.get("model"), "input_tokens": meta.get("input_tokens"), "output_tokens": meta.get("output_tokens"),
                 "label": meta.get("label"), "used": meta.get("used"), "error": meta.get("error")})


def _classify(state: HelpdeskState, update: dict[str, Any]) -> Summary:
    llm = update.get("intent_llm") or {}
    steps = (_side_call("intent_llm", "The rules were unsure, so the hosted model chose ONE label (it saw the message, nothing else)", llm),) if llm.get("called") else ()
    return Summary("rules", f"Routed to '{update.get('intent')}' (rule: {update.get('intent_rule')})",
                   {"intent": update.get("intent"), "rule": update.get("intent_rule"), "llm_fallback": bool(llm.get("called"))}, steps)


def _check_model(state: HelpdeskState, update: dict[str, Any]) -> Summary:
    error = update.get("error")
    detail = {"model_mode": state.get("model_mode")}
    if error:
        return Summary("graph", "The chosen model is not available (no other model is substituted)", {**detail, "error": error.get("code")})
    return Summary("graph", "The chosen model is configured", detail)


def _answer(state: HelpdeskState, update: dict[str, Any]) -> Summary:
    llm, handled, error = update.get("llm") or {}, update.get("handled_by") or {}, update.get("error")
    service = _provider_service(llm.get("provider") or handled.get("provider"))
    if error:
        return Summary(service, f"The model call failed ({error.get('code')})", {"error": error.get("code")})
    citations = update.get("citations") or []
    supplied = len(state.get("retrieved") or [])
    detail = {**_llm_detail(llm), "grounded": update.get("grounded"), "citations": len(citations),
              "cited": sum(1 for c in citations if c.get("cited")), "passages_supplied": supplied}
    if not llm.get("called"):
        return Summary("graph", "Nothing matched well enough, so a fixed 'I could not find this' answer was used (no model call)", detail)
    return Summary(service, f"{llm.get('model')} wrote the answer" + (f" from {supplied} passages" if supplied else " with no documents"), detail)


def _retrieve(state: HelpdeskState, update: dict[str, Any]) -> Summary:
    retrieval, condense, error = update.get("retrieval") or {}, update.get("condense_llm") or {}, update.get("error")
    steps = (_side_call("condense_query", "Rewrote the follow-up as a standalone question (used for searching only)", condense),) if condense.get("called") else ()
    if error:
        return Summary("chroma", "The search failed", {"error": error.get("code")}, steps)
    if not retrieval.get("ready"):
        return Summary("chroma", "The index is empty: nothing has been indexed yet", {"ready": False}, steps)
    sources = [{"source": c.get("source_name"), "page": c.get("page"), "distance": c.get("distance")} for c in (update.get("retrieved") or [])][:8]
    best = retrieval.get("best_distance")
    label = f"Found {retrieval.get('returned')} passages and kept {retrieval.get('kept')}" + (f" (nearest distance {best})" if best is not None else "")
    return Summary("chroma", label, {**retrieval, "sources": sources}, steps)


def _verify(state: HelpdeskState, update: dict[str, Any]) -> Summary:
    ok = bool(update.get("verified"))
    return Summary("graph", "The signed session is valid: the applicant is verified" if ok else "No valid session: the visitor is asked to verify first",
                   {"verified": ok})


def _eligibility(state: HelpdeskState, update: dict[str, Any]) -> Summary:
    eligibility, notification = update.get("eligibility") or {}, update.get("notification") or {}
    ok, reserved = bool(eligibility.get("eligible")), "event_id" in notification
    label = "Allowed: the send is reserved (one per cooldown window)" if ok and reserved else f"Not sent: {eligibility.get('reason')}"
    return Summary("sqlite", label, {"eligible": ok, "reason": eligibility.get("reason"), "reserved": reserved,
                                     "masked_recipient": notification.get("masked_recipient")})


def _send(state: HelpdeskState, update: dict[str, Any]) -> Summary:
    n = update.get("notification") or {}
    steps = tuple(Step(f"{n.get('provider')}_{name}", "email", SMTP_STEP_LABELS.get(name, name), ms) for name, ms in (n.get("send_steps") or []))
    labels = {"sent": "The mail server accepted the message", "failed": "The send failed",
              "simulated": "Wrote the message to the local outbox (simulated: nothing is delivered)"}
    return Summary("email", labels.get(n.get("send_status"), "Sent"),
                   {"provider": n.get("provider"), "status": n.get("send_status"), "mail_id": n.get("provider_message_id"), "error": n.get("send_error")}, steps)


def _fixed(service: str, label: str, **keys: str) -> Callable[[HelpdeskState, dict[str, Any]], Summary]:
    """A node whose summary is a fixed sentence plus a few state keys (booleans and short codes only)."""
    def describe_fixed(state: HelpdeskState, update: dict[str, Any]) -> Summary:
        detail = {out: update.get(src) for out, src in keys.items()}
        return Summary(service, label, detail)
    return describe_fixed


_DESCRIBERS: dict[str, Callable[[HelpdeskState, dict[str, Any]], Summary]] = {
    "classify_intent": _classify,
    "check_model_available": _check_model,
    "direct_answer": _answer,
    "rag_answer": _answer,
    "rag_peft_answer": _answer,
    "retrieve_context": _retrieve,
    "verify_identity": _verify,
    "fetch_application_status": lambda s, u: Summary("sqlite", "Read the applicant's own record with a fixed query", {"found": bool(u.get("application"))}),
    "fetch_interview_details": lambda s, u: Summary("sqlite", "Read the applicant's own interview with a fixed query", {"has_interview": bool(u.get("interview"))}),
    "check_resend_eligibility": _eligibility,
    "send_interview_email": _send,
    "record_notification": lambda s, u: Summary("sqlite", f"Recorded '{u.get('action_status')}' in the audit table", {"status": u.get("action_status")}),
    "compose_applicant_response": _fixed("graph", "Wrote the answer from a fixed template (no model involved)", action="action_status"),
    "general_help": _fixed("graph", "Replied with the fixed help text (no model involved)"),
    "safe_fallback": _fixed("graph", "Declined: this helpdesk answers and looks up, it never changes records"),
}


def describe(name: str, state: HelpdeskState, update: dict[str, Any]) -> Summary:
    """Never raises: a description bug must not touch the chat."""
    describer = _DESCRIBERS.get(name)
    if describer is None:
        return Summary("graph", name)
    try:
        return describer(state, update)
    except Exception:
        return Summary(START.get(name, ("graph", ""))[0], name)


def traced(name: str, fn: NodeFn) -> NodeFn:
    """The node itself, unchanged, plus a 'start' and an 'end' event (and one event per sub-step it reports)."""

    @wraps(fn)
    def run(state: HelpdeskState) -> dict[str, Any]:
        if flow.current_bus() is None:
            return fn(state)
        trace_id = str(state.get("request_id") or "")
        service, doing = START.get(name, ("graph", name))
        with flow.trace_scope(trace_id):
            flow.emit("node", name, "start", service, doing)
            started = time.perf_counter()
            try:
                update = fn(state)
            except Exception as exc:
                flow.emit("node", name, "error", service, f"{name} failed", ms=round((time.perf_counter() - started) * 1000),
                          detail={"error": type(exc).__name__})
                raise
            ms = round((time.perf_counter() - started) * 1000)
            summary = describe(name, state, update)
            for sub in summary.steps:
                flow.emit("step", sub.name, "end", sub.service, sub.label, ms=sub.ms, detail=sub.detail)
            failed = bool(update.get("error"))
            flow.emit("node", name, "error" if failed else "end", summary.service, summary.label, ms=ms, detail=summary.detail)
            return update

    return run

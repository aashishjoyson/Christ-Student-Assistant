"""What the dashboard says about each graph node, and that wrapping a node changes nothing about it."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.core import flow
from app.core.flow import SERVICES, FlowBus
from app.graph.flow_nodes import START, describe, traced

PRIVATE = "PRIVATE-QUESTION-TEXT"


def run_traced(name: str, update: dict[str, Any], state: dict[str, Any] | None = None) -> tuple[dict[str, Any], FlowBus]:
    bus = FlowBus()
    flow.install(bus)
    node = traced(name, lambda s: update)
    result = node({"request_id": "req-9", "message": PRIVATE, **(state or {})})  # type: ignore[arg-type]
    return result, bus


def test_a_wrapped_node_returns_exactly_what_it_returned() -> None:
    update = {"intent": "academic_qa", "intent_rule": "default_academic", "node_path": ["classify_intent"]}
    result, bus = run_traced("classify_intent", update)
    assert result is update
    start, end = bus.since(0)
    assert (start.phase, end.phase) == ("start", "end") and start.trace_id == end.trace_id == "req-9"
    assert end.service == "rules" and "academic_qa" in end.label and end.ms is not None


def test_without_a_bus_the_wrapper_is_a_plain_call() -> None:
    flow.install(None)
    assert traced("classify_intent", lambda s: {"intent": "x"})({"message": "hi"}) == {"intent": "x"}  # type: ignore[arg-type]


def test_a_node_that_raises_is_reported_and_the_exception_is_not_swallowed() -> None:
    bus = FlowBus()
    flow.install(bus)

    def broken(state: dict) -> dict:
        raise ValueError(f"failed on {PRIVATE}")

    with pytest.raises(ValueError, match="failed on"):
        traced("retrieve_context", broken)({"request_id": "r"})  # type: ignore[arg-type]
    end = bus.since(0)[-1]
    assert end.phase == "error" and end.detail == {"error": "ValueError"} and PRIVATE not in json.dumps(end.as_dict())


def test_a_node_that_returns_an_error_is_shown_as_an_error() -> None:
    _, bus = run_traced("check_model_available", {"error": {"code": "model3_not_configured", "message": "long text", "http_status": 503}},
                        {"model_mode": "rag_peft"})
    end = bus.since(0)[-1]
    assert end.phase == "error" and end.detail["error"] == "model3_not_configured" and "no other model" in end.label


def test_the_fallback_model_call_for_intent_is_its_own_visible_step() -> None:
    llm = {"called": True, "provider": "openai", "model": "gpt-x", "label": "resend_interview_email", "input_tokens": 80, "output_tokens": 3, "latency_ms": 420}
    _, bus = run_traced("classify_intent", {"intent": "resend_interview_email", "intent_rule": "llm_fallback", "intent_llm": llm})
    names = [(e.kind, e.name, e.service) for e in bus.since(0)]
    assert ("step", "intent_llm", "llm_openai") in names
    step = next(e for e in bus.since(0) if e.name == "intent_llm")
    assert step.ms == 420 and step.detail["input_tokens"] == 80


def test_retrieval_reports_counts_distances_and_source_names_but_never_passage_text() -> None:
    retrieved = [{"source_name": "handbook.pdf", "page": 29, "distance": 0.2211, "text": f"{PRIVATE} passage body", "chunk_id": "c1"}]
    update = {"retrieval": {"ready": True, "returned": 8, "kept": 1, "top_k": 8, "best_distance": 0.2211, "query_rewritten": True},
              "retrieved": retrieved, "condense_llm": {"called": True, "used": "llm", "provider": "openai", "model": "gpt-x", "latency_ms": 300}}
    _, bus = run_traced("retrieve_context", update)
    dump = json.dumps([e.as_dict() for e in bus.since(0)])
    assert PRIVATE not in dump and "handbook.pdf" in dump and "0.2211" in dump
    assert any(e.name == "condense_query" for e in bus.since(0))


def test_an_answer_node_names_the_model_tokens_and_citations() -> None:
    llm = {"called": True, "provider": "model3-endpoint", "model": "cu-helpdesk-lora", "prompt_version": "rag-v2", "input_tokens": 900,
           "output_tokens": 30, "first_token_ms": 700, "latency_ms": 1500}
    update = {"llm": llm, "grounded": True, "citations": [{"cited": True}, {"cited": False}], "response": PRIVATE}
    _, bus = run_traced("rag_peft_answer", update, {"retrieved": [{}, {}, {}]})
    end = bus.since(0)[-1]
    assert end.service == "llm_modal" and end.label == "cu-helpdesk-lora wrote the answer from 3 passages"
    assert end.detail["citations"] == 2 and end.detail["cited"] == 1 and end.detail["prompt_version"] == "rag-v2"
    assert PRIVATE not in json.dumps(end.as_dict())


def test_a_fixed_no_evidence_answer_says_that_no_model_was_called() -> None:
    _, bus = run_traced("rag_answer", {"llm": {"called": False, "prompt_version": "rag-v2"}, "grounded": False, "citations": []})
    end = bus.since(0)[-1]
    assert end.service == "graph" and "no model call" in end.label and end.detail["llm_called"] is False


def test_the_email_steps_are_listed_one_by_one_without_the_address() -> None:
    notification = {"provider": "smtp", "send_status": "sent", "provider_message_id": "<1.2@gmail.com>", "send_error": None,
                    "send_steps": [["connect", 120], ["starttls", 180], ["login", 400], ["send", 500]], "masked_recipient": "a***o@gmail.com"}
    _, bus = run_traced("send_interview_email", {"notification": notification})
    events = bus.since(0)
    steps = [e for e in events if e.kind == "step"]
    assert [(e.name, e.ms) for e in steps] == [("smtp_connect", 120), ("smtp_starttls", 180), ("smtp_login", 400), ("smtp_send", 500)]
    assert all(e.service == "email" for e in steps) and "accepted" in events[-1].label and events[-1].detail["mail_id"] == "<1.2@gmail.com>"


def test_a_simulated_email_is_labelled_as_not_delivered() -> None:
    _, bus = run_traced("send_interview_email", {"notification": {"provider": "console", "send_status": "simulated"}})
    assert "nothing is delivered" in bus.since(0)[-1].label


def test_the_resend_rules_event_shows_the_decision_not_the_address() -> None:
    update = {"eligibility": {"eligible": False, "reason": "cooldown_active"}, "notification": {"masked_recipient": "a***o@example.com"}}
    _, bus = run_traced("check_resend_eligibility", update)
    end = bus.since(0)[-1]
    assert "cooldown_active" in end.label and end.detail["reserved"] is False and end.detail["masked_recipient"] == "a***o@example.com"


def test_every_description_names_a_box_that_exists_on_the_map() -> None:
    for name, (service, _) in START.items():
        assert service in SERVICES, name
        summary = describe(name, {}, {})  # type: ignore[arg-type]
        assert summary.service in SERVICES and summary.label, name


def test_describing_never_raises_even_for_surprising_updates() -> None:
    summary = describe("retrieve_context", {}, {"retrieval": "not a dict", "retrieved": 5})  # type: ignore[arg-type]
    assert summary.service in SERVICES
    assert describe("unknown_node", {}, {}).service == "graph"  # type: ignore[arg-type]

from app.domain.intents import Intent
from app.domain.model_modes import ModelMode
from app.graph.routing import (
    END_NODE,
    route_after_eligibility,
    route_after_interview,
    route_after_retrieval,
    route_after_verify,
    route_by_intent,
    route_by_mode,
)
from app.graph.state import MAX_STORED_TURNS, append_turns, new_turn_input


def test_route_by_intent() -> None:
    assert route_by_intent({"intent": Intent.ACADEMIC_QA}) == "check_model_available"
    assert route_by_intent({"intent": Intent.APPLICANT_STATUS}) == "verify_identity"
    assert route_by_intent({"intent": Intent.RESEND_INTERVIEW_EMAIL}) == "verify_identity"
    assert route_by_intent({"intent": Intent.GENERAL_HELP}) == "general_help"
    assert route_by_intent({"intent": Intent.UNSUPPORTED}) == "safe_fallback"
    assert route_by_intent({}) == "safe_fallback"


def test_model_1_never_routes_to_retrieval() -> None:
    assert route_by_mode({"model_mode": ModelMode.DIRECT}) == "direct_answer"
    assert route_by_mode({"model_mode": ModelMode.RAG}) == "retrieve_context"
    assert route_by_mode({"model_mode": ModelMode.RAG_PEFT}) == "retrieve_context"


def test_unconfigured_model_stops_before_any_call() -> None:
    error = {"code": "model3_not_configured"}
    assert route_by_mode({"model_mode": ModelMode.RAG_PEFT, "error": error}) == END_NODE


def test_route_after_retrieval_never_crosses_models() -> None:
    assert route_after_retrieval({"model_mode": ModelMode.RAG}) == "rag_answer"
    assert route_after_retrieval({"model_mode": ModelMode.RAG_PEFT}) == "rag_peft_answer"


def test_unverified_applicant_stops() -> None:
    assert route_after_verify({"verified": False, "intent": Intent.APPLICANT_STATUS}) == END_NODE
    assert route_after_verify({"verified": True, "intent": Intent.APPLICANT_STATUS}) == "fetch_application_status"
    assert route_after_verify({"verified": True, "intent": Intent.RESEND_INTERVIEW_EMAIL}) == "fetch_interview_details"


def test_email_path() -> None:
    assert route_after_interview({"intent": Intent.RESEND_INTERVIEW_EMAIL}) == "check_resend_eligibility"
    assert route_after_interview({"intent": Intent.INTERVIEW_DETAILS}) == "compose_applicant_response"
    assert route_after_eligibility({"eligibility": {"eligible": True}}) == "send_interview_email"
    assert route_after_eligibility({"eligibility": {"eligible": False}}) == "compose_applicant_response"


def test_history_reducer_trims() -> None:
    turns = [{"role": "user", "content": str(i)} for i in range(MAX_STORED_TURNS + 5)]
    assert len(append_turns([], turns)) == MAX_STORED_TURNS
    assert append_turns(None, None) == []


def test_new_turn_input_resets_per_turn_fields() -> None:
    state = new_turn_input(conversation_id="c", request_id="r", message="hi", model_mode="rag", applicant_token=None)
    assert state["node_path"] == [] and state["error"] is None and state["citations"] == []
    assert state["history"] == [{"role": "user", "content": "hi"}]

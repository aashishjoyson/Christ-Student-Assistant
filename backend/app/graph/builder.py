"""Builds and compiles the helpdesk StateGraph (one supervisor/router + deterministic specialist nodes).

Run `python scripts/export_graph_diagram.py` to regenerate docs/graph.mmd from this code.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph import routing
from app.graph.deps import GraphDeps
from app.graph.nodes.academic import AcademicNodes
from app.graph.nodes.applicant import ApplicantNodes
from app.graph.nodes.common import CommonNodes
from app.graph.state import HelpdeskState

assert routing.END_NODE == END, "routing.END_NODE must match langgraph END"


def build_graph(deps: GraphDeps, checkpointer: BaseCheckpointSaver | None = None):  # type: ignore[no-untyped-def]
    common = CommonNodes(deps)
    academic = AcademicNodes(deps)
    applicant = ApplicantNodes(deps)

    g = StateGraph(HelpdeskState)

    # Supervisor / router
    g.add_node("classify_intent", common.classify_intent)
    # Academic Q&A (three model paths)
    g.add_node("check_model_available", academic.check_model_available)
    g.add_node("direct_answer", academic.direct_answer)
    g.add_node("retrieve_context", academic.retrieve_context)
    g.add_node("rag_answer", academic.rag_answer)
    g.add_node("rag_peft_answer", academic.rag_peft_answer)
    # Applicant services + interview email workflow
    g.add_node("verify_identity", applicant.verify_identity)
    g.add_node("fetch_application_status", applicant.fetch_application_status)
    g.add_node("fetch_interview_details", applicant.fetch_interview_details)
    g.add_node("check_resend_eligibility", applicant.check_resend_eligibility)
    g.add_node("send_interview_email", applicant.send_interview_email)
    g.add_node("record_notification", applicant.record_notification)
    g.add_node("compose_applicant_response", applicant.compose_applicant_response)
    # Templates
    g.add_node("general_help", common.general_help)
    g.add_node("safe_fallback", common.safe_fallback)

    g.add_edge(START, "classify_intent")
    g.add_conditional_edges(
        "classify_intent",
        routing.route_by_intent,
        {n: n for n in ("check_model_available", "verify_identity", "general_help", "safe_fallback")},
    )
    g.add_conditional_edges(
        "check_model_available",
        routing.route_by_mode,
        {"direct_answer": "direct_answer", "retrieve_context": "retrieve_context", END: END},
    )
    g.add_conditional_edges(
        "retrieve_context",
        routing.route_after_retrieval,
        {"rag_answer": "rag_answer", "rag_peft_answer": "rag_peft_answer", END: END},
    )
    g.add_conditional_edges(
        "verify_identity",
        routing.route_after_verify,
        {"fetch_application_status": "fetch_application_status", "fetch_interview_details": "fetch_interview_details",
         END: END},
    )
    g.add_edge("fetch_application_status", "compose_applicant_response")
    g.add_conditional_edges(
        "fetch_interview_details",
        routing.route_after_interview,
        {"check_resend_eligibility": "check_resend_eligibility",
         "compose_applicant_response": "compose_applicant_response"},
    )
    g.add_conditional_edges(
        "check_resend_eligibility",
        routing.route_after_eligibility,
        {"send_interview_email": "send_interview_email", "compose_applicant_response": "compose_applicant_response"},
    )
    g.add_edge("send_interview_email", "record_notification")
    g.add_edge("record_notification", "compose_applicant_response")

    for terminal in ("direct_answer", "rag_answer", "rag_peft_answer", "compose_applicant_response",
                     "general_help", "safe_fallback"):
        g.add_edge(terminal, END)

    # In-memory checkpointer: keeps per-conversation history (thread_id = conversation_id).
    # Lost on restart; fine for a local prototype (see ADR-006).
    return g.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())

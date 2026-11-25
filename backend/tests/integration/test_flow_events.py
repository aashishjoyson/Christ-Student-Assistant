"""The live flow dashboard end to end: a real chat turn through the real graph produces the right events, in order, with nothing private in them,
and the admin endpoints that serve them (and what Evidently said) are protected."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from tests.fakes_smtp import make_provider
from tests.integration.conftest import Env

KEY = {"X-Admin-Key": "test-admin-key"}
QUESTION = "When do classes begin?"


def turn_events(env: Env, message_id: str) -> list[dict]:
    assert env.container.flow is not None
    return [e.as_dict() for e in env.container.flow.since(0, 1000) if e.trace_id == message_id]


def names(events: list[dict], phase: str | None = None) -> list[str]:
    return [e["name"] for e in events if phase is None or e["phase"] == phase]


def test_a_document_question_shows_every_step_in_order(env: Env) -> None:
    body = env.chat(QUESTION).json()
    events = turn_events(env, body["message_id"])
    assert names(events, "start") == ["request", "classify_intent", "check_model_available", "retrieve_context", "rag_answer"]
    assert names(events, "end") == ["classify_intent", "check_model_available", "retrieve_context", "rag_answer", "trace", "request"]
    assert events[0]["name"] == "request" and events[-1]["name"] == "request" and events[-1]["phase"] == "end"
    answer = next(e for e in events if e["name"] == "rag_answer" and e["phase"] == "end")
    assert answer["service"] == "llm_openai" and answer["detail"]["grounded"] is True and answer["ms"] is not None
    retrieval = next(e for e in events if e["name"] == "retrieve_context" and e["phase"] == "end")
    assert retrieval["service"] == "chroma" and retrieval["detail"]["returned"] >= 1
    assert events[-1]["detail"]["path"][:2] == ["classify_intent", "check_model_available"]


def test_no_event_contains_what_the_visitor_typed_or_what_was_answered(env: Env) -> None:
    body = env.chat(QUESTION).json()
    dump = json.dumps(turn_events(env, body["message_id"])).lower()
    assert "classes begin" not in dump and QUESTION.lower() not in dump and body["answer"].lower() not in dump
    assert "message_chars" in dump  # only how long the message was


def test_model_one_never_touches_the_index(env: Env) -> None:
    body = env.chat(QUESTION, mode="direct").json()
    events = turn_events(env, body["message_id"])
    assert "retrieve_context" not in names(events) and "direct_answer" in names(events, "end")


def test_a_greeting_is_answered_from_a_template_with_no_model(env: Env) -> None:
    body = env.chat("hello").json()
    events = turn_events(env, body["message_id"])
    end = next(e for e in events if e["name"] == "general_help" and e["phase"] == "end")
    assert "no model involved" in end["label"] and not any(e["service"] in {"llm_openai", "llm_modal"} for e in events)


def test_the_interview_email_flow_is_visible_step_by_step_and_never_shows_the_address(make_env: Callable[..., Env]) -> None:
    provider, _ = make_provider()
    env = make_env(email=provider, email_provider="smtp", email_send_enabled=True, email_recipient_allowlist="aarav.demo@example.com")
    body = env.chat("I have not received my interview email", token=env.token_for("CUAPP-DEMO-0001")).json()
    events = turn_events(env, body["message_id"])
    ends = names(events, "end")
    assert ends.index("verify_identity") < ends.index("check_resend_eligibility") < ends.index("smtp_connect") < ends.index("send_interview_email")
    assert ends.index("send_interview_email") < ends.index("record_notification") < ends.index("compose_applicant_response")
    assert [n for n in ends if n.startswith("smtp_")] == ["smtp_connect", "smtp_starttls", "smtp_login", "smtp_send"]
    send = next(e for e in events if e["name"] == "send_interview_email" and e["phase"] == "end")
    assert send["service"] == "email" and send["detail"]["status"] == "sent" and send["detail"]["mail_id"].startswith("<")
    dump = json.dumps(events)
    assert "aarav.demo@example.com" not in dump and "meet.example.com" not in dump and "abcdefghijklmnop" not in dump
    assert not any(e["service"] in {"llm_openai", "llm_modal"} for e in events)  # the email path involves no model at all


def test_a_failed_send_is_an_error_event_with_a_safe_reason(make_env: Callable[..., Env]) -> None:
    import smtplib

    from tests.fakes_smtp import Script

    provider, _ = make_provider(Script(login_error=smtplib.SMTPAuthenticationError(535, b"5.7.8 not accepted")))
    env = make_env(email=provider, email_provider="smtp", email_send_enabled=True, email_recipient_allowlist="aarav.demo@example.com")
    body = env.chat("I have not received my interview email", token=env.token_for("CUAPP-DEMO-0001")).json()
    send = next(e for e in turn_events(env, body["message_id"]) if e["name"] == "send_interview_email" and e["phase"] == "end")
    assert send["detail"]["status"] == "failed" and "535" in send["detail"]["error"]


# ---------- endpoints ----------
def test_the_flow_endpoints_need_the_admin_key(env: Env) -> None:
    for path in ("/api/admin/flow/recent", "/api/admin/flow/services", "/api/admin/flow/stream?max_seconds=0.2", "/api/admin/flow/evidently"):
        assert env.client.get(path).status_code == 401, path
        assert env.client.get(path, headers={"X-Admin-Key": "wrong"}).status_code == 401, path


def test_recent_returns_events_and_a_cursor(env: Env) -> None:
    env.chat(QUESTION)
    body = env.client.get("/api/admin/flow/recent", headers=KEY).json()
    assert body["enabled"] is True and body["last_seq"] == len(body["events"]) > 5
    newer = env.client.get(f"/api/admin/flow/recent?since={body['last_seq'] - 1}", headers=KEY).json()
    assert [e["seq"] for e in newer["events"]] == [body["last_seq"]]


def test_the_services_endpoint_lists_every_box(env: Env) -> None:
    services = env.client.get("/api/admin/flow/services", headers=KEY).json()["services"]
    assert services["chroma"]["group"] == "data" and services["llm_modal"]["label"] == "Model 3 on Modal"


def test_the_stream_replays_from_a_cursor_in_server_sent_event_format_and_then_ends(env: Env) -> None:
    env.chat(QUESTION)
    with env.client.stream("GET", "/api/admin/flow/stream?since=0&max_seconds=0.6", headers=KEY) as response:
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    frames = [f for f in text.split("\n\n") if f.startswith("id:")]
    assert len(frames) > 5 and "event: flow" in frames[0]
    first = json.loads(next(line for line in frames[0].splitlines() if line.startswith("data:"))[5:])
    assert first["seq"] == 1 and first["name"] == "request"


def test_switching_the_events_off_is_visible_and_the_stream_says_so(make_env: Callable[..., Env]) -> None:
    env = make_env(flow_events_enabled=False)
    env.chat(QUESTION)
    assert env.client.get("/api/admin/flow/recent", headers=KEY).json() == {"enabled": False, "last_seq": 0, "events": []}
    assert env.client.get("/api/admin/flow/stream?max_seconds=0.2", headers=KEY).status_code == 503


# ---------- Evidently ----------
def outcome_metric(group: str, label: str, outcome: str, count: int) -> dict:
    return {"metric_name": f"GroupByMetric(column_name={group},label={label})",
            "config": {"type": "evidently:metric_v2:GroupByMetric", "column_name": group, "label": label,
                       "metric": {"type": "evidently:metric_v2:CategoryCount", "column": "outcome", "categories": [outcome]}},
            "value": {"count": float(count), "share": 0.1}}


def write_run(eval_dir: Path, name: str, with_html: bool = True) -> None:
    run = eval_dir / name
    run.mkdir(parents=True)
    metrics = [outcome_metric("mode", "rag", "correct", 28), outcome_metric("mode", "rag", "false_refusal", 2),
               outcome_metric("mode", "rag_peft", "correct", 24), outcome_metric("mode", "rag_peft", "wrong_answer", 3),
               outcome_metric("category", "calendar", "correct", 29),
               {"metric_name": "CategoryCount(column=citations_valid)", "config": {"type": "evidently:metric_v2:CategoryCount"}, "value": {"count": 0.0}}]
    tests = [{"name": "Column 'citations_valid' categories 'no': Equal 0.000", "description": "Actual value 0.000 expected 0.000", "status": "SUCCESS"}]
    (run / "evidently_evaluation.json").write_text(json.dumps({"metrics": metrics, "tests": tests}), encoding="utf-8")
    if with_html:
        (run / "evidently_evaluation.html").write_text("<html><body>report</body></html>", encoding="utf-8")


def test_evidently_summary_reads_the_latest_run_with_a_report(make_env: Callable[..., Env], tmp_path: Path) -> None:
    evals = tmp_path / "evals"
    write_run(evals, "eval-20260101-000000-aaaaaa")
    write_run(evals, "eval-20260102-000000-bbbbbb")
    (evals / "eval-20260103-000000-cccccc").mkdir()  # newest, but no report: it is skipped
    env = make_env(eval_dir=evals)
    body = env.client.get("/api/admin/flow/evidently", headers=KEY).json()
    assert body["run_id"] == "eval-20260102-000000-bbbbbb" and body["available"] is True
    assert body["by_mode"] == {"rag": {"correct": 28, "false_refusal": 2}, "rag_peft": {"correct": 24, "wrong_answer": 3}}
    assert body["by_category"] == {"calendar": {"correct": 29}}
    assert body["tests_passed"] == 1 and body["tests"][0]["status"] == "SUCCESS" and body["html_available"] is True
    report = env.client.get("/api/admin/flow/evidently/report", headers=KEY)
    assert report.status_code == 200 and report.headers["content-type"].startswith("text/html") and "report" in report.text


def test_without_any_report_the_summary_says_so_and_the_html_is_404(make_env: Callable[..., Env], tmp_path: Path) -> None:
    env = make_env(eval_dir=tmp_path / "none")
    assert env.client.get("/api/admin/flow/evidently", headers=KEY).json() == {"available": False}
    assert env.client.get("/api/admin/flow/evidently/report", headers=KEY).status_code == 404

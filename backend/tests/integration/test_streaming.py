"""POST /api/chat/stream (Server-Sent Events): start -> delta* -> final, with proper HTTP errors before the first token."""

from __future__ import annotations

import json
from collections.abc import Callable

from app.llm.base import LLMError
from tests.fakes import FakeChatClient, FakeRetriever
from tests.integration.conftest import Env


def sse(env: Env, message: str, mode: str = "rag", token: str | None = None, conversation_id: str | None = None):  # type: ignore[no-untyped-def]
    body: dict[str, object] = {"message": message, "model_mode": mode}
    if conversation_id:
        body["conversation_id"] = conversation_id
    headers = {"X-Applicant-Session": token} if token else {}
    return env.client.post("/api/chat/stream", json=body, headers=headers)


def events(response) -> list[tuple[str, dict]]:  # type: ignore[no-untyped-def]
    """Parse an SSE body into [(event name, data dict)]."""
    out = []
    for block in response.text.split("\n\n"):
        if not block.strip():
            continue
        lines = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_model_2_streams_text_then_a_final_event_with_citations(env: Env) -> None:
    r = sse(env, "When do classes begin?")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    evs = events(r)
    names = [n for n, _ in evs]
    assert names[0] == "start" and names[-1] == "final" and names.count("delta") >= 3 and names.count("final") == 1
    assert evs[0][1]["handled_by"]["label"] == "Model 2 - LLM + RAG"
    streamed = "".join(d["text"] for n, d in evs if n == "delta")
    final = evs[-1][1]["response"]
    assert streamed == final["answer"] == "Classes begin on 1 July [1]."
    assert final["grounded"] is True and final["citations"][0]["source_name"] == "SYNTHETIC_academic_calendar.md"
    assert final["usage"]["llm_called"] is True and final["usage"]["first_token_ms"] == 2
    assert final["workflow_path"] == ["classify_intent", "check_model_available", "retrieve_context", "rag_answer"]


def test_model_1_announces_its_notice_before_the_text(env: Env) -> None:
    evs = events(sse(env, "When do classes begin?", mode="direct"))
    assert evs[0][0] == "start" and evs[0][1]["notice"] and evs[0][1]["handled_by"]["label"] == "Model 1 - Direct LLM"
    final = evs[-1][1]["response"]
    assert final["notice"] and final["grounded"] is False and env.retriever.calls == []


def test_a_streamed_turn_equals_the_one_shot_turn(make_env: Callable[..., Env]) -> None:
    streamed_env, plain_env = make_env(), make_env()
    streamed = events(sse(streamed_env, "When do classes begin?"))[-1][1]["response"]
    plain = plain_env.chat("When do classes begin?").json()
    for key in ("answer", "intent", "grounded", "notice", "citations", "workflow_path", "handled_by"):
        assert streamed[key] == plain[key], key
    assert streamed_env.primary.calls == plain_env.primary.calls  # the model got exactly the same prompt


def test_template_answers_have_no_deltas_just_the_final_event(env: Env) -> None:
    evs = events(sse(env, "When is my interview?", token=env.token_for("CUAPP-DEMO-0001")))
    assert [n for n, _ in evs] == ["final"]
    assert "demo-ds-0001" in evs[0][1]["response"]["answer"] and env.primary.calls == []


def test_errors_before_the_first_token_are_normal_http_errors(make_env: Callable[..., Env]) -> None:
    unconfigured = make_env()
    r = sse(unconfigured, "When do classes begin?", mode="rag_peft")  # Model 3 is not configured
    assert r.status_code == 503 and r.headers["content-type"].startswith("application/json")
    assert r.json() == {"error": {"code": "model3_not_configured", "message": r.json()["error"]["message"]}}
    assert unconfigured.primary.calls == [] and unconfigured.retriever.calls == []

    failing = make_env(primary=FakeChatClient(error=LLMError("provider_rate_limited", "slow down", retryable=True, http_status=429)))
    r = sse(failing, "When do classes begin?")
    assert r.status_code == 429 and r.json()["error"]["code"] == "provider_rate_limited"


def test_a_failure_after_text_has_started_ends_with_an_error_event(make_env: Callable[..., Env]) -> None:
    env = make_env(primary=FakeChatClient(reply="one two three four five six", stream_error_after=3))
    r = sse(env, "When do classes begin?")
    evs = events(r)
    assert r.status_code == 200  # the status line was already sent with the first bytes
    assert [n for n, _ in evs][-1] == "error" and "final" not in [n for n, _ in evs]
    assert evs[-1][1]["code"] == "provider_unreachable"
    assert "".join(d["text"] for n, d in evs if n == "delta") == "one two three"
    line = json.loads((env.settings.trace_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert line["error_code"] == "provider_unreachable" and line["streamed"] is True  # still traced, once


def test_the_stream_writes_one_trace_line_with_first_token_time_and_no_text(env: Env) -> None:
    sse(env, "When do classes begin?")
    lines = (env.settings.trace_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    line = json.loads(lines[0])
    assert line["streamed"] is True and line["ttft_ms"] == 2 and line["llm_called"] is True
    assert "classes begin" not in lines[0].lower()


def test_streaming_keeps_the_conversation(env: Env) -> None:
    first = events(sse(env, "When do classes begin?", mode="direct"))[-1][1]["response"]
    sse(env, "And when do they end?", mode="direct", conversation_id=first["conversation_id"])
    assert any(m["content"] == "When do classes begin?" for m in env.primary.calls[1])


def test_validation_errors_match_the_one_shot_endpoint(env: Env) -> None:
    assert sse(env, "").status_code == 422
    assert sse(env, "x" * 2001).status_code == 422


def test_no_documents_indexed_streams_just_the_final_honest_answer(make_env: Callable[..., Env]) -> None:
    env = make_env(retriever=FakeRetriever(ready=False))
    evs = events(sse(env, "When do classes begin?"))
    assert [n for n, _ in evs] == ["final"] and "no university documents have been indexed" in evs[0][1]["response"]["answer"].lower()

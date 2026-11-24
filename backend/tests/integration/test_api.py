"""Required test 12: API health and schema behaviour, admin protection, tracing."""

import json

from tests.integration.conftest import Env


def test_health_reports_model_configuration(env: Env) -> None:
    body = env.client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["models"]["direct"]["configured"] is True
    assert body["models"]["direct"]["retrieval"] is False
    assert body["models"]["rag_peft"]["configured"] is False


def test_chat_validates_input(env: Env) -> None:
    assert env.client.post("/api/chat", json={"message": "", "model_mode": "rag"}).status_code == 422
    assert env.client.post("/api/chat", json={"message": "hi", "model_mode": "gpt"}).status_code == 422


def test_chat_response_schema(env: Env) -> None:
    body = env.chat("When do classes begin?").json()
    for key in ("conversation_id", "message_id", "answer", "intent", "handled_by", "citations", "usage",
                "workflow_path"):
        assert key in body


def test_admin_routes_require_key(env: Env) -> None:
    assert env.client.get("/api/admin/drive/status").status_code == 401
    ok = env.client.get("/api/admin/drive/status", headers={"X-Admin-Key": "test-admin-key"})
    assert ok.status_code == 200 and ok.json()["files"] == []


def test_admin_disabled_without_key(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(admin_api_key=None)
    assert env.client.get("/api/admin/drive/status", headers={"X-Admin-Key": "x"}).status_code == 403


def test_trace_written_without_pii(env: Env) -> None:
    env.chat("I have not received my interview email", token=env.token_for("CUAPP-DEMO-0001"))
    env.chat("When do classes begin?", mode="rag")
    lines = (env.settings.trace_dir / "requests.jsonl").read_text().splitlines()
    assert len(lines) == 2
    text = "\n".join(lines)
    assert "aarav.demo@example.com" not in text and "meet.example.com" not in text
    rag = json.loads(lines[1])
    assert rag["model"] == "fake-model" and rag["prompt_version"] == "rag-v2"
    assert rag["retrieved_chunk_ids"] and rag["node_path"][-1] == "rag_answer"

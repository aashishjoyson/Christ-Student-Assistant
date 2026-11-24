"""Monitoring through the real app: traces written by real chat turns feed the admin summary, thumbs and alerts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.domain.clock import utcnow
from app.services.monitoring_service import build_report, read_traces

KEY = {"X-Admin-Key": "test-admin-key"}
SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "monitor_traces.py"


def test_the_admin_summary_requires_the_admin_key(env) -> None:  # type: ignore[no-untyped-def]
    assert env.client.get("/api/admin/monitoring/summary").status_code in (401, 403)
    assert env.client.get("/api/admin/monitoring/summary", headers=KEY).status_code == 200


def test_real_chat_turns_appear_in_the_summary_with_distances_and_thumbs(env) -> None:  # type: ignore[no-untyped-def]
    answers = [env.chat("When do classes begin?").json() for _ in range(3)]
    env.chat("hello")  # a greeting: answered from a template, never retrieved
    env.client.post("/api/feedback", json={"message_id": answers[0]["message_id"], "rating": "down", "reason": "wrong_answer", "model_mode": "rag"})
    body = env.client.get("/api/admin/monitoring/summary?hours=1", headers=KEY).json()
    cur = body["current"]
    assert cur["requests"] == 4 and cur["errors"] == 0 and cur["document_questions"] == 3
    assert cur["intent_mix"] == {"academic_qa": 3, "general_help": 1}
    assert cur["best_distance"]["n"] == 3 and cur["best_distance"]["mean"] == 0.2  # the fake retriever's nearest passage
    assert cur["feedback"] == {"votes": 1, "down": 1, "thumbs_down_rate": 1.0, "down_reasons": {"wrong_answer": 1}}
    assert cur["llm_answers"] == 3 and cur["template_answers"] == 1 and cur["latency_ms"]["p50"] is not None
    assert body["status"] == "ok" and [a["code"] for a in body["alerts"]] == ["small_sample"]  # 4 requests are too few to alert on
    text = json.dumps(body).lower()
    assert "classes begin" not in text and "hello" not in text  # nothing the visitor typed, nor anything the system answered


def test_a_provider_outage_shows_up_as_errors_and_a_critical_alert(make_env) -> None:  # type: ignore[no-untyped-def]
    from app.llm.base import LLMError
    from tests.fakes import FakeChatClient

    env = make_env(primary=FakeChatClient(error=LLMError("provider_unreachable", "down", retryable=True)))
    for _ in range(25):
        env.chat("When do classes begin?")
    body = env.client.get("/api/admin/monitoring/summary?hours=1", headers=KEY).json()
    assert body["current"]["errors"] == 25 and body["current"]["error_codes"] == {"provider_unreachable": 25}
    assert body["status"] == "critical" and "error_rate" in {a["code"] for a in body["alerts"]}


def test_a_missing_trace_log_is_an_empty_window_not_an_error(env) -> None:  # type: ignore[no-untyped-def]
    report = build_report(env.settings, env.container.session_factory, utcnow(), traces=[])
    assert report["current"]["requests"] == 0 and report["status"] == "ok" and report["alerts"][0]["code"] == "no_traffic"
    assert read_traces(env.settings.trace_dir / "does-not-exist.jsonl") == []


def test_unreadable_trace_lines_are_skipped(tmp_path: Path) -> None:
    log = tmp_path / "requests.jsonl"
    log.write_text('{"ts": "2026-11-24T12:00:00+00:00", "message_id": "a"}\nnot json\n[1, 2]\n\n{"message_id": "b"}\n', encoding="utf-8")
    assert [t["message_id"] for t in read_traces(log)] == ["a", "b"]


def test_automatic_ingestion_makes_a_stale_index_an_alert(make_env) -> None:  # type: ignore[no-untyped-def]
    from datetime import timedelta

    from app.db.models import SyncRun

    env = make_env(drive_poll_enabled=True)
    old = utcnow() - timedelta(hours=30)
    with env.container.session_factory() as session:
        session.add(SyncRun(source="drive", trigger="poll", started_at=old, finished_at=old, status="succeeded"))
        session.commit()
    body = env.client.get("/api/admin/monitoring/summary", headers=KEY).json()
    assert "stale_index" in {a["code"] for a in body["alerts"]} and body["index"]["automatic_ingestion"] is True
    assert body["index"]["age_seconds"] > 29 * 3600


def test_the_command_line_monitor_reads_a_trace_log_and_exits_by_severity(tmp_path: Path) -> None:
    now = utcnow().isoformat()
    healthy = tmp_path / "ok.jsonl"
    healthy.write_text("\n".join(json.dumps({"ts": now, "message_id": f"m{i}", "intent": "academic_qa", "model_mode_requested": "rag", "llm_called": True,
                                               "total_latency_ms": 1500, "est_cost_usd": 0.0001, "retrieval": {"ready": True, "kept": 8, "best_distance": 0.3}})
                                  for i in range(30)) + "\n", encoding="utf-8")
    broken = tmp_path / "broken.jsonl"
    broken.write_text("\n".join(json.dumps({"ts": now, "message_id": f"m{i}", "intent": "academic_qa", "model_mode_requested": "rag", "error_code": "llm_timeout"})
                                for i in range(30)) + "\n", encoding="utf-8")
    run = lambda path, *extra: subprocess.run([sys.executable, str(SCRIPT), "--traces", str(path), *extra],  # noqa: E731, S603
                                              capture_output=True, text=True, check=False)
    ok = run(healthy)
    assert ok.returncode == 0 and "requests" in ok.stdout and "no alerts" in ok.stdout
    assert json.loads(run(healthy, "--json").stdout)["current"]["requests"] == 30
    bad = run(broken)
    assert bad.returncode == 1 and "CRITICAL" in bad.stdout and "error_rate" in bad.stdout
    assert run(tmp_path / "missing.jsonl").returncode == 2

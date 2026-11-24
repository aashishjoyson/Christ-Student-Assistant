"""Operating the system: the chat rate limit, retention of operational data, and the experiments summary the admin page shows."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select, update

from app.db.models import Feedback
from app.domain.clock import utcnow
from app.schemas.chat import ChatRequest
from app.services.experiments import experiments_summary, list_runs, read_baseline
from app.services.retention import prune_traces, purge_feedback

KEY = {"X-Admin-Key": "test-admin-key"}
REPO = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------- rate limit
def test_a_client_that_sends_too_fast_is_told_to_wait(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(chat_rate_limit_per_minute=5)
    codes = [env.chat(f"What is the library fine number {i}?").status_code for i in range(7)]
    assert codes == [200] * 5 + [429, 429]
    blocked = env.chat("one more").json()
    assert blocked == {"error": {"code": "rate_limited", "message": "You are sending messages very quickly. Please wait a moment and try again."}}


def test_the_streaming_route_has_the_same_limit(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(chat_rate_limit_per_minute=2)
    body = {"message": "hello", "model_mode": "rag"}
    codes = [env.client.post("/api/chat/stream", json=body).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_the_limit_does_not_apply_to_health_or_feedback(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env(chat_rate_limit_per_minute=1)
    env.chat("one")
    assert env.chat("two").status_code == 429
    assert env.client.get("/api/health").status_code == 200
    assert env.client.post("/api/feedback", json={"message_id": "m1", "rating": "up"}).status_code == 200


# ---------------------------------------------------------------- retention
def trace_line(ts, name: str) -> str:  # type: ignore[no-untyped-def]
    return json.dumps({"ts": ts.isoformat(), "message_id": name})


def test_old_trace_lines_are_removed_and_recent_or_unreadable_ones_are_kept(tmp_path: Path) -> None:
    now = utcnow()
    log = tmp_path / "requests.jsonl"
    log.write_text("\n".join([trace_line(now - timedelta(days=120), "old"), trace_line(now - timedelta(days=5), "recent"), "not json at all",
                              json.dumps({"message_id": "no timestamp"})]) + "\n", encoding="utf-8")
    assert prune_traces(log, now - timedelta(days=90), dry_run=True) == (3, 1)
    assert "old" in log.read_text(encoding="utf-8")  # a dry run changes nothing
    assert prune_traces(log, now - timedelta(days=90)) == (3, 1)
    text = log.read_text(encoding="utf-8")
    assert '"old"' not in text and '"recent"' in text and "not json at all" in text and "no timestamp" in text


def test_pruning_a_missing_or_clean_log_is_harmless(tmp_path: Path) -> None:
    assert prune_traces(tmp_path / "none.jsonl", utcnow()) == (0, 0)
    clean = tmp_path / "clean.jsonl"
    clean.write_text(trace_line(utcnow(), "fresh") + "\n", encoding="utf-8")
    before = clean.read_bytes()
    assert prune_traces(clean, utcnow() - timedelta(days=1)) == (1, 0) and clean.read_bytes() == before


def test_old_ratings_are_purged_and_a_dry_run_only_counts(env) -> None:  # type: ignore[no-untyped-def]
    for name in ("old", "new"):
        env.client.post("/api/feedback", json={"message_id": name, "rating": "up"})
    with env.container.session_factory() as session:
        session.execute(update(Feedback).where(Feedback.message_id == "old").values(updated_at=utcnow() - timedelta(days=400)))
        session.commit()
        cutoff = utcnow() - timedelta(days=365)
        assert purge_feedback(session, cutoff, dry_run=True) == 1
        assert session.execute(select(Feedback)).scalars().all().__len__() == 2
        assert purge_feedback(session, cutoff) == 1
        assert [f.message_id for f in session.execute(select(Feedback)).scalars()] == ["new"]


def test_the_retention_command_runs_a_dry_run_without_changing_anything(tmp_path: Path) -> None:
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "retention.py"), "--dry-run"], capture_output=True, text=True, check=False)  # noqa: S603
    assert done.returncode == 0 and "traces older than 90 days: would remove" in done.stdout and "ratings older than 365 days: would remove" in done.stdout


# ---------------------------------------------------------------- experiments summary
def make_run(root: Path, run_id: str, accuracy: float) -> None:
    folder = root / run_id
    folder.mkdir(parents=True)
    (folder / "config.json").write_text(json.dumps({"run_id": run_id, "created_at": "2026-11-24T10:00:00+00:00", "git": {"commit": "abc", "dirty": False},
                                                    "golden_set": {"sha256": "g" * 64, "cases": 38}, "retrieval": {"top_k": 8},
                                                    "prompt_versions": {"rag": "rag-v2"}}), encoding="utf-8")
    (folder / "summary.json").write_text(json.dumps({"modes": {"rag": {"n": 38, "answer_accuracy": accuracy, "secret_extra": "dropped", "errors": 0}}}), encoding="utf-8")


def test_runs_are_listed_newest_first_with_only_the_headline_metrics(tmp_path: Path) -> None:
    make_run(tmp_path, "eval-20261124-100000-aaaaaa", 0.7)
    make_run(tmp_path, "eval-20261124-120000-bbbbbb", 0.9)
    (tmp_path / "eval-broken").mkdir()  # a run folder without its files is skipped, not an error
    runs = list_runs(tmp_path)
    assert [r["run_id"] for r in runs] == ["eval-20261124-120000-bbbbbb", "eval-20261124-100000-aaaaaa"]
    assert runs[0]["modes"]["rag"]["answer_accuracy"] == 0.9 and "secret_extra" not in runs[0]["modes"]["rag"]
    assert len(list_runs(tmp_path, limit=1)) == 1 and list_runs(tmp_path / "nowhere") == []


def test_the_committed_baseline_is_readable_and_the_admin_endpoint_serves_the_summary(make_env, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    baseline = read_baseline(REPO / "data" / "eval" / "baselines" / "academic_real_baseline.json")
    assert baseline is not None and baseline["modes"]["rag"]["answer_accuracy"] is not None and "Initial baseline" in baseline["reason"]
    make_run(tmp_path / "runs", "eval-20261124-120000-bbbbbb", 0.9)
    env = make_env(eval_dir=tmp_path / "runs", baseline_file=REPO / "data" / "eval" / "baselines" / "academic_real_baseline.json")
    assert env.client.get("/api/admin/experiments/summary").status_code in (401, 403)
    body = env.client.get("/api/admin/experiments/summary", headers=KEY).json()
    assert body["baseline"]["run_id"] == baseline["run_id"] and [r["run_id"] for r in body["runs"]] == ["eval-20261124-120000-bbbbbb"]
    assert experiments_summary(tmp_path / "none", tmp_path / "none.json") == {"baseline": None, "runs": []}


def test_a_chat_request_object_is_unchanged_by_the_limit() -> None:
    assert ChatRequest(message="hi").model_mode == "rag"

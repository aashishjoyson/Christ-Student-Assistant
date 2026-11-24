"""Builds the monitoring report from the trace log, the feedback table and the document sync history. Used by the admin endpoint and
scripts/monitor_traces.py, so the dashboard and the command line can never disagree."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import SyncRun
from app.db.repositories.feedback import feedback_rows
from app.eval.monitoring import Thresholds, evaluate_alerts, in_window, summarize, worst_level

MAX_TRACE_LINES = 200_000  # the newest lines are kept; a prototype log never gets near this


def read_traces(path: Path, max_lines: int = MAX_TRACE_LINES) -> list[dict[str, Any]]:
    """Read the JSONL trace log, skipping lines that are not valid JSON objects. A missing file is an empty log."""
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                out.append(record)
    return out[-max_lines:]


def last_successful_sync(session: Session) -> datetime | None:
    run = session.execute(select(SyncRun).where(SyncRun.status == "succeeded", SyncRun.finished_at.is_not(None))
                          .order_by(SyncRun.finished_at.desc()).limit(1)).scalar_one_or_none()
    return run.finished_at if run else None


def build_report(settings: Settings, session_factory: sessionmaker[Session], now: datetime, hours: float = 24, reference_hours: float = 168,
                 thresholds: Thresholds | None = None, traces: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    thresholds = thresholds or Thresholds()
    if traces is None:
        traces = read_traces(settings.trace_dir / "requests.jsonl")
    cut = now - timedelta(hours=hours)
    ref_from = cut - timedelta(hours=reference_hours)
    with session_factory() as session:
        votes_now, votes_ref = feedback_rows(session, cut, now), feedback_rows(session, ref_from, cut)
        synced_at = last_successful_sync(session)
    current = summarize(in_window(traces, cut, now), votes_now)
    reference = summarize(in_window(traces, ref_from, cut), votes_ref)
    age = (now - synced_at) if synced_at else None
    # An index that nobody refreshes is only a problem when automatic ingestion is meant to be running.
    alerts = evaluate_alerts(current, reference, thresholds, index_age=age if settings.drive_poll_enabled else None,
                             index_known=synced_at is not None or not settings.drive_poll_enabled)
    return {
        "generated_at": now.isoformat(), "window_hours": hours, "reference_hours": reference_hours,
        "status": worst_level(alerts), "alerts": [asdict(a) for a in alerts],
        "current": current, "reference": reference,
        "index": {"last_successful_sync": synced_at.isoformat() if synced_at else None,
                  "age_seconds": int(age.total_seconds()) if age else None, "automatic_ingestion": settings.drive_poll_enabled},
        "traces_in_log": len(traces),
    }

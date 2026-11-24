"""Retention: how long operational data is kept. Nothing here touches documents, the applicant database or evaluation runs.

- request traces (no message text, but still a record of use): pruned by age
- thumbs up/down: pruned by age
- stored conversations (opt-in memory): pruned by age by HistoryStore.purge
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import Feedback
from app.eval.monitoring import parse_ts


def prune_traces(path: Path, cutoff: datetime, dry_run: bool = False) -> tuple[int, int]:
    """Remove trace lines older than `cutoff`. Returns (kept, dropped). Lines without a readable timestamp are kept, never guessed at.
    The file is rewritten through a temporary file; lines appended while it was being read are carried over. Run it while the API is quiet."""
    if not path.is_file():
        return 0, 0
    size = path.stat().st_size
    raw = path.read_bytes()[:size]
    kept: list[bytes] = []
    dropped = 0
    for line in raw.splitlines(keepends=True):
        try:
            ts = parse_ts(str(json.loads(line).get("ts", "")))
        except (ValueError, AttributeError):
            ts = None
        if ts is not None and ts < cutoff:
            dropped += 1
        else:
            kept.append(line if line.endswith(b"\n") else line + b"\n")
    if dry_run or dropped == 0:
        return len(kept), dropped
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("wb") as handle:
        handle.writelines(kept)
        if path.stat().st_size > size:  # the API wrote while we were working: keep those lines
            handle.write(path.read_bytes()[size:])
    os.replace(tmp, path)
    return len(kept), dropped


def purge_feedback(session: Session, cutoff: datetime, dry_run: bool = False) -> int:
    from sqlalchemy import func, select

    if dry_run:
        return int(session.execute(select(func.count()).select_from(Feedback).where(Feedback.updated_at < cutoff)).scalar_one())
    deleted = session.execute(delete(Feedback).where(Feedback.updated_at < cutoff)).rowcount
    session.commit()
    return int(deleted or 0)

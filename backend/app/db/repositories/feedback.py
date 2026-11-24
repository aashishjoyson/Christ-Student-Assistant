"""Thumbs up/down on answers. One rating per answer; rating again changes it. Nothing here touches applicant data."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Feedback


def upsert_feedback(session: Session, message_id: str, rating: str, reason: str | None, model_mode: str | None, now: datetime) -> bool:
    """Store or change the rating for an answer. Returns True when it was new."""
    row = session.execute(select(Feedback).where(Feedback.message_id == message_id)).scalar_one_or_none()
    created = row is None
    if row is None:
        row = Feedback(message_id=message_id, created_at=now)
        session.add(row)
    row.rating, row.reason, row.model_mode, row.updated_at = rating, reason if rating == "down" else None, model_mode, now
    session.commit()
    return created


def feedback_rows(session: Session, since: datetime | None = None, until: datetime | None = None) -> list[dict[str, str | None]]:
    query = select(Feedback)
    if since is not None:
        query = query.where(Feedback.updated_at >= since)
    if until is not None:
        query = query.where(Feedback.updated_at < until)
    return [{"message_id": f.message_id, "rating": f.rating, "reason": f.reason, "model_mode": f.model_mode}
            for f in session.execute(query).scalars()]


def feedback_summary(rows: list[dict[str, str | None]]) -> dict[str, object]:
    ratings = Counter(r["rating"] for r in rows)
    return {"votes": len(rows), "up": ratings["up"], "down": ratings["down"],
            "down_reasons": dict(Counter(r["reason"] or "none" for r in rows if r["rating"] == "down")),
            "by_mode": dict(Counter(f"{r['model_mode'] or 'unknown'}:{r['rating']}" for r in rows))}

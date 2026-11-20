"""Reserve-then-send audit trail for interview email resends."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import NotificationEvent


def reserve_notification(
    session: Session,
    *,
    applicant_id: int,
    interview_id: int,
    recipient_email: str,
    idempotency_key: str,
    request_id: str,
    provider: str,
    now: datetime,
) -> int | None:
    """Insert a 'pending' event. Returns its id, or None if the UNIQUE key says a send is already in this window."""
    event = NotificationEvent(
        applicant_id=applicant_id,
        interview_id=interview_id,
        recipient_email=recipient_email,
        status="pending",
        provider=provider,
        idempotency_key=idempotency_key,
        request_id=request_id,
        created_at=now,
    )
    session.add(event)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return None
    return event.id


def complete_notification(
    session: Session,
    event_id: int,
    *,
    status: str,
    provider_message_id: str | None,
    error_message: str | None,
    now: datetime,
) -> None:
    event = session.get(NotificationEvent, event_id)
    if event is None:
        raise LookupError(f"notification event {event_id} not found")
    event.status = status
    event.provider_message_id = provider_message_id
    event.error_message = error_message
    event.completed_at = now
    if status == "failed":
        # Free the cooldown window so the student can retry after a provider failure.
        event.idempotency_key = f"{event.idempotency_key}:failed:{event.id}"
    session.commit()

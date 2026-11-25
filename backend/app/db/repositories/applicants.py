"""Applicant lookups. Every function is scoped by the verified applicant_id.

There is deliberately no lookup by name and no "search applicants" function.
Return types are small read-only views containing only the fields an answer needs.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Applicant, Application, Interview, NotificationEvent
from app.domain.masking import mask_email, normalize_application_id, normalize_email
from app.domain.notification_policy import ACTIVE_INTERVIEW_STATUSES, EventSnapshot


@dataclass(frozen=True)
class VerifiedApplicant:
    applicant_id: int
    application_id: str
    first_name: str
    masked_email: str
    programme: str


@dataclass(frozen=True)
class ApplicationStatusView:
    application_id: str
    programme: str
    status: str
    status_updated_at: datetime


@dataclass(frozen=True)
class InterviewView:
    interview_id: int
    scheduled_at: datetime
    mode: str
    location_or_meeting_link: str
    interviewer_label: str
    status: str


@dataclass(frozen=True)
class ApplicantContact:
    """Internal only: used by the email node. Never returned to the UI or the LLM."""

    full_name: str
    registered_email: str
    application_id: str
    programme: str


def verify_applicant(session: Session, application_id: str, registered_email: str) -> VerifiedApplicant | None:
    row = session.execute(
        select(Applicant).where(Applicant.application_id == normalize_application_id(application_id))
    ).scalar_one_or_none()
    supplied = normalize_email(registered_email)
    stored = normalize_email(row.registered_email) if row else "no-match@invalid.invalid"
    matches = hmac.compare_digest(supplied.encode(), stored.encode())  # constant-time comparison
    if row is None or not matches:
        return None
    return VerifiedApplicant(
        applicant_id=row.id,
        application_id=row.application_id,
        first_name=row.full_name.split()[0],
        masked_email=mask_email(row.registered_email),
        programme=row.programme,
    )


@dataclass(frozen=True)
class SyntheticApplicantView:
    """Demo helper only. The registered address is returned so the route can decide what may be shown (it never leaves the route unmasked
    unless it is a synthetic example.com address)."""

    application_id: str
    first_name: str
    application_status: str
    interview_status: str | None
    interview_mode: str | None
    registered_email: str


def list_synthetic_applicants(session: Session) -> list[SyntheticApplicantView]:
    """The SYNTHETIC records only (is_synthetic = true), so the chat can offer them as ready-made demo logins. A real record is never listed."""
    out: list[SyntheticApplicantView] = []
    for applicant in session.execute(select(Applicant).where(Applicant.is_synthetic.is_(True)).order_by(Applicant.application_id)).scalars():
        application = session.execute(select(Application).where(Application.applicant_id == applicant.id)).scalars().first()
        interview = session.execute(select(Interview).where(Interview.applicant_id == applicant.id).order_by(Interview.id.desc())).scalars().first()
        out.append(SyntheticApplicantView(
            application_id=applicant.application_id,
            first_name=applicant.full_name.split()[0],
            application_status=application.status if application else "unknown",
            interview_status=interview.status if interview else None,
            interview_mode=interview.mode if interview else None,
            registered_email=applicant.registered_email,
        ))
    return out


def applicant_exists(session: Session, applicant_id: int) -> bool:
    return session.get(Applicant, applicant_id) is not None


def get_application_status(session: Session, applicant_id: int) -> ApplicationStatusView | None:
    row = session.execute(
        select(Application, Applicant)
        .join(Applicant, Application.applicant_id == Applicant.id)
        .where(Application.applicant_id == applicant_id)
    ).first()
    if row is None:
        return None
    application, applicant = row
    return ApplicationStatusView(
        application_id=applicant.application_id,
        programme=applicant.programme,
        status=application.status,
        status_updated_at=application.status_updated_at,
    )


def _to_view(row: Interview) -> InterviewView:
    return InterviewView(
        interview_id=row.id,
        scheduled_at=row.scheduled_at,
        mode=row.mode,
        location_or_meeting_link=row.location_or_meeting_link,
        interviewer_label=row.interviewer_label,
        status=row.status,
    )


def get_interview_details(session: Session, applicant_id: int, now: datetime) -> InterviewView | None:
    """Next upcoming active interview; otherwise the most recent interview of any status."""
    upcoming = session.execute(
        select(Interview)
        .where(
            Interview.applicant_id == applicant_id,
            Interview.status.in_(sorted(ACTIVE_INTERVIEW_STATUSES)),
            Interview.scheduled_at > now,
        )
        .order_by(Interview.scheduled_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    if upcoming is not None:
        return _to_view(upcoming)
    latest = session.execute(
        select(Interview).where(Interview.applicant_id == applicant_id).order_by(Interview.scheduled_at.desc()).limit(1)
    ).scalar_one_or_none()
    return _to_view(latest) if latest else None


def get_interview_for_applicant(session: Session, interview_id: int, applicant_id: int) -> InterviewView | None:
    """Scoped by BOTH ids so one applicant can never read another applicant's interview."""
    row = session.execute(
        select(Interview).where(Interview.id == interview_id, Interview.applicant_id == applicant_id)
    ).scalar_one_or_none()
    return _to_view(row) if row else None


def get_applicant_contact(session: Session, applicant_id: int) -> ApplicantContact | None:
    row = session.get(Applicant, applicant_id)
    if row is None:
        return None
    return ApplicantContact(row.full_name, row.registered_email, row.application_id, row.programme)


def get_notification_history(
    session: Session, applicant_id: int, interview_id: int, since: datetime
) -> list[EventSnapshot]:
    rows = session.execute(
        select(NotificationEvent.status, NotificationEvent.created_at).where(
            NotificationEvent.applicant_id == applicant_id,
            NotificationEvent.interview_id == interview_id,
            NotificationEvent.created_at >= since,
        )
    ).all()
    return [EventSnapshot(status=s, created_at=c) for s, c in rows]

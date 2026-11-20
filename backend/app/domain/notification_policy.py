"""Eligibility rules for resending an interview email.

Two layers protect against duplicate emails:
1. decide_resend(): readable business rules (cooldown, daily cap, valid interview).
2. make_window_key(): an idempotency key stored under a UNIQUE constraint, so even
   two concurrent requests cannot both reserve a send in the same cooldown window.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

ACTIVE_INTERVIEW_STATUSES = frozenset({"scheduled", "rescheduled"})
BLOCKING_EVENT_STATUSES = frozenset({"pending", "sent", "simulated"})
DELIVERED_EVENT_STATUSES = frozenset({"sent", "simulated"})

_EMAIL_OK = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class Ineligible(StrEnum):
    NO_INTERVIEW = "no_interview"
    INTERVIEW_NOT_ACTIVE = "interview_not_active"
    INTERVIEW_IN_PAST = "interview_in_past"
    INVALID_RECIPIENT = "invalid_recipient"
    COOLDOWN_ACTIVE = "cooldown_active"
    DAILY_LIMIT = "daily_limit"
    DUPLICATE_IN_PROGRESS = "duplicate_in_progress"
    RECIPIENT_NOT_ALLOWLISTED = "recipient_not_allowlisted"


@dataclass(frozen=True)
class InterviewSnapshot:
    interview_id: int
    status: str
    scheduled_at: datetime


@dataclass(frozen=True)
class EventSnapshot:
    status: str
    created_at: datetime


@dataclass(frozen=True)
class PolicyConfig:
    cooldown: timedelta = timedelta(minutes=15)
    max_per_day: int = 3


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: Ineligible | None = None
    retry_after: datetime | None = None


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_OK.match(email.strip()))


def decide_resend(
    interview: InterviewSnapshot | None,
    recent_events: Iterable[EventSnapshot],
    recipient_email: str,
    now: datetime,
    config: PolicyConfig,
) -> EligibilityDecision:
    if interview is None:
        return EligibilityDecision(False, Ineligible.NO_INTERVIEW)
    if interview.status not in ACTIVE_INTERVIEW_STATUSES:
        return EligibilityDecision(False, Ineligible.INTERVIEW_NOT_ACTIVE)
    if interview.scheduled_at <= now:
        return EligibilityDecision(False, Ineligible.INTERVIEW_IN_PAST)
    if not is_valid_email(recipient_email):
        return EligibilityDecision(False, Ineligible.INVALID_RECIPIENT)

    events = list(recent_events)
    blocking = [e for e in events if e.status in BLOCKING_EVENT_STATUSES and now - e.created_at < config.cooldown]
    if blocking:
        latest = max(e.created_at for e in blocking)
        return EligibilityDecision(False, Ineligible.COOLDOWN_ACTIVE, retry_after=latest + config.cooldown)

    delivered_today = [
        e for e in events if e.status in DELIVERED_EVENT_STATUSES and now - e.created_at < timedelta(days=1)
    ]
    if len(delivered_today) >= config.max_per_day:
        oldest = min(e.created_at for e in delivered_today)
        return EligibilityDecision(False, Ineligible.DAILY_LIMIT, retry_after=oldest + timedelta(days=1))

    return EligibilityDecision(True)


def make_window_key(interview_id: int, now: datetime, cooldown: timedelta) -> str:
    """Same key for every request in the same cooldown window -> UNIQUE constraint blocks duplicates."""
    window = int(now.timestamp() // max(1, int(cooldown.total_seconds())))
    raw = f"interview-resend:{interview_id}:{window}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def recipient_allowed(recipient: str, allowlist: Iterable[str]) -> bool:
    """Allowlist entries are full addresses or '@domain'. Empty allowlist = nothing allowed."""
    recipient = recipient.strip().lower()
    for entry in allowlist:
        entry = entry.strip().lower()
        if not entry:
            continue
        if entry.startswith("@") and recipient.endswith(entry):
            return True
        if recipient == entry:
            return True
    return False

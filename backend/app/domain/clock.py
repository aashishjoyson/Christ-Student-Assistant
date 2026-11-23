"""Timezone helpers. Store UTC everywhere; convert only for display."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(UTC)


def ensure_aware_utc(value: datetime) -> datetime:
    """Reject naive datetimes so timezone bugs fail loudly."""
    if value.tzinfo is None:
        raise ValueError("Naive datetime is not allowed; use a timezone-aware value.")
    return value.astimezone(UTC)


def format_local(value: datetime, tz_name: str) -> str:
    """Human-readable local time, e.g. 'Mon 24 Nov 2026, 10:30 AM IST'."""
    local = ensure_aware_utc(value).astimezone(ZoneInfo(tz_name))
    return local.strftime("%a %d %b %Y, %I:%M %p %Z")

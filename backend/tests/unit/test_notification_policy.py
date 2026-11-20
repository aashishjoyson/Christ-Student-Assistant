from datetime import datetime, timedelta, timezone

from app.domain.notification_policy import (
    EventSnapshot,
    Ineligible,
    InterviewSnapshot,
    PolicyConfig,
    decide_resend,
    make_window_key,
    recipient_allowed,
)

NOW = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)
FUTURE = InterviewSnapshot(interview_id=7, status="scheduled", scheduled_at=NOW + timedelta(days=3))
CFG = PolicyConfig(cooldown=timedelta(minutes=15), max_per_day=3)
EMAIL = "demo.applicant@example.com"


def test_eligible_when_no_history() -> None:
    assert decide_resend(FUTURE, [], EMAIL, NOW, CFG).eligible


def test_no_interview() -> None:
    assert decide_resend(None, [], EMAIL, NOW, CFG).reason == Ineligible.NO_INTERVIEW


def test_cancelled_interview_not_eligible() -> None:
    cancelled = InterviewSnapshot(7, "cancelled", NOW + timedelta(days=1))
    assert decide_resend(cancelled, [], EMAIL, NOW, CFG).reason == Ineligible.INTERVIEW_NOT_ACTIVE


def test_past_interview_not_eligible() -> None:
    past = InterviewSnapshot(7, "scheduled", NOW - timedelta(hours=1))
    assert decide_resend(past, [], EMAIL, NOW, CFG).reason == Ineligible.INTERVIEW_IN_PAST


def test_invalid_recipient() -> None:
    assert decide_resend(FUTURE, [], "not-an-email", NOW, CFG).reason == Ineligible.INVALID_RECIPIENT


def test_cooldown_blocks_recent_send_and_reports_retry_time() -> None:
    sent = EventSnapshot("simulated", NOW - timedelta(minutes=5))
    decision = decide_resend(FUTURE, [sent], EMAIL, NOW, CFG)
    assert decision.reason == Ineligible.COOLDOWN_ACTIVE
    assert decision.retry_after == sent.created_at + CFG.cooldown


def test_pending_event_also_blocks() -> None:
    pending = EventSnapshot("pending", NOW - timedelta(minutes=1))
    assert decide_resend(FUTURE, [pending], EMAIL, NOW, CFG).reason == Ineligible.COOLDOWN_ACTIVE


def test_failed_attempt_does_not_block_retry() -> None:
    failed = EventSnapshot("failed", NOW - timedelta(minutes=1))
    assert decide_resend(FUTURE, [failed], EMAIL, NOW, CFG).eligible


def test_daily_limit() -> None:
    events = [EventSnapshot("sent", NOW - timedelta(hours=h)) for h in (1, 2, 3)]
    assert decide_resend(FUTURE, events, EMAIL, NOW, CFG).reason == Ineligible.DAILY_LIMIT


def test_window_key_same_within_window_and_changes_after() -> None:
    a = make_window_key(7, NOW, CFG.cooldown)
    b = make_window_key(7, NOW + timedelta(minutes=1), CFG.cooldown)
    c = make_window_key(7, NOW + timedelta(minutes=16), CFG.cooldown)
    other = make_window_key(8, NOW, CFG.cooldown)
    assert a == b
    assert a != c
    assert a != other


def test_recipient_allowlist() -> None:
    assert recipient_allowed("x@example.com", ["@example.com"])
    assert recipient_allowed("Me@Test.org", ["me@test.org"])
    assert not recipient_allowed("x@gmail.com", ["@example.com"])
    assert not recipient_allowed("x@example.com", [])

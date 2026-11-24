from datetime import UTC, datetime, timedelta

from app.core.rate_limit import SlidingWindowLimiter
from app.domain.masking import mask_email
from app.domain.redaction import redact
from app.domain.tokens import issue_token, verify_token

NOW = datetime(2026, 11, 20, 6, 0, tzinfo=UTC)
SECRET = b"unit-test-secret"


def test_mask_email() -> None:
    assert mask_email("aarav.demo@example.com") == "a********o@example.com"
    assert mask_email("ab@example.com") == "a***@example.com"
    assert mask_email("nonsense") == "***"


def test_token_roundtrip_and_expiry() -> None:
    token, expires = issue_token(42, SECRET, timedelta(minutes=30), NOW)
    assert verify_token(token, SECRET, NOW + timedelta(minutes=29)) == 42
    assert verify_token(token, SECRET, expires) is None


def test_token_tampering_rejected() -> None:
    token, _ = issue_token(42, SECRET, timedelta(minutes=30), NOW)
    body, sig = token.split(".")
    forged_body = body[:-2] + ("AA" if body[-2:] != "AA" else "BB")
    assert verify_token(f"{forged_body}.{sig}", SECRET, NOW) is None
    assert verify_token(token, b"other-secret", NOW) is None
    assert verify_token("garbage", SECRET, NOW) is None
    assert verify_token(None, SECRET, NOW) is None


def test_redact_masks_secrets_and_emails() -> None:
    fake_key = "sk-" + "x" * 24  # built at runtime so the repo secret scanner stays clean
    data = {"api_key": fake_key, "note": f"mail demo.user@example.com key {fake_key}"}
    out = redact(data)
    assert out["api_key"] == "[REDACTED]"
    assert "demo.user@example.com" not in out["note"]
    assert fake_key not in out["note"]


def test_rate_limiter_window() -> None:
    limiter = SlidingWindowLimiter(max_attempts=2, window=timedelta(minutes=15))
    assert limiter.hit("k", NOW)
    assert limiter.hit("k", NOW + timedelta(minutes=1))
    assert not limiter.hit("k", NOW + timedelta(minutes=2))
    assert limiter.hit("k", NOW + timedelta(minutes=16))


# ---- trace redaction: token COUNTS are metrics, token VALUES are secrets ----
def test_numeric_token_counts_survive_redaction() -> None:
    from app.domain.redaction import redact

    out = redact({"input_tokens": 120, "output_tokens": 20, "intent_llm_input_tokens": 90, "intent_llm_output_tokens": 4, "total_tokens": None})
    assert out == {"input_tokens": 120, "output_tokens": 20, "intent_llm_input_tokens": 90, "intent_llm_output_tokens": 4, "total_tokens": None}


def test_secret_looking_keys_are_still_redacted_even_with_numbers_or_odd_values() -> None:
    from app.domain.redaction import redact

    out = redact({
        "session_token": "abc.def", "applicant_token": 12345, "api_key": "sk-test", "password": 1, "Authorization": "Bearer x",
        "input_tokens": "sk" + "-proj-" + "x" * 30,  # a string under a count key is NOT a count (built at runtime: no key-shaped literal)
        "token": 7, "refresh_token_count_secret": 3,
    })
    assert out["session_token"] == out["applicant_token"] == out["api_key"] == out["password"] == out["Authorization"] == "[REDACTED]"
    assert out["token"] == "[REDACTED]" and out["refresh_token_count_secret"] == "[REDACTED]"
    assert "sk-proj" not in str(out["input_tokens"])

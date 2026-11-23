"""Short-lived signed applicant session tokens (HMAC-SHA256, stdlib only).

Issued by POST /api/demo/applicant/verify after application ID + registered
email match. Sent back on chat requests in the X-Applicant-Session header.
The token carries only the internal applicant id and an expiry, never PII.

PROTOTYPE ONLY: production needs institutional SSO / verified identity.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

TOKEN_VERSION = 1


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(applicant_id: int, secret: bytes, ttl: timedelta, now: datetime) -> tuple[str, datetime]:
    expires_at = (now + ttl).astimezone(UTC)
    payload = {"v": TOKEN_VERSION, "aid": applicant_id, "exp": int(expires_at.timestamp())}
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64e(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}", expires_at


def verify_token(token: str | None, secret: bytes, now: datetime) -> int | None:
    """Return applicant id if the token is authentic and unexpired, else None."""
    if not token or token.count(".") != 1:
        return None
    body, sig = token.split(".")
    expected = _b64e(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("v") != TOKEN_VERSION or not isinstance(payload.get("aid"), int):
        return None
    if int(payload.get("exp", 0)) <= int(now.timestamp()):
        return None
    return payload["aid"]

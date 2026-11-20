"""PII masking and identifier hashing for UI, logs and traces."""

from __future__ import annotations

import hashlib
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_email(email: str) -> str:
    """'aarav.demo@example.com' -> 'a********o@example.com'."""
    email = email.strip()
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "***"
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def mask_emails_in_text(text: str) -> str:
    return EMAIL_RE.sub(lambda m: mask_email(m.group(0)), text)


def hash_identifier(value: str, length: int = 12) -> str:
    """Stable, non-reversible short id for correlating traces without storing raw ids."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_application_id(application_id: str) -> str:
    return application_id.strip().upper()

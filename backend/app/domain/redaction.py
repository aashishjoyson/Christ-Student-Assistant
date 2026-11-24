"""Redact secrets and PII before anything is written to traces or logs."""

from __future__ import annotations

import re
from typing import Any

from app.domain.masking import mask_emails_in_text

_SECRET_KEY_NAMES = re.compile(r"(api[_-]?key|secret|password|token|authorization|credential)", re.IGNORECASE)
_SECRET_VALUES = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # OpenAI / OpenRouter style keys
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),  # Google API keys
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


# A token COUNT (input_tokens, output_tokens, ...) is a usage metric, not a credential. Only numeric values under these
# exact key shapes are exempt; session_token, applicant_token, api_key and the like stay redacted whatever their value.
_TOKEN_COUNT_KEY = re.compile(r"(^|_)(input|output|prompt|completion|total)_tokens$", re.IGNORECASE)


def _is_token_count(key: str, value: Any) -> bool:
    numeric = value is None or (isinstance(value, int | float) and not isinstance(value, bool))
    return numeric and bool(_TOKEN_COUNT_KEY.search(key))


def redact_text(text: str) -> str:
    for pattern in _SECRET_VALUES:
        text = pattern.sub("[REDACTED]", text)
    return mask_emails_in_text(text)


def redact(obj: Any) -> Any:
    """Recursively redact dict/list/str values. Keys that look secret are blanked."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if isinstance(key, str) and _SECRET_KEY_NAMES.search(key) and not _is_token_count(key, value):
                out[key] = "[REDACTED]" if value else value
            else:
                out[key] = redact(value)
        return out
    if isinstance(obj, list | tuple):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj

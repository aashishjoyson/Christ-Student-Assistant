"""Stdlib logging with a redaction filter so keys and emails never reach log output."""

from __future__ import annotations

import logging

from app.domain.redaction import redact_text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Format first (so %d etc. still work), then redact the final string.
        record.msg = redact_text(record.getMessage())
        record.args = None
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

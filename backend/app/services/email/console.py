"""Default provider: never contacts a mail server. Writes the email to storage/outbox for inspection."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.domain.masking import mask_email
from app.services.email.base import OutgoingEmail, SendResult

log = logging.getLogger(__name__)


class ConsoleEmailProvider:
    name = "console"

    def __init__(self, outbox_dir: Path) -> None:
        self._outbox = outbox_dir

    def send(self, email: OutgoingEmail) -> SendResult:
        message_id = f"sim-{uuid.uuid4().hex[:12]}"
        try:
            self._outbox.mkdir(parents=True, exist_ok=True)
            (self._outbox / f"{message_id}.txt").write_text(
                f"To: {email.to}\nSubject: {email.subject}\n\n{email.text}", encoding="utf-8"
            )
        except OSError as exc:
            return SendResult(status="failed", provider=self.name, error=f"outbox write failed: {exc}")
        log.info("SIMULATED email %s to %s: %s", message_id, mask_email(email.to), email.subject)
        return SendResult(status="simulated", provider=self.name, provider_message_id=message_id)

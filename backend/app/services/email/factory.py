from __future__ import annotations

from app.core.config import Settings
from app.services.email.base import EmailProvider
from app.services.email.console import ConsoleEmailProvider


def build_email_provider(settings: Settings) -> EmailProvider:
    """Console (simulated) unless real sending is explicitly enabled by the operator."""
    if not settings.email_send_enabled or settings.email_provider == "console":
        return ConsoleEmailProvider(settings.outbox_dir)
    if not settings.allowlist:
        raise RuntimeError("EMAIL_SEND_ENABLED=true requires EMAIL_RECIPIENT_ALLOWLIST (safety guard).")
    # Phase 5 implements SmtpEmailProvider in app/services/email/smtp.py and returns it here.
    raise RuntimeError("SMTP sending is implemented in Phase 5 (see docs/IMPLEMENTATION_PLAN.md).")

from __future__ import annotations

from app.core.config import Settings
from app.services.email.base import EmailProvider
from app.services.email.console import ConsoleEmailProvider
from app.services.email.smtp import SmtpConfigError, SmtpEmailProvider, tidy_app_password


def build_email_provider(settings: Settings) -> EmailProvider:
    """Console (simulated) unless real sending is explicitly enabled by the operator.

    Real sending needs EMAIL_PROVIDER=smtp AND EMAIL_SEND_ENABLED=true AND a non-empty EMAIL_RECIPIENT_ALLOWLIST. A half-configured
    setup raises here, when the application starts, with a message that says what to fix: it never falls back to "simulated" silently
    (that would look like a working email) and never sends with settings it cannot use safely."""
    if not settings.email_send_enabled or settings.email_provider == "console":
        return ConsoleEmailProvider(settings.outbox_dir)
    if not settings.allowlist:
        raise RuntimeError("EMAIL_SEND_ENABLED=true requires EMAIL_RECIPIENT_ALLOWLIST (safety guard).")
    if settings.email_from.strip().lower().endswith("@example.com"):
        raise RuntimeError("EMAIL_SEND_ENABLED=true requires EMAIL_FROM to be the address you send from (it is still the placeholder).")
    password = tidy_app_password(settings.smtp_password.get_secret_value()) if settings.smtp_password else ""
    try:
        return SmtpEmailProvider(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=password,
            sender=settings.email_from,
            use_starttls=settings.smtp_use_starttls,
            timeout=settings.smtp_timeout_seconds,
        )
    except SmtpConfigError as exc:
        raise RuntimeError(f"Real email sending is enabled but the SMTP settings are unusable: {exc}") from exc

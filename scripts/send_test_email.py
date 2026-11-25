"""Send ONE test email through the configured SMTP settings, to check them before a demo.

Usage (from the repo root, backend venv active):
    python scripts/send_test_email.py --to you@gmail.com

It uses the same provider and the same guards as the application: EMAIL_PROVIDER=smtp, EMAIL_SEND_ENABLED=true, and the recipient must be in
EMAIL_RECIPIENT_ALLOWLIST. The message says it is a test and contains no applicant data. "Accepted" means the mail server took the message;
look in the inbox (and the spam folder) to see it arrive.

Exit codes: 0 the server accepted the message, 1 it did not, 2 the settings are unusable or real sending is not switched on.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.domain.masking import mask_email  # noqa: E402
from app.domain.notification_policy import recipient_allowed  # noqa: E402
from app.services.email.base import OutgoingEmail  # noqa: E402
from app.services.email.factory import build_email_provider  # noqa: E402

BODY = (
    "This is a test message from the Student Helpdesk prototype.\n\n"
    "If you can read it, the SMTP settings work and the interview email can reach this inbox.\n"
    "It contains no applicant data.\n\n"
    "-- Student Helpdesk (academic prototype; demo data)\n"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to", required=True, help="the recipient; it must be in EMAIL_RECIPIENT_ALLOWLIST")
    args = parser.parse_args()
    settings = get_settings()
    if not (settings.email_send_enabled and settings.email_provider == "smtp"):
        print("Real sending is not switched on: set EMAIL_PROVIDER=smtp and EMAIL_SEND_ENABLED=true in .env (see docs/SETUP_EMAIL.md).")
        return 2
    try:
        provider = build_email_provider(settings)
    except RuntimeError as exc:
        print(f"The settings cannot be used: {exc}")
        return 2
    if not recipient_allowed(args.to, settings.allowlist):
        print(f"{mask_email(args.to)} is not in EMAIL_RECIPIENT_ALLOWLIST, so the application would refuse it too. Add it to .env first.")
        return 2

    print(f"Sending one test message to {mask_email(args.to)} through {settings.smtp_host}:{settings.smtp_port} ...")
    result = provider.send(OutgoingEmail(to=args.to, subject="Test message from the helpdesk prototype", text=BODY))
    for name, ms in result.steps:
        print(f"  {name:9s} {ms:5d} ms")
    if result.status == "sent":
        print(f"ACCEPTED by the mail server (Message-ID {result.provider_message_id}). Now check the inbox, and the spam folder.")
        return 0
    print(f"NOT SENT: {result.error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

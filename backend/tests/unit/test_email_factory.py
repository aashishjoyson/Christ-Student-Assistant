"""Which email provider the application builds, and that a half-configured setup stops at start-up instead of pretending to work."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.email.console import ConsoleEmailProvider
from app.services.email.factory import build_email_provider
from app.services.email.smtp import SmtpEmailProvider

REAL: dict[str, Any] = {
    "email_provider": "smtp", "email_send_enabled": True, "email_recipient_allowlist": "me@gmail.example", "email_from": "me@gmail.example",
    "smtp_host": "smtp.gmail.example", "smtp_username": "me@gmail.example", "smtp_password": "abcd efgh ijkl mnop",
}


def settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(_env_file=None, outbox_dir=tmp_path / "outbox", **overrides)  # type: ignore[arg-type]


def test_the_default_is_the_simulated_provider(tmp_path: Path) -> None:
    assert isinstance(build_email_provider(settings(tmp_path)), ConsoleEmailProvider)


@pytest.mark.parametrize("overrides", [{"email_provider": "smtp"}, {"email_send_enabled": True}, {"email_provider": "smtp", "email_send_enabled": False}])
def test_real_sending_needs_both_switches(tmp_path: Path, overrides: dict[str, Any]) -> None:
    provider = build_email_provider(settings(tmp_path, **overrides))
    assert provider.name == "console"


def test_both_switches_and_valid_settings_build_the_smtp_provider(tmp_path: Path) -> None:
    provider = build_email_provider(settings(tmp_path, **REAL))
    assert isinstance(provider, SmtpEmailProvider) and provider.name == "smtp"


def test_an_app_password_pasted_with_spaces_is_tidied(tmp_path: Path) -> None:
    provider = build_email_provider(settings(tmp_path, **REAL))
    assert provider._password == "abcdefghijklmnop"  # the shape Google shows it in has spaces that are not part of it


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"email_recipient_allowlist": ""}, "EMAIL_RECIPIENT_ALLOWLIST"),
        ({"email_from": "helpdesk-demo@example.com"}, "EMAIL_FROM"),
        ({"smtp_host": ""}, "SMTP_HOST"),
        ({"smtp_password": None}, "together"),
        ({"smtp_port": 25, "smtp_use_starttls": False, "smtp_host": "mail.remote.example"}, "Plain SMTP"),
    ],
)
def test_a_half_configured_setup_stops_at_start_up_with_a_message_that_says_what_to_fix(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(RuntimeError, match=message):
        build_email_provider(settings(tmp_path, **{**REAL, **overrides}))


def test_the_demo_address_must_be_one_plain_address_or_blank(tmp_path: Path) -> None:
    assert settings(tmp_path, demo_applicant_email="  me@gmail.example ").demo_applicant_email == "me@gmail.example"
    assert settings(tmp_path).demo_applicant_email == ""
    with pytest.raises(ValidationError):
        settings(tmp_path, demo_applicant_email="a@example.com, b@example.com")

"""A pretend mail server for the SMTP provider: nothing opens a socket. Shared by the unit and the integration tests."""

from __future__ import annotations

import smtplib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.services.email.base import OutgoingEmail
from app.services.email.smtp import SmtpEmailProvider

PASSWORD = "abcdefghijklmnop"
SENDER = "helpdesk.sender@gmail.example"
TO = "aarav.demo@example.com"
EMAIL = OutgoingEmail(to=TO, subject="Your interview details - Application CUAPP-DEMO-0001", text="Dear Aarav,\n\nVenue: Demo Room 1\n")


@dataclass
class Script:
    """What the pretend mail server does."""

    offers_starttls: bool = True
    connect_error: Exception | None = None
    login_error: Exception | None = None
    send_error: Exception | None = None
    refused: dict[str, Any] = field(default_factory=dict)
    quit_error: Exception | None = None


class FakeSmtp:
    """Stands in for smtplib.SMTP and smtplib.SMTP_SSL; every call is appended to `log`."""

    def __init__(self, script: Script, log: list[tuple], kind: str, host: str, port: int, timeout: float | None, context: Any = None) -> None:
        if script.connect_error:
            raise script.connect_error
        self.script, self.log = script, log
        log.append((kind, host, port, timeout, context))

    def ehlo(self) -> None:
        self.log.append(("ehlo",))

    def starttls(self, *, context: Any = None) -> None:
        if not self.script.offers_starttls:
            raise smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server.")
        self.log.append(("starttls", context))

    def login(self, user: str, password: str) -> None:
        if self.script.login_error:
            raise self.script.login_error
        self.log.append(("login", user, password))

    def send_message(self, msg: Any, from_addr: str | None = None, to_addrs: list[str] | None = None) -> dict[str, Any]:
        if self.script.send_error:
            raise self.script.send_error
        self.log.append(("send_message", msg, from_addr, list(to_addrs or [])))
        return dict(self.script.refused)

    def quit(self) -> None:
        self.log.append(("quit",))
        if self.script.quit_error:
            raise self.script.quit_error

    def close(self) -> None:
        self.log.append(("close",))


def make_provider(script: Script | None = None, **overrides: Any) -> tuple[SmtpEmailProvider, list[tuple]]:
    script, log = script or Script(), []
    kwargs: dict[str, Any] = {
        "host": "smtp.gmail.example", "port": 587, "username": SENDER, "password": PASSWORD, "sender": SENDER, "use_starttls": True, "timeout": 7.0,
        "smtp_factory": lambda host, port, timeout: FakeSmtp(script, log, "smtp", host, port, timeout),
        "smtp_ssl_factory": lambda host, port, timeout, context: FakeSmtp(script, log, "smtp_ssl", host, port, timeout, context),
    }
    kwargs.update(overrides)
    return SmtpEmailProvider(**kwargs), log


def calls(log: list[tuple], name: str) -> list[tuple]:
    return [entry for entry in log if entry[0] == name]


def ticking_clock(*times: float) -> Callable[[], float]:
    values = iter(times)
    return lambda: next(values)

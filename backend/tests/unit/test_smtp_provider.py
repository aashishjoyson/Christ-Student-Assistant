"""The real-sending provider. Nothing here opens a socket: the standard library's SMTP classes are replaced by a recorder (tests/fakes_smtp.py)
that plays back what a mail server would do (accept, refuse, fail to log in, not offer STARTTLS, time out)."""

from __future__ import annotations

import smtplib
import ssl
from typing import Any

import pytest

from app.services.email.base import OutgoingEmail
from app.services.email.smtp import SmtpConfigError, tidy_app_password
from tests.fakes_smtp import EMAIL, PASSWORD, SENDER, TO, Script, calls, ticking_clock
from tests.fakes_smtp import make_provider as make


# ---------- the happy path ----------
def test_a_message_is_sent_over_starttls_with_login_and_reported_as_sent() -> None:
    provider, log = make(clock=ticking_clock(0.0, 0.1, 0.3, 0.6, 1.0))
    result = provider.send(EMAIL)
    assert result.status == "sent" and result.provider == "smtp" and result.error is None
    assert [entry[0] for entry in log] == ["smtp", "ehlo", "starttls", "ehlo", "login", "send_message", "quit"]
    assert log[0][1:4] == ("smtp.gmail.example", 587, 7.0)  # host, port and the hard timeout
    assert calls(log, "login")[0][1:] == (SENDER, PASSWORD)
    assert result.steps == (("connect", 100), ("starttls", 200), ("login", 300), ("send", 400))


def test_the_message_has_the_right_headers_one_recipient_and_the_text() -> None:
    provider, log = make()
    result = provider.send(EMAIL)
    _, message, envelope_from, envelope_to = calls(log, "send_message")[0]
    assert envelope_from == SENDER and envelope_to == [TO]  # exactly one recipient on the envelope
    assert message["To"] == TO and message["Bcc"] is None and message["Cc"] is None
    assert SENDER in message["From"] and message["Subject"] == EMAIL.subject
    assert message["Message-ID"] == result.provider_message_id and result.provider_message_id.startswith("<")
    assert result.provider_message_id.endswith("@gmail.example>")  # the domain of the sender
    assert message.get_content().strip() == EMAIL.text.strip()
    assert message.get_content_type() == "text/plain"


def test_non_ascii_text_is_carried_as_utf8() -> None:
    provider, log = make()
    provider.send(OutgoingEmail(to=TO, subject="Interview - Zoë", text="Dear Zoë,\n"))
    message = calls(log, "send_message")[0][1]
    assert message.get_content().strip() == "Dear Zoë,"
    assert message.get_content_charset() == "utf-8"


def test_port_465_uses_implicit_tls_without_starttls() -> None:
    provider, log = make(port=465)
    result = provider.send(EMAIL)
    assert result.status == "sent"
    assert [entry[0] for entry in log] == ["smtp_ssl", "login", "send_message", "quit"]
    assert log[0][2] == 465 and isinstance(log[0][4], ssl.SSLContext)
    assert [name for name, _ in result.steps] == ["connect", "login", "send"]


def test_the_default_tls_context_verifies_the_certificate_and_the_host_name() -> None:
    provider, log = make()
    provider.send(EMAIL)
    context = calls(log, "starttls")[0][1]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_a_server_on_this_machine_may_be_used_without_encryption_or_login() -> None:
    provider, log = make(host="localhost", port=1025, use_starttls=False, username="", password="")
    assert provider.send(EMAIL).status == "sent"
    assert [entry[0] for entry in log] == ["smtp", "ehlo", "send_message", "quit"]  # no starttls, no login


# ---------- it never downgrades and never accepts an unsafe configuration ----------
def test_a_server_that_does_not_offer_starttls_is_not_used_in_plain_text() -> None:
    provider, log = make(Script(offers_starttls=False))
    result = provider.send(EMAIL)
    assert result.status == "failed" and "STARTTLS" in (result.error or "")
    assert not calls(log, "login") and not calls(log, "send_message")  # nothing was sent, no password went over the wire


def test_plain_smtp_to_a_remote_server_is_refused_when_the_provider_is_built() -> None:
    with pytest.raises(SmtpConfigError, match="Plain SMTP"):
        make(host="smtp.example.net", port=25, use_starttls=False)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"host": "  "}, "SMTP_HOST"),
        ({"sender": "Helpdesk <h@x.example>"}, "EMAIL_FROM"),
        ({"sender": "not-an-address"}, "EMAIL_FROM"),
        ({"username": SENDER, "password": ""}, "together"),
        ({"username": "", "password": PASSWORD}, "together"),
    ],
)
def test_unusable_settings_are_rejected_when_the_provider_is_built(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(SmtpConfigError, match=message):
        make(**overrides)


# ---------- failures are reported as failures, with a safe one-line reason ----------
def test_a_failed_login_is_reported_without_the_password_or_the_raw_address() -> None:
    echo = smtplib.SMTPAuthenticationError(535, f"5.7.8 Username {SENDER} and password {PASSWORD} not accepted".encode())
    provider, log = make(Script(login_error=echo))
    result = provider.send(EMAIL)
    assert result.status == "failed" and "535" in (result.error or "")
    assert PASSWORD not in (result.error or "") and SENDER not in (result.error or "")
    assert "app password" in (result.error or "")  # the hint for the usual Gmail mistake
    assert not calls(log, "send_message")
    assert [name for name, _ in result.steps] == ["connect", "starttls"]  # how far it got
    assert calls(log, "quit")  # the connection is closed


def test_a_refused_recipient_is_a_failure_and_the_address_is_masked() -> None:
    refusal = smtplib.SMTPRecipientsRefused({TO: (550, b"5.1.1 no such user")})
    result = make(Script(send_error=refusal))[0].send(EMAIL)
    assert result.status == "failed" and result.provider_message_id is None
    assert TO not in (result.error or "")


def test_a_partial_refusal_is_not_reported_as_sent() -> None:
    result = make(Script(refused={TO: (550, b"mailbox unavailable")}))[0].send(EMAIL)
    assert result.status == "failed" and "refused" in (result.error or "")


def test_a_rejected_message_reports_the_server_code() -> None:
    result = make(Script(send_error=smtplib.SMTPDataError(554, b"5.7.1 message rejected as spam")))[0].send(EMAIL)
    assert result.status == "failed" and "554" in (result.error or "")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("timed out"), "timed out after 7 s"),
        (ConnectionRefusedError("connection refused"), "ConnectionRefusedError"),
        (ssl.SSLCertVerificationError("certificate verify failed"), "SSLCertVerificationError"),
        (smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), "SMTPServerDisconnected"),
    ],
)
def test_connection_problems_are_failures_not_exceptions(error: Exception, expected: str) -> None:
    result = make(Script(connect_error=error))[0].send(EMAIL)
    assert result.status == "failed" and expected in (result.error or "")


def test_a_failure_while_closing_the_connection_does_not_undo_an_accepted_message() -> None:
    provider, log = make(Script(quit_error=smtplib.SMTPServerDisconnected("closed")))
    assert provider.send(EMAIL).status == "sent"
    assert calls(log, "close")


def test_one_attempt_only_there_is_no_retry_inside_the_provider() -> None:
    provider, log = make(Script(send_error=smtplib.SMTPDataError(451, b"try again later")))
    provider.send(EMAIL)
    assert len(calls(log, "smtp")) == 1 and len(calls(log, "send_message")) == 0


def test_error_text_is_one_short_line() -> None:
    long_text = ("line one\n" + "x" * 1000).encode()
    result = make(Script(send_error=smtplib.SMTPDataError(554, long_text)))[0].send(EMAIL)
    assert "\n" not in (result.error or "") and len(result.error or "") <= 260


# ---------- the recipient and subject cannot be used to inject headers ----------
@pytest.mark.parametrize(
    "recipient",
    [
        "a@example.com, b@example.com",
        "Name <a@example.com>",
        "a@example.com\nBcc: x@example.org",
        "a@example.com\r\nBcc: x@example.org",
        "a b@example.com",
        "",
        "no-at-sign",
    ],
)
def test_only_one_plain_address_is_accepted_and_nothing_is_opened_otherwise(recipient: str) -> None:
    provider, log = make()
    result = provider.send(OutgoingEmail(to=recipient, subject="s", text="t"))
    assert result.status == "failed" and "not sent" in (result.error or "")
    assert log == []  # no connection was made


@pytest.mark.parametrize("subject", ["Hello\nBcc: evil@example.org", "Hello\rBcc: evil@example.org"])
def test_a_subject_with_a_line_break_is_refused(subject: str) -> None:
    provider, log = make()
    result = provider.send(OutgoingEmail(to=TO, subject=subject, text="t"))
    assert result.status == "failed" and log == []


# ---------- the app password helper ----------
@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("abcd efgh ijkl mnop", "abcdefghijklmnop"),
        ("abcdefghijklmnop", "abcdefghijklmnop"),
        ("my pass word", "my pass word"),  # not the app-password shape: left alone
        ("Abcd efgh ijkl mnop", "Abcd efgh ijkl mnop"),
        ("", ""),
    ],
)
def test_an_app_password_pasted_with_spaces_is_tidied_and_other_passwords_are_not_touched(given: str, expected: str) -> None:
    assert tidy_app_password(given) == expected

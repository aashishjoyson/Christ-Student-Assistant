"""Real sending over SMTP (Phase 5).

Used only when EMAIL_PROVIDER=smtp AND EMAIL_SEND_ENABLED=true; the interview-resend rule has already checked the recipient against
EMAIL_RECIPIENT_ALLOWLIST by the time `send` is called. `sent` means the mail server ACCEPTED the message. It does not prove the message
reached an inbox, so nothing in the product says "delivered".

Safety choices, each pinned by a test (tests/unit/test_smtp_provider.py):
- The connection is always encrypted and the certificate and host name are verified: STARTTLS on port 587 (never silently downgraded when
  the server does not offer it) or implicit TLS on port 465. Plain SMTP is accepted only for a server on this machine (a local test sink).
- The recipient must be ONE plain address (no list, no display name), and the standard-library message class refuses a line break in any
  header, so a subject or an address cannot smuggle in a Bcc. The envelope recipient is that one address and nothing else.
- One attempt, a hard timeout, no retry inside the provider: the cooldown rules decide whether a person may ask again.
- An error is reduced to one short line with the password and the addresses removed. The message text is never logged.
"""

from __future__ import annotations

import contextlib
import logging
import re
import smtplib
import ssl
import time
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.domain.masking import mask_email
from app.domain.notification_policy import is_valid_email
from app.services.email.base import OutgoingEmail, SendResult

log = logging.getLogger(__name__)

IMPLICIT_TLS_PORT = 465
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
MAX_ERROR_CHARS = 220
DISPLAY_NAME = "Student Helpdesk (prototype)"
AUTH_HINT = " Check SMTP_USERNAME and the app password (Gmail needs 2-Step Verification and an app password)."
_APP_PASSWORD_SHAPE = re.compile(r"[a-z]{4}( [a-z]{4}){3}")


class SmtpConfigError(ValueError):
    """The SMTP settings cannot be used safely. Raised when the application starts, never while sending."""


def tidy_app_password(password: str) -> str:
    """Google shows an app password as four groups of four letters; the spaces are not part of it. Anything else is left alone."""
    return password.replace(" ", "") if _APP_PASSWORD_SHAPE.fullmatch(password) else password


def _default_tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()  # verifies the certificate chain and the host name
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class SmtpEmailProvider:
    name = "smtp"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        use_starttls: bool = True,
        timeout: float = 15.0,
        tls_context: ssl.SSLContext | None = None,
        smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
        smtp_ssl_factory: Callable[..., smtplib.SMTP_SSL] = smtplib.SMTP_SSL,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        host = host.strip()
        if not host:
            raise SmtpConfigError("SMTP_HOST is empty.")
        if not is_valid_email(sender):
            raise SmtpConfigError("EMAIL_FROM must be one plain address such as helpdesk@yourdomain.example.")
        if bool(username) != bool(password):
            raise SmtpConfigError("SMTP_USERNAME and SMTP_PASSWORD must be set together.")
        self._implicit_tls = port == IMPLICIT_TLS_PORT
        self._starttls = use_starttls and not self._implicit_tls
        if not (self._implicit_tls or self._starttls) and host.lower() not in LOCAL_HOSTS:
            raise SmtpConfigError("Plain SMTP to a remote server is refused: use port 587 with STARTTLS, or port 465.")
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_addr = sender.strip()
        self._timeout = timeout
        self._tls = tls_context or _default_tls_context()
        self._smtp = smtp_factory
        self._smtp_ssl = smtp_ssl_factory
        self._clock = clock

    # ---------- public ----------
    def send(self, email: OutgoingEmail) -> SendResult:
        recipient = email.to.strip()
        try:
            message = self._message(recipient, email)
        except ValueError as exc:  # not one plain address, or a header with a line break: nothing is opened, nothing is sent
            return SendResult(status="failed", provider=self.name, error=self._clean(f"not sent: {exc}", recipient))

        steps: list[tuple[str, int]] = []
        server: smtplib.SMTP | None = None
        try:
            lap = self._clock()
            if self._implicit_tls:
                server = self._smtp_ssl(self._host, self._port, timeout=self._timeout, context=self._tls)
            else:
                server = self._smtp(self._host, self._port, timeout=self._timeout)
            lap = self._lap(steps, "connect", lap)
            if not self._implicit_tls:
                server.ehlo()
            if self._starttls:
                server.starttls(context=self._tls)  # raises when the server does not offer it: no fall back to plain text
                server.ehlo()
                lap = self._lap(steps, "starttls", lap)
            if self._username:
                server.login(self._username, self._password)
                lap = self._lap(steps, "login", lap)
            refused = server.send_message(message, from_addr=self._from_addr, to_addrs=[recipient])
            self._lap(steps, "send", lap)
        except smtplib.SMTPAuthenticationError as exc:
            return self._failure(exc, recipient, steps, AUTH_HINT)
        except (smtplib.SMTPException, OSError) as exc:  # refused recipient, no STARTTLS, TLS failure, timeout, unreachable host ...
            return self._failure(exc, recipient, steps)
        finally:
            self._close(server)

        if refused:  # the server accepted the message for some recipients but named one it refused
            return SendResult(status="failed", provider=self.name, error="the server refused the recipient", steps=tuple(steps))
        log.info("SMTP accepted %s for %s in %d ms", message["Message-ID"], mask_email(recipient), sum(ms for _, ms in steps))
        return SendResult(status="sent", provider=self.name, provider_message_id=str(message["Message-ID"]), steps=tuple(steps))

    # ---------- helpers ----------
    def _message(self, recipient: str, email: OutgoingEmail) -> EmailMessage:
        if not is_valid_email(recipient):
            raise ValueError("the recipient is not one plain email address")
        if any(ch in email.subject for ch in "\r\n"):  # checked here as well as by the message class: this is the Bcc-injection door
            raise ValueError("the subject contains a line break")
        message = EmailMessage()  # its default policy also raises on a header value that contains a line break
        message["From"] = formataddr((DISPLAY_NAME, self._from_addr))
        message["To"] = recipient
        message["Subject"] = email.subject
        message["Date"] = formatdate(usegmt=True)
        message["Message-ID"] = make_msgid(domain=self._from_addr.rsplit("@", 1)[1])
        message["X-Prototype"] = "academic prototype; synthetic demo data"
        message.set_content(email.text)
        return message

    def _lap(self, steps: list[tuple[str, int]], name: str, since: float) -> float:
        now = self._clock()
        steps.append((name, max(0, round((now - since) * 1000))))
        return now

    @staticmethod
    def _close(server: smtplib.SMTP | None) -> None:
        if server is None:
            return
        try:
            server.quit()
        except Exception:  # the message is already accepted or already failed; closing is best effort
            with contextlib.suppress(Exception):
                server.close()

    def _failure(self, exc: Exception, recipient: str, steps: list[tuple[str, int]], hint: str = "") -> SendResult:
        code = getattr(exc, "smtp_code", None)
        server_text = getattr(exc, "smtp_error", None)
        if isinstance(server_text, bytes):
            server_text = server_text.decode("utf-8", "replace")
        if code is not None:
            detail = f"SMTP {code}: {server_text or ''}"
        elif isinstance(exc, smtplib.SMTPRecipientsRefused):
            detail = "the server refused the recipient"
        elif isinstance(exc, TimeoutError):
            detail = f"timed out after {self._timeout:g} s"
        else:
            detail = f"{type(exc).__name__}: {exc}"
        log.warning("SMTP send to %s failed (%s)", mask_email(recipient), type(exc).__name__)
        return SendResult(status="failed", provider=self.name, error=self._clean(detail, recipient) + hint, steps=tuple(steps))

    def _clean(self, text: str, recipient: str) -> str:
        """One short line: no password, no raw addresses."""
        text = " ".join(str(text).split())
        if self._password:
            text = text.replace(self._password, "***")
        for address in (recipient, self._username, self._from_addr):
            if address and "@" in address:
                text = text.replace(address, mask_email(address))
        return text[:MAX_ERROR_CHARS]

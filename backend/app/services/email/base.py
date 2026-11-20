from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

SendStatus = Literal["sent", "simulated", "failed"]


@dataclass(frozen=True)
class OutgoingEmail:
    to: str  # always the registered_email from the database
    subject: str
    text: str


@dataclass(frozen=True)
class SendResult:
    status: SendStatus  # "sent" only after the provider accepted the message
    provider: str
    provider_message_id: str | None = None
    error: str | None = None


class EmailProvider(Protocol):
    name: str

    def send(self, email: OutgoingEmail) -> SendResult: ...

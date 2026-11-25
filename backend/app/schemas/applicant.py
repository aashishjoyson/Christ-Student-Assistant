from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class VerifyRequest(BaseModel):
    application_id: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9\-]+$")
    registered_email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class VerifiedApplicantOut(BaseModel):
    application_id: str
    first_name: str
    masked_email: str
    programme: str


class DemoApplicantOut(BaseModel):
    """One ready-made SYNTHETIC login for the demo. `email_prefill` is set only for synthetic example.com addresses; any other address
    (a real inbox given to the demo applicant) is shown masked in `email_hint` and the visitor has to type it."""

    application_id: str
    first_name: str
    scenario: str
    email_prefill: str | None
    email_hint: str
    real_inbox: bool
    suggestions: list[str]
    resend_outcome: str


class VerifyResponse(BaseModel):
    verified: bool
    session_token: str
    expires_at: datetime
    applicant: VerifiedApplicantOut

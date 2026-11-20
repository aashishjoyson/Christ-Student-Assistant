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


class VerifyResponse(BaseModel):
    verified: bool
    session_token: str
    expires_at: datetime
    applicant: VerifiedApplicantOut

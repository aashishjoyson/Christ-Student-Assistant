"""Prototype applicant verification. PRODUCTION REQUIRES INSTITUTIONAL SSO - this is demo-level only."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_container
from app.container import AppContainer
from app.db.repositories.applicants import verify_applicant
from app.domain.clock import utcnow
from app.domain.masking import normalize_application_id
from app.domain.tokens import issue_token
from app.schemas.applicant import VerifiedApplicantOut, VerifyRequest, VerifyResponse

router = APIRouter(prefix="/api/demo/applicant", tags=["applicant"])

GENERIC_FAILURE = "Could not verify these details. Check the application ID and registered email."


@router.post("/verify", response_model=VerifyResponse)
def verify(body: VerifyRequest, request: Request, container: AppContainer = Depends(get_container)) -> VerifyResponse:
    now = utcnow()
    client_ip = request.client.host if request.client else "unknown"
    limiter = container.verify_limiter
    # Limit per client and per application id, so neither guessing emails nor IDs is cheap.
    if not (limiter.hit(f"ip:{client_ip}", now) and limiter.hit(f"app:{normalize_application_id(body.application_id)}", now)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please wait and try again.")

    with container.session_factory() as session:
        verified = verify_applicant(session, body.application_id, body.registered_email)
    if verified is None:
        # Same message whether the ID is unknown or the email is wrong (no account enumeration).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_FAILURE)

    token, expires_at = issue_token(
        verified.applicant_id,
        container.settings.secret_key_bytes(),
        timedelta(minutes=container.settings.applicant_session_ttl_minutes),
        now,
    )
    return VerifyResponse(
        verified=True,
        session_token=token,
        expires_at=expires_at,
        applicant=VerifiedApplicantOut(
            application_id=verified.application_id,
            first_name=verified.first_name,
            masked_email=verified.masked_email,
            programme=verified.programme,
        ),
    )

"""Prototype applicant verification. PRODUCTION REQUIRES INSTITUTIONAL SSO - this is demo-level only."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_container
from app.container import AppContainer
from app.db.repositories.applicants import SyntheticApplicantView, list_synthetic_applicants, verify_applicant
from app.domain.clock import utcnow
from app.domain.masking import mask_email, normalize_application_id
from app.domain.notification_policy import ACTIVE_INTERVIEW_STATUSES, recipient_allowed
from app.domain.tokens import issue_token
from app.schemas.applicant import DemoApplicantOut, VerifiedApplicantOut, VerifyRequest, VerifyResponse

router = APIRouter(prefix="/api/demo/applicant", tags=["applicant"])

GENERIC_FAILURE = "Could not verify these details. Check the application ID and registered email."

STATUS_TEXT = {"submitted": "Submitted", "under_review": "Under review", "shortlisted": "Shortlisted", "interview_scheduled": "Interview scheduled",
               "offer_made": "Offer made", "waitlisted": "Waitlisted", "not_selected": "Not selected"}


def _scenario(view: SyntheticApplicantView) -> str:
    interview = "no interview" if not view.interview_status else f"interview {view.interview_status}" + (
        f" ({view.interview_mode.replace('_', ' ')})" if view.interview_mode else "")
    return f"{STATUS_TEXT.get(view.application_status, view.application_status)}, {interview}"


def _resend_outcome(view: SyntheticApplicantView, container: AppContainer) -> str:
    """What asking for the interview email again will do for this applicant right now, given the email settings."""
    s = container.settings
    if not view.interview_status:
        return "Refused: there is no interview to resend."
    if view.interview_status not in ACTIVE_INTERVIEW_STATUSES:
        return "Refused: the interview is not active (completed or cancelled)."
    if s.email_send_enabled and not recipient_allowed(view.registered_email, s.allowlist):
        return "Refused: this address is not on the email allowlist, so nothing is sent."
    if s.email_send_enabled and s.email_provider == "smtp":
        return "A real email is sent to this address (once per 15 minutes)."
    return "Simulated: the email is written to the outbox and nothing is delivered."


@router.get("/examples", response_model=list[DemoApplicantOut])
def examples(container: AppContainer = Depends(get_container)) -> list[DemoApplicantOut]:
    """Ready-made SYNTHETIC demo logins and what to ask each. Off in production. Only synthetic example.com addresses are shown in full;
    a real inbox given to the demo applicant is shown masked (the visitor types it), so this list never reveals a real address."""
    if container.settings.app_env == "production":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not available.")
    with container.session_factory() as session:
        views = list_synthetic_applicants(session)
    out = []
    for v in views:
        synthetic_address = v.registered_email.lower().endswith("@example.com")
        asks = ["When is my interview?", "I have not received my interview email", "What is the status of my application?"] if v.interview_status \
            else ["What is the status of my application?", "When is my interview?"]
        out.append(DemoApplicantOut(application_id=v.application_id, first_name=v.first_name, scenario=_scenario(v),
                                    email_prefill=v.registered_email if synthetic_address else None, email_hint=mask_email(v.registered_email),
                                    real_inbox=not synthetic_address, suggestions=asks, resend_outcome=_resend_outcome(v, container)))
    return out


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

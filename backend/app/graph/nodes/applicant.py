"""Applicant-service nodes: identity, status, interview and the controlled email workflow.

No LLM is involved anywhere in this file. Facts come from fixed repository functions,
responses come from templates, and the email recipient is read from the database
inside send_interview_email - it is never taken from the chat message or from state.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.db.repositories import applicants as repo
from app.db.repositories import notifications as notif_repo
from app.domain.clock import format_local
from app.domain.email_templates import InterviewEmailData, render_interview_email
from app.domain.intents import Intent
from app.domain.masking import mask_email
from app.domain.notification_policy import (
    EligibilityDecision,
    Ineligible,
    InterviewSnapshot,
    PolicyConfig,
    decide_resend,
    make_window_key,
    recipient_allowed,
)
from app.domain.tokens import verify_token
from app.graph.deps import GraphDeps
from app.graph.state import APPLICANT_HISTORY_PLACEHOLDER, HelpdeskState, step
from app.services.email.base import OutgoingEmail, SendResult

APPLICANT_SERVICE = {"kind": "applicant_service", "label": "Applicant service (database lookup, no LLM)"}

STATUS_LABELS = {
    "submitted": "Submitted - awaiting review",
    "under_review": "Under review",
    "shortlisted": "Shortlisted",
    "interview_scheduled": "Interview scheduled",
    "offer_made": "Offer made",
    "waitlisted": "Waitlisted",
    "not_selected": "Not selected",
}

VERIFY_PROMPT = (
    "To protect your information, please verify first: enter your application ID and registered email "
    "in the 'Verify applicant' panel, then ask again."
)


def _interview_dict(view: repo.InterviewView) -> dict[str, Any]:
    return {
        "interview_id": view.interview_id,
        "scheduled_at": view.scheduled_at.isoformat(),
        "mode": view.mode,
        "location_or_meeting_link": view.location_or_meeting_link,
        "interviewer_label": view.interviewer_label,
        "status": view.status,
    }


class ApplicantNodes:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps

    @property
    def _tz(self) -> str:
        return self.deps.settings.app_timezone

    def verify_identity(self, state: HelpdeskState) -> dict[str, Any]:
        path = step(state, "verify_identity")
        applicant_id = verify_token(state.get("applicant_token"), self.deps.settings.secret_key_bytes(), self.deps.now())
        if applicant_id is not None:
            with self.deps.session_factory() as session:
                if repo.applicant_exists(session, applicant_id):
                    return {"verified": True, "applicant_id": applicant_id, "node_path": path}
        return {
            "verified": False,
            "applicant_id": None,
            "action_status": "verification_required",
            "response": VERIFY_PROMPT,
            "handled_by": APPLICANT_SERVICE,
            "history": [{"role": "assistant", "content": VERIFY_PROMPT}],
            "node_path": path,
        }

    def fetch_application_status(self, state: HelpdeskState) -> dict[str, Any]:
        with self.deps.session_factory() as session:
            view = repo.get_application_status(session, state["applicant_id"])  # type: ignore[arg-type]
        application = None
        if view:
            application = {
                "application_id": view.application_id,
                "programme": view.programme,
                "status": view.status,
                "status_updated_at": view.status_updated_at.isoformat(),
            }
        return {"application": application, "node_path": step(state, "fetch_application_status")}

    def fetch_interview_details(self, state: HelpdeskState) -> dict[str, Any]:
        with self.deps.session_factory() as session:
            view = repo.get_interview_details(session, state["applicant_id"], self.deps.now())  # type: ignore[arg-type]
        return {
            "interview": _interview_dict(view) if view else None,
            "node_path": step(state, "fetch_interview_details"),
        }

    def check_resend_eligibility(self, state: HelpdeskState) -> dict[str, Any]:
        """Apply business rules, then atomically reserve the send (UNIQUE idempotency key)."""
        s = self.deps.settings
        now = self.deps.now()
        path = step(state, "check_resend_eligibility")
        applicant_id: int = state["applicant_id"]  # type: ignore[assignment]
        interview = state.get("interview")
        cooldown = timedelta(minutes=s.notification_cooldown_minutes)

        with self.deps.session_factory() as session:
            contact = repo.get_applicant_contact(session, applicant_id)
            recipient = contact.registered_email if contact else ""
            snapshot = None
            history = []
            if interview:
                snapshot = InterviewSnapshot(
                    interview["interview_id"], interview["status"], datetime.fromisoformat(interview["scheduled_at"])
                )
                history = repo.get_notification_history(
                    session, applicant_id, interview["interview_id"], since=now - timedelta(days=1)
                )
            decision = decide_resend(
                snapshot, history, recipient, now, PolicyConfig(cooldown=cooldown, max_per_day=s.notification_max_per_day)
            )
            if decision.eligible and s.email_send_enabled and not recipient_allowed(recipient, s.allowlist):
                decision = EligibilityDecision(False, Ineligible.RECIPIENT_NOT_ALLOWLISTED)
            if not decision.eligible:
                return {
                    "eligibility": {
                        "eligible": False,
                        "reason": decision.reason.value if decision.reason else None,
                        "retry_after": decision.retry_after.isoformat() if decision.retry_after else None,
                    },
                    "action_status": "not_eligible",
                    "notification": {"masked_recipient": mask_email(recipient) if recipient else None},
                    "node_path": path,
                }
            event_id = notif_repo.reserve_notification(
                session,
                applicant_id=applicant_id,
                interview_id=interview["interview_id"],  # type: ignore[index]
                recipient_email=recipient,
                idempotency_key=make_window_key(interview["interview_id"], now, cooldown),  # type: ignore[index]
                request_id=state.get("request_id", ""),
                provider=self.deps.email_provider.name,
                now=now,
            )
        if event_id is None:
            return {
                "eligibility": {"eligible": False, "reason": Ineligible.DUPLICATE_IN_PROGRESS.value, "retry_after": None},
                "action_status": "not_eligible",
                "notification": {"masked_recipient": mask_email(recipient)},
                "node_path": path,
            }
        return {
            "eligibility": {"eligible": True, "reason": None, "retry_after": None},
            "notification": {"event_id": event_id, "masked_recipient": mask_email(recipient)},
            "node_path": path,
        }

    def send_interview_email(self, state: HelpdeskState) -> dict[str, Any]:
        """Re-read recipient and interview fields from the DB, render the fixed template, send."""
        path = step(state, "send_interview_email")
        applicant_id: int = state["applicant_id"]  # type: ignore[assignment]
        interview_id = state["interview"]["interview_id"]  # type: ignore[index]
        with self.deps.session_factory() as session:
            contact = repo.get_applicant_contact(session, applicant_id)
            interview = repo.get_interview_for_applicant(session, interview_id, applicant_id)
        notification = dict(state.get("notification") or {})
        if contact is None or interview is None:
            result = SendResult(status="failed", provider=self.deps.email_provider.name, error="record not found")
        else:
            content = render_interview_email(
                InterviewEmailData(
                    full_name=contact.full_name,
                    application_id=contact.application_id,
                    programme=contact.programme,
                    scheduled_at=interview.scheduled_at,
                    mode=interview.mode,
                    location_or_meeting_link=interview.location_or_meeting_link,
                    interviewer_label=interview.interviewer_label,
                ),
                self._tz,
            )
            try:
                result = self.deps.email_provider.send(
                    OutgoingEmail(to=contact.registered_email, subject=content.subject, text=content.text)
                )
            except Exception as exc:  # provider bugs must still be audited as failures
                result = SendResult(status="failed", provider=self.deps.email_provider.name, error=str(exc))
        notification.update(
            send_status=result.status,
            provider=result.provider,
            provider_message_id=result.provider_message_id,
            send_error=result.error,
            send_steps=[list(item) for item in result.steps],
        )
        return {"notification": notification, "node_path": path}

    def record_notification(self, state: HelpdeskState) -> dict[str, Any]:
        notification = state.get("notification") or {}
        with self.deps.session_factory() as session:
            notif_repo.complete_notification(
                session,
                notification["event_id"],
                status=notification["send_status"],
                provider_message_id=notification.get("provider_message_id"),
                error_message=notification.get("send_error"),
                now=self.deps.now(),
            )
        return {"action_status": notification["send_status"], "node_path": step(state, "record_notification")}

    def compose_applicant_response(self, state: HelpdeskState) -> dict[str, Any]:
        intent = state.get("intent")
        if intent == Intent.APPLICANT_STATUS:
            text = self._status_text(state.get("application"))
        elif intent == Intent.INTERVIEW_DETAILS:
            text = self._interview_text(state.get("interview"))
        else:
            text = self._resend_text(state)
        return {
            "response": text,
            "handled_by": APPLICANT_SERVICE,
            "history": [{"role": "assistant", "content": APPLICANT_HISTORY_PLACEHOLDER}],
            "node_path": step(state, "compose_applicant_response"),
        }

    # ---------- templates ----------
    def _status_text(self, application: dict[str, Any] | None) -> str:
        if not application:
            return "I couldn't find an application record for your verified profile. Please contact the admissions office."
        updated = format_local(datetime.fromisoformat(application["status_updated_at"]), self._tz)
        label = STATUS_LABELS.get(application["status"], application["status"])
        return (
            f"Your application {application['application_id']} for {application['programme']} is currently: "
            f"{label} (last updated {updated})."
        )

    def _interview_text(self, interview: dict[str, Any] | None) -> str:
        if not interview:
            return "There is no interview scheduled for your application at the moment."
        when = format_local(datetime.fromisoformat(interview["scheduled_at"]), self._tz)
        where_label = "Meeting link" if interview["mode"] == "online" else "Venue"
        return (
            f"Your interview ({interview['status']}) is on {when}, mode: {interview['mode']}. "
            f"{where_label}: {interview['location_or_meeting_link']}. Panel: {interview['interviewer_label']}."
        )

    def _resend_text(self, state: HelpdeskState) -> str:
        status = state.get("action_status")
        notification = state.get("notification") or {}
        masked = notification.get("masked_recipient") or "your registered email"
        if status == "sent":
            return f"Done - I've re-sent your interview details to {masked}. Please also check your spam folder."
        if status == "simulated":
            return (
                f"Done - your interview details were re-sent to {masked}. "
                "(Demo mode: the email was simulated and not actually delivered.)"
            )
        if status == "failed":
            return (
                "Sorry, I couldn't send the email right now. Nothing was marked as sent. "
                "Please try again in a few minutes or contact the admissions office."
            )
        eligibility = state.get("eligibility") or {}
        reason = eligibility.get("reason")
        if reason == Ineligible.COOLDOWN_ACTIVE and eligibility.get("retry_after"):
            retry = format_local(datetime.fromisoformat(eligibility["retry_after"]), self._tz)
            return (
                f"Your interview email was already sent to {masked} a few minutes ago. "
                f"Please check your inbox and spam folder. You can request another copy after {retry}."
            )
        messages = {
            Ineligible.NO_INTERVIEW: "There is no scheduled interview for your application, so there is no email to resend.",
            Ineligible.INTERVIEW_NOT_ACTIVE: "Your interview is not currently active (it may be completed or cancelled), "
            "so I can't resend it. Please contact the admissions office.",
            Ineligible.INTERVIEW_IN_PAST: "Your interview time has already passed, so I can't resend the invitation.",
            Ineligible.DAILY_LIMIT: "The daily limit for resending this email has been reached. Please try again tomorrow "
            "or contact the admissions office.",
            Ineligible.DUPLICATE_IN_PROGRESS: f"A resend to {masked} is already in progress. Please check your inbox shortly.",
            Ineligible.INVALID_RECIPIENT: "Your registered email looks invalid, so I can't send to it. "
            "Please contact the admissions office.",
            Ineligible.RECIPIENT_NOT_ALLOWLISTED: "Email sending is restricted to approved test recipients in this "
            "prototype, so I can't send to your address.",
        }
        return messages.get(reason, "I couldn't resend the email. Please contact the admissions office.")  # type: ignore[arg-type]

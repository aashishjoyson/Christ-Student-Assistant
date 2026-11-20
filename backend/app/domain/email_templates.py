"""Fixed interview email template. Every field comes from the database, never from an LLM."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.clock import format_local


@dataclass(frozen=True)
class InterviewEmailData:
    full_name: str
    application_id: str
    programme: str
    scheduled_at: datetime
    mode: str
    location_or_meeting_link: str
    interviewer_label: str


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text: str


def render_interview_email(data: InterviewEmailData, tz_name: str) -> EmailContent:
    when = format_local(data.scheduled_at, tz_name)
    where_label = "Meeting link" if data.mode == "online" else "Venue"
    subject = f"Your interview details - Application {data.application_id}"
    text = (
        f"Dear {data.full_name},\n\n"
        f"As requested through the student helpdesk, here are your interview details again.\n\n"
        f"Application ID: {data.application_id}\n"
        f"Programme: {data.programme}\n"
        f"Date and time: {when}\n"
        f"Mode: {data.mode}\n"
        f"{where_label}: {data.location_or_meeting_link}\n"
        f"Panel: {data.interviewer_label}\n\n"
        "If any of these details look wrong, please contact the admissions office directly.\n\n"
        "-- Student Helpdesk (academic prototype; demo data)\n"
    )
    return EmailContent(subject=subject, text=text)

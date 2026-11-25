"""Reset and seed the SYNTHETIC applicant database from data/synthetic_applicants.csv.

Interview times are stored in the CSV as offsets from "today" plus a local time, so the
demo data never goes stale (interviews stay in the future when you re-seed).
"""

from __future__ import annotations

import csv
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Applicant, Application, Interview
from app.domain.notification_policy import is_valid_email

# The applicant whose interview email the live demo resends. Only this record can be given a real address (see DEMO_APPLICANT_EMAIL).
DEMO_EMAIL_APPLICANT = "CUAPP-DEMO-0001"


def _local_to_utc(day_offset: int, hhmm: str, tz_name: str, now: datetime) -> datetime:
    tz = ZoneInfo(tz_name)
    local_date = now.astimezone(tz).date() + timedelta(days=day_offset)
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime.combine(local_date, time(hour, minute), tzinfo=tz).astimezone(ZoneInfo("UTC"))


def reset_and_seed(engine: Engine, csv_path: Path, tz_name: str, now: datetime, demo_email: str | None = None) -> int:
    """Drop every table and load the CSV. `demo_email` replaces the registered address of DEMO_EMAIL_APPLICANT only, so a real inbox can
    receive the demo's interview email without a personal address ever being written into the tracked CSV."""
    if demo_email and not is_valid_email(demo_email):
        raise ValueError("demo_email must be one plain email address")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    count = 0
    with Session(engine) as session, csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            application_id = row["application_id"].strip().upper()
            applicant = Applicant(
                application_id=application_id,
                full_name=row["full_name"].strip(),
                registered_email=demo_email.strip() if demo_email and application_id == DEMO_EMAIL_APPLICANT else row["registered_email"].strip(),
                programme=row["programme"].strip(),
                is_synthetic=True,
                created_at=now,
            )
            session.add(applicant)
            session.flush()
            session.add(
                Application(
                    applicant_id=applicant.id,
                    status=row["application_status"].strip(),
                    status_updated_at=now - timedelta(days=int(row["status_days_ago"])),
                    notes=row.get("notes", "").strip(),
                )
            )
            if row["interview_status"].strip():
                session.add(
                    Interview(
                        applicant_id=applicant.id,
                        scheduled_at=_local_to_utc(
                            int(row["interview_offset_days"]), row["interview_local_time"], tz_name, now
                        ),
                        mode=row["interview_mode"].strip(),
                        location_or_meeting_link=row["interview_location"].strip(),
                        interviewer_label=row["interviewer_label"].strip(),
                        status=row["interview_status"].strip(),
                        updated_at=now,
                    )
                )
            count += 1
        session.commit()
    return count


def set_demo_email(engine: Engine, email: str) -> bool:
    """Change DEMO_EMAIL_APPLICANT's registered address in place: nothing is dropped, so the indexing history, feedback and
    notification audit survive. Returns False when that applicant does not exist (the database was never seeded)."""
    if not is_valid_email(email):
        raise ValueError("email must be one plain email address")
    with Session(engine) as session:
        applicant = session.execute(select(Applicant).where(Applicant.application_id == DEMO_EMAIL_APPLICANT)).scalar_one_or_none()
        if applicant is None:
            return False
        applicant.registered_email = email.strip()
        session.commit()
    return True

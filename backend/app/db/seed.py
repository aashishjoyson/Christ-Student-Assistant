"""Reset and seed the SYNTHETIC applicant database from data/synthetic_applicants.csv.

Interview times are stored in the CSV as offsets from "today" plus a local time, so the
demo data never goes stale (interviews stay in the future when you re-seed).
"""

from __future__ import annotations

import csv
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Applicant, Application, Interview


def _local_to_utc(day_offset: int, hhmm: str, tz_name: str, now: datetime) -> datetime:
    tz = ZoneInfo(tz_name)
    local_date = now.astimezone(tz).date() + timedelta(days=day_offset)
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime.combine(local_date, time(hour, minute), tzinfo=tz).astimezone(ZoneInfo("UTC"))


def reset_and_seed(engine: Engine, csv_path: Path, tz_name: str, now: datetime) -> int:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    count = 0
    with Session(engine) as session, csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            applicant = Applicant(
                application_id=row["application_id"].strip().upper(),
                full_name=row["full_name"].strip(),
                registered_email=row["registered_email"].strip(),
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

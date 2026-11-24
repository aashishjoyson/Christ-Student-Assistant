"""ORM models. Applicant tables hold SYNTHETIC demo data only (is_synthetic=True)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime
from app.domain.clock import utcnow


class Applicant(Base):
    __tablename__ = "applicants"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    registered_email: Mapped[str] = mapped_column(String(254))
    programme: Mapped[str] = mapped_column(String(120))
    is_synthetic: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    application: Mapped[Application | None] = relationship(back_populates="applicant", uselist=False)
    interviews: Mapped[list[Interview]] = relationship(back_populates="applicant")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id"), unique=True)
    status: Mapped[str] = mapped_column(String(32))
    status_updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    notes: Mapped[str] = mapped_column(Text, default="")  # non-sensitive demo notes only

    applicant: Mapped[Applicant] = relationship(back_populates="application")


class Interview(Base):
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime)
    mode: Mapped[str] = mapped_column(String(16))  # "online" | "in_person"
    location_or_meeting_link: Mapped[str] = mapped_column(String(300))
    interviewer_label: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16))  # scheduled | rescheduled | completed | cancelled
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    applicant: Mapped[Applicant] = relationship(back_populates="interviews")


class NotificationEvent(Base):
    """Audit row for every resend attempt. idempotency_key is UNIQUE (one send per cooldown window)."""

    __tablename__ = "notification_events"
    __table_args__ = (Index("ix_notification_interview_created", "interview_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id"), index=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"))
    event_type: Mapped[str] = mapped_column(String(32), default="interview_resend")
    recipient_email: Mapped[str] = mapped_column(String(254))  # copied from applicants row, never user input
    status: Mapped[str] = mapped_column(String(16))  # pending | sent | simulated | failed
    provider: Mapped[str] = mapped_column(String(32))
    provider_message_id: Mapped[str | None] = mapped_column(String(200), default=None)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    request_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)


class IngestedFile(Base):
    """One row per source file (Drive or local folder). Used from Phase 2 onwards."""

    __tablename__ = "ingested_files"
    __table_args__ = (UniqueConstraint("source", "source_file_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))  # "drive" | "local"
    source_file_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(300))
    mime_type: Mapped[str] = mapped_column(String(120), default="")
    source_url: Mapped[str | None] = mapped_column(String(500), default=None)
    modified_time: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    remote_checksum: Mapped[str | None] = mapped_column(String(128), default=None)  # Drive md5Checksum/version
    content_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    active_version: Mapped[str | None] = mapped_column(String(32), default=None)  # chunk version in Chroma
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|indexed|failed|unsupported|deleted
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    indexed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    trigger: Mapped[str] = mapped_column(String(16))  # "manual" | "poll"
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|succeeded|partial|failed
    files_seen: Mapped[int] = mapped_column(Integer, default=0)
    files_indexed: Mapped[int] = mapped_column(Integer, default=0)
    files_skipped: Mapped[int] = mapped_column(Integer, default=0)
    files_failed: Mapped[int] = mapped_column(Integer, default=0)
    files_deleted: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)


class ConversationHistory(Base):
    """Opt-in memory of a conversation (CHAT_HISTORY_PERSIST). The turns are the ones the graph already keeps for the model: applicant-service
    answers are a placeholder, emails and secret-looking values are masked. Deleted after CHAT_HISTORY_RETENTION_DAYS."""

    __tablename__ = "conversation_history"

    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    turns: Mapped[str] = mapped_column(Text)  # JSON list of {"role", "content"}
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Feedback(Base):
    """A thumbs up/down on one answer. Keyed by the answer's message id (the same id the trace log uses). No message text, no identity."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    rating: Mapped[str] = mapped_column(String(4))  # "up" | "down"
    reason: Mapped[str | None] = mapped_column(String(24), default=None)  # a fixed code, only with "down"; never free text
    model_mode: Mapped[str | None] = mapped_column(String(16), default=None)  # direct | rag | rag_peft
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


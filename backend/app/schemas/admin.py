from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IngestedFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    source_file_id: str
    name: str
    mime_type: str
    status: str
    chunk_count: int
    modified_time: datetime | None
    indexed_at: datetime | None
    last_error: str | None


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    files_seen: int
    files_indexed: int
    files_skipped: int
    files_failed: int
    files_deleted: int
    error: str | None


class IngestionStatusResponse(BaseModel):
    drive_configured: bool
    poll_enabled: bool
    poll_interval_seconds: int
    last_run: SyncRunOut | None
    files: list[IngestedFileOut]
    counts: dict[str, int]

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
    local_docs_folder: str | None = None  # folder NAME only, never the full path
    retriever: dict[str, object] | None = None
    drive_ready: bool = False  # Drive is configured AND its credentials loaded
    drive_error: str | None = None  # why Drive is unavailable (safe text: no credentials, no file contents)
    pollers: list[dict[str, object]] = []  # automatic ingestion: last/next run, status, failures
    seconds_since_last_success: int | None = None  # index freshness: age of the last successful sync


class SyncResultOut(BaseModel):
    """Result of POST /api/admin/local/sync."""

    run_id: int
    status: str
    files_seen: int
    files_indexed: int
    files_skipped: int
    files_failed: int
    files_deleted: int
    files_unsupported: int
    embed_calls: int
    embed_tokens: int
    est_embedding_cost_usd: float | None
    error: str | None

"""Admin endpoints (development only, X-Admin-Key). Local-folder sync is Phase 2; Drive sync arrives in Phase 3."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import get_container, require_admin
from app.container import AppContainer
from app.db.models import IngestedFile, SyncRun
from app.rag.ingest import IngestionService, SyncAlreadyRunning, estimate_embedding_cost
from app.schemas.admin import IngestedFileOut, IngestionStatusResponse, SyncResultOut, SyncRunOut

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _status(container: AppContainer) -> IngestionStatusResponse:
    s = container.settings
    with container.session_factory() as session:
        files = session.execute(select(IngestedFile).order_by(IngestedFile.name)).scalars().all()
        last_run = session.execute(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1)).scalar_one_or_none()
        file_rows = [IngestedFileOut.model_validate(f) for f in files]
        run_row = SyncRunOut.model_validate(last_run) if last_run else None
        ok_run = session.execute(select(SyncRun).where(SyncRun.status.in_(("succeeded", "partial")), SyncRun.finished_at.is_not(None))
                                 .order_by(SyncRun.finished_at.desc()).limit(1)).scalar_one_or_none()
        age = int((datetime.now(UTC) - ok_run.finished_at).total_seconds()) if ok_run and ok_run.finished_at else None
    return IngestionStatusResponse(
        drive_configured=bool(s.google_drive_folder_id),
        poll_enabled=s.drive_poll_enabled,
        poll_interval_seconds=s.drive_sync_interval_seconds,
        last_run=run_row,
        files=file_rows,
        counts=dict(Counter(f.status for f in file_rows)),
        local_docs_folder=s.local_docs_dir.name,
        retriever=container.deps.retriever.describe(),
        drive_ready=container.drive_ingestion is not None,
        drive_error=container.drive_error,
        pollers=[p.describe() for p in container.pollers],
        seconds_since_last_success=age,
    )


@router.get("/drive/status", response_model=IngestionStatusResponse)
def drive_status(container: AppContainer = Depends(get_container)) -> IngestionStatusResponse:
    return _status(container)


@router.get("/local/status", response_model=IngestionStatusResponse)
def local_status(container: AppContainer = Depends(get_container)) -> IngestionStatusResponse:
    return _status(container)


def _run_sync(service: IngestionService | None, unavailable: str, model: str) -> SyncResultOut:
    if service is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, unavailable)
    try:
        r = service.sync("manual")
    except SyncAlreadyRunning as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "A sync is already running.") from exc
    return SyncResultOut(
        run_id=r.run_id, status=r.status, files_seen=r.files_seen, files_indexed=r.files_indexed,
        files_skipped=r.files_skipped, files_failed=r.files_failed, files_deleted=r.files_deleted,
        files_unsupported=r.files_unsupported, embed_calls=r.embed_calls, embed_tokens=r.embed_tokens,
        est_embedding_cost_usd=estimate_embedding_cost(model, r.embed_tokens), error=r.error,
    )


@router.post("/local/sync", response_model=SyncResultOut)
def local_sync(container: AppContainer = Depends(get_container)) -> SyncResultOut:
    """Index the local documents folder now (blocking; one sync at a time). Needs OPENAI_API_KEY for embeddings."""
    return _run_sync(container.ingestion, "Indexing needs OPENAI_API_KEY (used for embeddings).",
                     container.settings.openai_embedding_model)


@router.post("/drive/sync", response_model=SyncResultOut)
def drive_sync(container: AppContainer = Depends(get_container)) -> SyncResultOut:
    """Sync the Google Drive folder now (blocking; one sync at a time, shared with the automatic poller)."""
    reason = container.drive_error or "Google Drive is not configured (GOOGLE_DRIVE_FOLDER_ID and the service-account key; see docs/SETUP_DRIVE.md)."
    return _run_sync(container.drive_ingestion, reason, container.settings.openai_embedding_model)

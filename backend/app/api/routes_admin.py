"""Admin endpoints (development only, X-Admin-Key). Drive sync itself arrives in Phase 3."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import get_container, require_admin
from app.container import AppContainer
from app.db.models import IngestedFile, SyncRun
from app.schemas.admin import IngestedFileOut, IngestionStatusResponse, SyncRunOut

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/drive/status", response_model=IngestionStatusResponse)
def drive_status(container: AppContainer = Depends(get_container)) -> IngestionStatusResponse:
    s = container.settings
    with container.session_factory() as session:
        files = session.execute(select(IngestedFile).order_by(IngestedFile.name)).scalars().all()
        last_run = session.execute(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1)).scalar_one_or_none()
        file_rows = [IngestedFileOut.model_validate(f) for f in files]
        run_row = SyncRunOut.model_validate(last_run) if last_run else None
    return IngestionStatusResponse(
        drive_configured=bool(s.google_drive_folder_id),
        poll_enabled=s.drive_poll_enabled,
        poll_interval_seconds=s.drive_sync_interval_seconds,
        last_run=run_row,
        files=file_rows,
        counts=dict(Counter(f.status for f in file_rows)),
    )


@router.post("/drive/sync", status_code=status.HTTP_202_ACCEPTED)
def drive_sync() -> dict[str, str]:
    # Phase 3: run DriveSyncService.sync(trigger="manual") with a single-flight lock and return the SyncRun.
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Google Drive sync is implemented in Phase 3.")

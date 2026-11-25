"""The live flow dashboard's data (admin key required): the event stream, recent events, the map's boxes, and what Evidently said."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import get_container, require_admin
from app.container import AppContainer
from app.core.flow import SERVICES
from app.services import evidently_summary

router = APIRouter(prefix="/api/admin/flow", tags=["flow"], dependencies=[Depends(require_admin)])

POLL_SECONDS = 0.2
HEARTBEAT_SECONDS = 15.0


@router.get("/services")
def services() -> dict[str, Any]:
    """Every box on the maps with its group and one-sentence role."""
    return {"services": SERVICES}


@router.get("/recent")
def recent(since: int = Query(0, ge=0), limit: int = Query(300, ge=1, le=1000), container: AppContainer = Depends(get_container)) -> dict[str, Any]:
    bus = container.flow
    if bus is None:
        return {"enabled": False, "last_seq": 0, "events": []}
    return {"enabled": True, "last_seq": bus.last_seq, "events": [e.as_dict() for e in bus.since(since, limit)]}


@router.get("/stream", responses={200: {"content": {"text/event-stream": {}}}})
async def stream(request: Request, since: int | None = Query(None, ge=0), max_seconds: float = Query(3600, gt=0, le=86400),
                 container: AppContainer = Depends(get_container)) -> StreamingResponse:
    """Server-Sent Events, one `flow` event per step as it happens. Without `since`, only new events are sent (fetch /recent for history).
    The stream ends after `max_seconds`; the dashboard simply reconnects."""
    bus = container.flow
    if bus is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Flow events are switched off (FLOW_EVENTS_ENABLED=false).")

    async def frames() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        cursor = bus.last_seq if since is None else since
        deadline = loop.time() + max_seconds
        beat = loop.time()
        yield ": connected\n\n"
        while loop.time() < deadline and not await request.is_disconnected():
            events = bus.since(cursor, 200)
            for event in events:
                cursor = event.seq
                yield f"id: {event.seq}\nevent: flow\ndata: {json.dumps(event.as_dict(), ensure_ascii=False)}\n\n"
            if not events and loop.time() - beat > HEARTBEAT_SECONDS:
                beat = loop.time()
                yield ": heartbeat\n\n"
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(frames(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@router.get("/evidently")
def evidently(container: AppContainer = Depends(get_container)) -> dict[str, Any]:
    run = evidently_summary.latest_run(container.settings.eval_dir)
    return evidently_summary.summarize(run) if run else {"available": False}


@router.get("/evidently/report")
def evidently_report(container: AppContainer = Depends(get_container)) -> FileResponse:
    """The full Evidently HTML report of the latest run (a few MB). The dashboard fetches it with the admin key and opens it in a new tab."""
    run = evidently_summary.latest_run(container.settings.eval_dir)
    html = evidently_summary.report_html(run) if run else None
    if html is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Evidently report yet: run scripts/run_evaluation.py --evidently.")
    return FileResponse(html, media_type="text/html")

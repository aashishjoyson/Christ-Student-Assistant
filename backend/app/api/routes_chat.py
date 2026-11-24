from __future__ import annotations

import json
from collections.abc import Iterator
from itertools import chain
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import get_container
from app.container import AppContainer
from app.schemas.chat import ChatRequest, ChatResponse, ErrorResponse

router = APIRouter(prefix="/api", tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
def chat(
    request: ChatRequest,
    container: AppContainer = Depends(get_container),
    x_applicant_session: str | None = Header(default=None),
) -> ChatResponse:
    # Sync def: FastAPI runs it in a worker thread; the graph and SDK clients are synchronous.
    return container.chat_service.handle(request, x_applicant_session)


def _sse(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    """Server-Sent Events framing: one `event:` name and one JSON `data:` line per event."""
    for event in events:
        payload = {k: v for k, v in event.items() if k != "type"}
        yield f"event: {event['type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat/stream", responses={200: {"content": {"text/event-stream": {}}}, 502: {"model": ErrorResponse},
                                        503: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
def chat_stream(
    request: ChatRequest,
    container: AppContainer = Depends(get_container),
    x_applicant_session: str | None = Header(default=None),
) -> Any:
    """Same turn as POST /api/chat, delivered as Server-Sent Events: start -> delta* -> final (or error).

    A failure BEFORE any text (model not configured, provider auth/rate limit) is returned as an ordinary HTTP error with the
    same JSON shape as /api/chat; a failure after text has started ends the stream with an `error` event."""
    events = container.chat_service.stream(request, x_applicant_session)
    first = next(events, None)
    if first is None or first["type"] == "error":
        err = first or {"code": "internal_error", "message": "No response.", "http_status": 500}
        return JSONResponse(status_code=int(err.get("http_status", 502)),
                            content={"error": {"code": err["code"], "message": err["message"]}})
    return StreamingResponse(
        _sse(chain([first], events)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )

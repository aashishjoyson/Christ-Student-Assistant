from __future__ import annotations

import json
from collections.abc import Iterator
from itertools import chain
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import get_container
from app.container import AppContainer
from app.domain.clock import utcnow
from app.schemas.chat import ChatRequest, ChatResponse, ErrorResponse
from app.services.chat_service import ChatError

router = APIRouter(prefix="/api", tags=["chat"])


def limit_chat(request: Request, container: AppContainer = Depends(get_container)) -> None:
    """Per-client message limit. The error has the same shape as every other chat error, so the widget shows the message as it is."""
    client = request.client.host if request.client else "unknown"
    if not container.chat_limiter.hit(f"ip:{client}", utcnow()):
        raise ChatError("rate_limited", "You are sending messages very quickly. Please wait a moment and try again.", 429)


@router.post(
    "/chat",
    dependencies=[Depends(limit_chat)],
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


@router.delete("/chat/{conversation_id}")
def forget_conversation(conversation_id: UUID, container: AppContainer = Depends(get_container)) -> dict[str, bool]:
    """Forget a conversation: its stored turns (when persistent memory is on) and the in-memory copy. The id is an unguessable UUID the
    browser already holds; deleting an unknown id is not an error."""
    return {"deleted": container.chat_service.forget(conversation_id)}


def _sse(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    """Server-Sent Events framing: one `event:` name and one JSON `data:` line per event."""
    for event in events:
        payload = {k: v for k, v in event.items() if k != "type"}
        yield f"event: {event['type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat/stream", dependencies=[Depends(limit_chat)], responses={200: {"content": {"text/event-stream": {}}}, 502: {"model": ErrorResponse},
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

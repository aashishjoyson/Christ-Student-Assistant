"""Thumbs up/down on an answer. Public like the chat itself; rate limited per client; stores a rating and a fixed reason code, never text."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_container
from app.container import AppContainer
from app.db.repositories.feedback import upsert_feedback
from app.domain.clock import utcnow
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

router = APIRouter(prefix="/api", tags=["feedback"])


@router.post("/feedback", response_model=FeedbackResponse)
def give_feedback(body: FeedbackRequest, request: Request, container: AppContainer = Depends(get_container)) -> FeedbackResponse:
    now = utcnow()
    client_ip = request.client.host if request.client else "unknown"
    if not container.feedback_limiter.hit(f"ip:{client_ip}", now):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many ratings. Please wait a moment.")
    with container.session_factory() as session:
        created = upsert_feedback(session, body.message_id, body.rating, body.reason, body.model_mode, now)
    return FeedbackResponse(status="recorded" if created else "updated")

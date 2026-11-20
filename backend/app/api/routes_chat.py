from __future__ import annotations

from fastapi import APIRouter, Depends, Header

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

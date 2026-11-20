"""FastAPI entry point: `uvicorn app.main:app --reload` (run from backend/)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api import routes_admin, routes_applicant, routes_chat, routes_health
from app.container import AppContainer, build_container
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.chat_service import ChatError


def create_app(container: AppContainer | None = None) -> FastAPI:
    settings = container.settings if container else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        app.state.container = container or build_container(settings)
        # Phase 3: start the Drive poller here when DRIVE_POLL_ENABLED=true (single-flight lock).
        yield

    app = FastAPI(title="CU Student Helpdesk AI (prototype)", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Applicant-Session", "X-Admin-Key"],
    )

    @app.exception_handler(ChatError)
    async def _chat_error(_: Request, exc: ChatError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content={"error": {"code": exc.code, "message": exc.message}})

    for module in (routes_health, routes_chat, routes_applicant, routes_admin):
        app.include_router(module.router)
    return app


app = create_app()

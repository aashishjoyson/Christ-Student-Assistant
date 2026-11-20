"""Composition root: the only place where concrete implementations are chosen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.rate_limit import SlidingWindowLimiter
from app.db.session import init_db, make_engine, make_session_factory
from app.graph.builder import build_graph
from app.graph.deps import GraphDeps
from app.llm.factory import build_model3_client, build_primary_client
from app.rag.base import NullRetriever, Retriever
from app.services.chat_service import ChatService
from app.services.email.factory import build_email_provider
from app.services.tracing import TraceRecorder


@dataclass
class AppContainer:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    deps: GraphDeps
    graph: Any
    chat_service: ChatService
    verify_limiter: SlidingWindowLimiter


def build_retriever(settings: Settings) -> Retriever:
    # Phase 2 replaces this with ChromaRetriever(settings) once ingestion exists.
    return NullRetriever()


def build_container(settings: Settings, deps_override: GraphDeps | None = None) -> AppContainer:
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    deps = deps_override or GraphDeps(
        settings=settings,
        session_factory=session_factory,
        primary_llm=build_primary_client(settings),
        model3_llm=build_model3_client(settings),
        retriever=build_retriever(settings),
        email_provider=build_email_provider(settings),
    )
    graph = build_graph(deps)
    tracer = TraceRecorder(settings.trace_dir, settings.trace_include_text)
    return AppContainer(
        settings=settings,
        engine=engine,
        session_factory=deps.session_factory,
        deps=deps,
        graph=graph,
        chat_service=ChatService(graph, tracer),
        verify_limiter=SlidingWindowLimiter(
            settings.verify_max_attempts, timedelta(minutes=settings.verify_window_minutes)
        ),
    )

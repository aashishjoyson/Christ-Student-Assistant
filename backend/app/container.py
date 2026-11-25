"""Composition root: the only place where concrete implementations are chosen."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import flow
from app.core.config import Settings
from app.core.flow import FlowBus
from app.core.rate_limit import SlidingWindowLimiter
from app.db.session import init_db, make_engine, make_session_factory
from app.graph.builder import build_graph
from app.graph.deps import GraphDeps
from app.llm.factory import build_model3_client, build_primary_client
from app.rag.base import NullRetriever, Retriever
from app.rag.embeddings import OpenAIEmbedder
from app.rag.ingest import IngestionService
from app.rag.poller import IngestionPoller
from app.rag.retriever import ChromaRetriever
from app.rag.sources.google_drive import DriveError, GoogleDriveSource, build_drive_service
from app.rag.sources.local_folder import LocalFolderSource
from app.rag.vector_store import ChromaStore
from app.services.chat_service import ChatService
from app.services.email.factory import build_email_provider
from app.services.history_store import HistoryStore
from app.services.tracing import TraceRecorder

log = logging.getLogger("container")


@dataclass
class AppContainer:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    deps: GraphDeps
    graph: Any
    chat_service: ChatService
    verify_limiter: SlidingWindowLimiter
    feedback_limiter: SlidingWindowLimiter
    chat_limiter: SlidingWindowLimiter
    ingestion: IngestionService | None = None  # local folder; None when embeddings are not configured
    drive_ingestion: IngestionService | None = None  # Google Drive; None when not configured or its credentials are unusable
    drive_error: str | None = None  # why Drive is unavailable (safe to show: no credentials, no file contents)
    pollers: list[IngestionPoller] = field(default_factory=list)  # started by the app lifespan
    flow: FlowBus | None = None  # live events for the #/flow dashboard (None = switched off)


@dataclass
class RagParts:
    retriever: Retriever
    local: IngestionService | None = None
    drive: IngestionService | None = None
    drive_error: str | None = None
    pollers: list[IngestionPoller] = field(default_factory=list)


def build_rag(settings: Settings, session_factory: sessionmaker[Session]) -> RagParts:
    """Retriever + ingestion share one embedder, one Chroma store and one lock. Without an OpenAI key (embeddings) there is no
    RAG: Models 2/3 then say honestly that no documents are indexed. A collection built with another embedding model raises.
    Drive problems (bad key, no folder) never stop the app from starting: they are reported in the admin status."""
    api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if not api_key:
        return RagParts(NullRetriever())
    embedder = OpenAIEmbedder(api_key, settings.openai_embedding_model, timeout=settings.llm_timeout_seconds,
                              max_retries=settings.llm_max_retries)
    store = ChromaStore(settings.chroma_persist_dir, settings.chroma_collection, settings.openai_embedding_model)
    lock = threading.Lock()  # one writer at a time across the local and Drive services
    common: dict[str, Any] = {"chunk_size": settings.rag_chunk_size, "chunk_overlap": settings.rag_chunk_overlap, "lock": lock}
    local = IngestionService(LocalFolderSource(settings.local_docs_dir, include_synthetic=settings.local_docs_include_synthetic),
                             embedder, store, session_factory, **common)
    retriever = ChromaRetriever(embedder, store, settings.rag_lexical_weight, settings.rag_candidate_pool)
    parts = RagParts(retriever, local=local)
    if settings.google_drive_folder_id:
        try:
            service = build_drive_service(settings.google_drive_auth_mode, settings.google_drive_credentials_file,
                                          settings.google_drive_token_file)
            parts.drive = IngestionService(GoogleDriveSource(settings.google_drive_folder_id, service), embedder, store,
                                           session_factory, **common)
            if settings.drive_poll_enabled:
                parts.pollers.append(IngestionPoller(parts.drive, settings.drive_sync_interval_seconds, name="drive"))
        except DriveError as exc:
            parts.drive_error = str(exc)
            log.warning("Google Drive is not available: %s", exc)
    return parts


def build_container(
    settings: Settings, deps_override: GraphDeps | None = None, ingestion_override: IngestionService | None = None,
    drive_ingestion_override: IngestionService | None = None, pollers_override: list[IngestionPoller] | None = None,
) -> AppContainer:
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    local, drive, drive_error, pollers = ingestion_override, drive_ingestion_override, None, list(pollers_override or [])
    if deps_override is None:
        parts = build_rag(settings, session_factory)
        local, drive = local or parts.local, drive or parts.drive
        drive_error, pollers = parts.drive_error, pollers or parts.pollers
        deps = GraphDeps(
            settings=settings,
            session_factory=session_factory,
            primary_llm=build_primary_client(settings),
            model3_llm=build_model3_client(settings),
            retriever=parts.retriever,
            email_provider=build_email_provider(settings),
        )
    else:
        deps = deps_override
    bus = FlowBus(settings.flow_buffer_events) if settings.flow_events_enabled else None
    flow.install(bus)
    graph = build_graph(deps)
    tracer = TraceRecorder(settings.trace_dir, settings.trace_include_text)
    return AppContainer(
        settings=settings,
        engine=engine,
        session_factory=deps.session_factory,
        deps=deps,
        graph=graph,
        chat_service=ChatService(graph, tracer, HistoryStore(deps.session_factory) if settings.chat_history_persist else None),
        verify_limiter=SlidingWindowLimiter(
            settings.verify_max_attempts, timedelta(minutes=settings.verify_window_minutes)
        ),
        chat_limiter=SlidingWindowLimiter(settings.chat_rate_limit_per_minute, timedelta(minutes=1)),
        feedback_limiter=SlidingWindowLimiter(60, timedelta(minutes=10)),  # ratings per client; a thumb is cheap, a flood is not
        ingestion=local,
        drive_ingestion=drive,
        drive_error=drive_error,
        pollers=pollers,
        flow=bus,
    )

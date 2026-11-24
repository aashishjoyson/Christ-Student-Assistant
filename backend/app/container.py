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
from app.rag.embeddings import OpenAIEmbedder
from app.rag.ingest import IngestionService
from app.rag.retriever import ChromaRetriever
from app.rag.sources.local_folder import LocalFolderSource
from app.rag.vector_store import ChromaStore
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
    ingestion: IngestionService | None = None  # None when embeddings are not configured


def build_rag(settings: Settings, session_factory: sessionmaker[Session]) -> tuple[Retriever, IngestionService | None]:
    """Retriever + ingestion share one embedder and one Chroma store. Without an OpenAI key (embeddings) there is no RAG:
    Models 2/3 then say honestly that no documents are indexed. A collection built with another embedding model raises."""
    api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if not api_key:
        return NullRetriever(), None
    embedder = OpenAIEmbedder(api_key, settings.openai_embedding_model, timeout=settings.llm_timeout_seconds,
                              max_retries=settings.llm_max_retries)
    store = ChromaStore(settings.chroma_persist_dir, settings.chroma_collection, settings.openai_embedding_model)
    source = LocalFolderSource(settings.local_docs_dir, include_synthetic=settings.local_docs_include_synthetic)
    ingestion = IngestionService(source, embedder, store, session_factory,
                                 chunk_size=settings.rag_chunk_size, chunk_overlap=settings.rag_chunk_overlap)
    return ChromaRetriever(embedder, store), ingestion


def build_container(
    settings: Settings, deps_override: GraphDeps | None = None, ingestion_override: IngestionService | None = None
) -> AppContainer:
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    ingestion = ingestion_override
    if deps_override is None:
        retriever, built_ingestion = build_rag(settings, session_factory)
        ingestion = ingestion or built_ingestion
        deps = GraphDeps(
            settings=settings,
            session_factory=session_factory,
            primary_llm=build_primary_client(settings),
            model3_llm=build_model3_client(settings),
            retriever=retriever,
            email_provider=build_email_provider(settings),
        )
    else:
        deps = deps_override
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
        ingestion=ingestion,
    )

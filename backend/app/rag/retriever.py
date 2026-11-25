"""Chroma-backed Retriever: embeds the query, queries the store, returns RetrievedChunk with citation metadata."""

from __future__ import annotations

from app.core import flow
from app.domain.documents import RetrievedChunk
from app.rag.embeddings import Embedder
from app.rag.rerank import rerank
from app.rag.vector_store import ChromaStore


class ChromaRetriever:
    """lexical_weight > 0 turns on re-ranking: the store returns `candidate_pool` passages by meaning, and the best `top_k` are chosen after
    rewarding passages that contain the query's rare words (see app/rag/rerank.py). 0 keeps the plain vector order."""

    def __init__(self, embedder: Embedder, store: ChromaStore, lexical_weight: float = 0.0, candidate_pool: int = 40) -> None:
        self._embedder = embedder
        self._store = store
        self._lexical_weight = lexical_weight
        self._pool = candidate_pool

    @property
    def ready(self) -> bool:
        return self._store.count() > 0  # evaluated on every call, so a sync makes it ready without a restart

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        with flow.span("embed_query", "embedder", "Turned the question into a vector", model=self._embedder.model):
            vector = self._embedder.embed([query]).vectors[0]
        wanted = max(top_k, self._pool) if self._lexical_weight > 0 else top_k
        with flow.span("vector_search", "chroma", "Searched the index by meaning", wanted=wanted) as info:
            hits = list(self._store.query(vector, wanted))
            info["candidates"] = len(hits)
        chunks = [
            RetrievedChunk(
                chunk_id=hit.id,
                text=hit.text,
                source_name=str(hit.metadata.get("source_name", "")),
                source_id=str(hit.metadata.get("source_file_id", "")),
                page=hit.metadata.get("page"),
                section=hit.metadata.get("section"),
                source_url=hit.metadata.get("source_url"),
                distance=hit.distance,
            )
            for hit in hits
        ]
        if self._lexical_weight > 0:
            with flow.span("rerank", "rerank", "Re-ranked by the rare words in the question", keep=top_k, lexical_weight=self._lexical_weight):
                chunks = rerank(query, chunks, top_k, self._lexical_weight)
        return chunks

    def describe(self) -> dict[str, object]:
        return {"backend": "chroma", "ready": self.ready, "chunks": self._store.count(),
                "embedding_model": self._embedder.model, "collection": self._store.collection}

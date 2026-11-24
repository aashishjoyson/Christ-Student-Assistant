"""Chroma-backed Retriever: embeds the query, queries the store, returns RetrievedChunk with citation metadata."""

from __future__ import annotations

from app.domain.documents import RetrievedChunk
from app.rag.embeddings import Embedder
from app.rag.vector_store import ChromaStore


class ChromaRetriever:
    def __init__(self, embedder: Embedder, store: ChromaStore) -> None:
        self._embedder = embedder
        self._store = store

    @property
    def ready(self) -> bool:
        return self._store.count() > 0  # evaluated on every call, so a sync makes it ready without a restart

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        vector = self._embedder.embed([query]).vectors[0]
        return [
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
            for hit in self._store.query(vector, top_k)
        ]

    def describe(self) -> dict[str, object]:
        return {"backend": "chroma", "ready": self.ready, "chunks": self._store.count(),
                "embedding_model": self._embedder.model, "collection": self._store.collection}

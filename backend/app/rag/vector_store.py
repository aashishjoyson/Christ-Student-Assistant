"""Persistent Chroma collection (cosine distance). Embeddings are computed by our code and passed in explicitly, so the
embedding model is visible and mockable. The collection records the model; a different model needs a new collection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class EmbeddingModelMismatch(Exception):
    """The persisted collection was built with a different embedding model."""


@dataclass(frozen=True)
class Hit:
    id: str
    text: str
    metadata: dict[str, Any]
    distance: float


class ChromaStore:
    def __init__(self, persist_dir: Path, collection: str, embedding_model: str, client: Any = None) -> None:
        import chromadb

        if client is None:
            persist_dir.mkdir(parents=True, exist_ok=True)
            # Telemetry off: this project indexes real university documents and must not phone home.
            client = chromadb.PersistentClient(path=str(persist_dir), settings=chromadb.config.Settings(anonymized_telemetry=False))
        self._client = client
        self._col = client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": "cosine", "embedding_model": embedding_model}
        )
        stored = (self._col.metadata or {}).get("embedding_model")
        if stored and stored != embedding_model:
            raise EmbeddingModelMismatch(
                f"collection {collection!r} was built with {stored!r} but the configured model is {embedding_model!r}. "
                "Use a new CHROMA_COLLECTION name (or delete storage/chroma) and re-index."
            )
        self.embedding_model = embedding_model
        self.collection = collection

    def count(self) -> int:
        return int(self._col.count())

    def upsert(self, ids: Sequence[str], vectors: Sequence[Sequence[float]], documents: Sequence[str],
               metadatas: Sequence[dict[str, Any]]) -> None:
        step = 500
        for start in range(0, len(ids), step):
            end = start + step
            self._col.upsert(ids=list(ids[start:end]), embeddings=[list(v) for v in vectors[start:end]],
                             documents=list(documents[start:end]), metadatas=list(metadatas[start:end]))

    def delete_other_versions(self, source_file_id: str, keep_version: str) -> None:
        self._col.delete(where={"$and": [{"source_file_id": {"$eq": source_file_id}}, {"version": {"$ne": keep_version}}]})

    def delete_version(self, source_file_id: str, version: str) -> None:
        self._col.delete(where={"$and": [{"source_file_id": {"$eq": source_file_id}}, {"version": {"$eq": version}}]})

    def delete_file(self, source_file_id: str) -> None:
        self._col.delete(where={"source_file_id": {"$eq": source_file_id}})

    def ids_for_file(self, source_file_id: str) -> list[str]:
        return sorted(self._col.get(where={"source_file_id": {"$eq": source_file_id}}, include=[])["ids"])

    def query(self, vector: Sequence[float], k: int) -> list[Hit]:
        total = self.count()
        if total == 0 or k <= 0:
            return []
        result = self._col.query(query_embeddings=[list(vector)], n_results=min(k, total),
                                 include=["documents", "metadatas", "distances"])
        return [
            Hit(id=i, text=d or "", metadata=dict(m or {}), distance=float(dist))
            for i, d, m, dist in zip(result["ids"][0], result["documents"][0], result["metadatas"][0],
                                     result["distances"][0], strict=True)
        ]

"""Retriever and document-source interfaces.

Phase 2 adds ChromaRetriever (OpenAI embeddings + persistent Chroma) and a LocalFolderSource.
Phase 3 adds GoogleDriveSource. The graph depends only on the Retriever protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.documents import RetrievedChunk


class Retriever(Protocol):
    @property
    def ready(self) -> bool:
        """True once at least one document is indexed."""
        ...

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]: ...

    def describe(self) -> dict[str, object]: ...


class NullRetriever:
    """Honest placeholder until ingestion exists: reports not-ready and returns nothing.

    Model 2/3 then answer "no documents indexed" instead of pretending to be grounded.
    """

    @property
    def ready(self) -> bool:
        return False

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        return []

    def describe(self) -> dict[str, object]:
        return {"backend": "none", "ready": False, "note": "Document ingestion not implemented yet (Phase 2)."}


@dataclass(frozen=True)
class SourceFile:
    """A file listed by a DocumentSource (local folder or Google Drive)."""

    source_file_id: str
    name: str
    mime_type: str
    modified_time: datetime | None
    remote_checksum: str | None  # Drive md5Checksum, or Drive 'version' for Google Docs
    source_url: str | None = None


class DocumentSource(Protocol):
    name: str  # "local" | "drive"

    def list_files(self) -> list[SourceFile]: ...

    def fetch(self, file: SourceFile) -> tuple[bytes, str]:
        """Return (content bytes, effective mime type). Google Docs are exported (e.g. to DOCX or text)."""
        ...

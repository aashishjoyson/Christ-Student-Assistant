"""Document data shapes shared by ingestion, retrieval, prompts and citations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSection:
    """A piece of extracted text with its location in the source file."""

    text: str
    page: int | None = None  # 1-based page number for PDFs
    section: str | None = None  # nearest heading for DOCX / Markdown
    prefix: str | None = None  # identity line repeated at the top of EVERY chunk of this section (e.g. a table row's course name)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str  # deterministic: "{source_id}:{version}:{index:04d}"
    source_id: str
    version: str
    index: int
    text: str
    page: int | None
    section: str | None


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    text: str
    source_name: str
    source_id: str
    page: int | None = None
    section: str | None = None
    source_url: str | None = None
    distance: float | None = None  # cosine distance; lower = more similar

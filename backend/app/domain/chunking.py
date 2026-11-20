"""Deterministic character-based chunking that preserves page/section metadata.

Chunks never cross section boundaries, so every chunk has one accurate
page/section for its citation. Chunk ids depend only on (source id, content
version, index), so re-syncing an unchanged file produces identical ids and
an upsert cannot create duplicates.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from app.domain.documents import Chunk, ParsedSection

_WS = re.compile(r"[ \t]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(_WS.sub(" ", line).strip() for line in text.split("\n"))
    return _MANY_NEWLINES.sub("\n\n", text).strip()


def content_version(sections: Sequence[ParsedSection]) -> str:
    """Hash of normalized content. Changes only when the text changes."""
    digest = hashlib.sha256()
    for s in sections:
        digest.update(f"{s.page}|{s.section}|{normalize_text(s.text)}\n".encode())
    return digest.hexdigest()[:16]


def _find_break(text: str, start: int, hard_end: int) -> int:
    """Prefer a paragraph, then sentence, then word boundary in the last 30% of the window."""
    if hard_end >= len(text):
        return len(text)
    window_floor = start + int((hard_end - start) * 0.7)
    for sep in ("\n\n", ". ", "? ", "! ", "\n", " "):
        pos = text.rfind(sep, window_floor, hard_end)
        if pos != -1:
            return pos + len(sep)
    return hard_end


def split_text(text: str, size: int, overlap: int) -> list[str]:
    if size <= 0:
        raise ValueError("size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("overlap must be >= 0 and smaller than size")
    text = normalize_text(text)
    if not text:
        return []
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = _find_break(text, start, start + size)
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        next_start = end - overlap
        start = next_start if next_start > start else end
    return pieces


def chunk_sections(
    source_id: str,
    sections: Sequence[ParsedSection],
    size: int = 900,
    overlap: int = 120,
) -> list[Chunk]:
    version = content_version(sections)
    chunks: list[Chunk] = []
    for section in sections:
        for piece in split_text(section.text, size, overlap):
            index = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=f"{source_id}:{version}:{index:04d}",
                    source_id=source_id,
                    version=version,
                    index=index,
                    text=piece,
                    page=section.page,
                    section=section.section,
                )
            )
    return chunks

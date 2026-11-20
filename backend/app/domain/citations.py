"""Turn [n] markers in an answer into structured citations."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.documents import RetrievedChunk

_GROUP = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass(frozen=True)
class Citation:
    index: int
    source_name: str
    page: int | None
    section: str | None
    source_url: str | None
    chunk_id: str
    cited: bool  # True if the answer explicitly referenced it


def extract_citation_indices(answer: str) -> list[int]:
    seen: list[int] = []
    for group in _GROUP.findall(answer):
        for part in group.split(","):
            n = int(part.strip())
            if n not in seen:
                seen.append(n)
    return seen


def build_citations(answer: str, chunks: Sequence[RetrievedChunk]) -> list[Citation]:
    """Cited passages first. If the model cited nothing, return retrieved passages marked cited=False."""
    valid = [i for i in extract_citation_indices(answer) if 1 <= i <= len(chunks)]
    chosen = valid or list(range(1, len(chunks) + 1))
    out: list[Citation] = []
    seen_locations: set[tuple[str, int | None, str | None]] = set()
    for i in chosen:
        c = chunks[i - 1]
        location = (c.source_name, c.page, c.section)
        if location in seen_locations:
            continue
        seen_locations.add(location)
        out.append(Citation(i, c.source_name, c.page, c.section, c.source_url, c.chunk_id, cited=bool(valid)))
    return out

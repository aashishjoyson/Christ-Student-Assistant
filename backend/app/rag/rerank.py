"""Lexical re-ranking of retrieval candidates (stdlib only).

Dense embeddings are good at meaning and poor at telling near-duplicates apart: thirty course rows that differ by one specialisation
word, or a calendar entry that shares "Session I" with an FAQ answer about MBA applications. Words that are RARE among the candidates
are exactly what separates them, so each candidate's score is lowered by the weighted share of the query's distinctive words it contains.
The reported `distance` is untouched, so the "nothing relevant" cut-off keeps its meaning.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.documents import RetrievedChunk

STOPWORDS = frozenset({
    "a", "an", "the", "of", "for", "to", "in", "on", "at", "by", "with", "and", "or", "is", "are", "was", "were", "be", "been", "do", "does",
    "did", "can", "could", "will", "would", "should", "i", "me", "my", "we", "you", "your", "it", "its", "this", "that", "these", "those",
    "what", "when", "where", "which", "who", "whom", "how", "why", "there", "their", "from", "as", "about", "into", "than", "then", "so",
    "if", "not", "no", "any", "all", "per",
})
_WORD = re.compile(r"[a-z0-9]+")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def distinctive_words(query: str) -> set[str]:
    return {w for w in words(query) if w not in STOPWORDS and (len(w) > 1 or w.isdigit())}


@dataclass(frozen=True)
class Scored:
    chunk: RetrievedChunk
    lexical: float  # 0..1, share of the query's distinctive words found in the chunk (rare words count more)
    combined: float  # cosine distance minus the lexical bonus; lower is better


def lexical_scores(query: str, texts: Sequence[str]) -> list[float]:
    wanted = distinctive_words(query)
    if not wanted or not texts:
        return [0.0] * len(texts)
    present = [set(words(t)) for t in texts]
    n = len(texts)
    weight = {w: math.log((n + 1) / (sum(w in p for p in present) + 0.5)) + 1.0 for w in wanted}
    total = sum(weight.values())
    return [round(sum(weight[w] for w in wanted if w in p) / total, 4) for p in present]


def rerank(query: str, chunks: Sequence[RetrievedChunk], top_k: int, lexical_weight: float) -> list[RetrievedChunk]:
    """Best `top_k` by (distance - lexical_weight * lexical score). weight 0 keeps the dense order. Ties keep the dense order."""
    if lexical_weight <= 0 or len(chunks) <= 1:
        return list(chunks[:top_k])
    scores = lexical_scores(query, [c.text for c in chunks])
    scored = [
        Scored(c, s, (c.distance if c.distance is not None else 1.0) - lexical_weight * s) for c, s in zip(chunks, scores, strict=True)
    ]
    scored.sort(key=lambda s: s.combined)  # sort is stable: equal scores keep the order the vector store returned
    return [s.chunk for s in scored[:top_k]]

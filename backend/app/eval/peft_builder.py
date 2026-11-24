"""Builds the Model 3 training examples from the indexed documents. The teacher model and the vector search are injected, so the whole
procedure is tested with fakes and the script (scripts/build_peft_dataset.py) wires the real ones."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domain.documents import RetrievedChunk
from app.domain.prompts import NO_EVIDENCE_ANSWER, build_rag_messages, format_context
from app.eval.peft_data import (
    answered_by_other_passages,
    build_teacher_messages,
    example_key,
    is_holdout_chunk,
    parse_teacher_reply,
    too_close_to_golden,
    validate_answerable,
)

Neighbours = Callable[[str, int], Sequence[RetrievedChunk]]  # (text, k) -> the k nearest passages to this text
Teacher = Callable[[list[dict[str, str]]], str | None]  # chat messages -> reply text (None on failure)


@dataclass(frozen=True)
class BuildConfig:
    calls: int  # teacher calls to make (each gives one answerable example, and sometimes a refusal example)
    refusal_share: float = 0.55  # chance that a call also yields a refusal example
    context_size: int = 4  # passages in each example's context (the gold one plus hard negatives)
    seed: int = 7
    min_chunk_chars: int = 80
    max_chunk_chars: int = 1400
    neighbour_pool: int = 14


@dataclass
class BuildResult:
    examples: list[dict[str, Any]] = field(default_factory=list)  # {"messages": [...], "meta": {...}}
    dropped: Counter[str] = field(default_factory=Counter)
    teacher_calls: int = 0


def usable_chunk(chunk: RetrievedChunk, cfg: BuildConfig) -> bool:
    text = chunk.text.strip()
    return cfg.min_chunk_chars <= len(text) <= cfg.max_chunk_chars and "{" not in text  # short stubs and leftover style rules teach nothing


def pick_gold_chunks(chunks: Sequence[RetrievedChunk], cfg: BuildConfig, rng: random.Random) -> list[RetrievedChunk]:
    """Round-robin over the source files, so a 1,500-row spreadsheet does not drown out a 10-page calendar."""
    by_source: dict[str, list[RetrievedChunk]] = {}
    for c in chunks:
        by_source.setdefault(c.source_name, []).append(c)
    for group in by_source.values():
        rng.shuffle(group)
    order = sorted(by_source)
    picked: list[RetrievedChunk] = []
    while len(picked) < cfg.calls and any(by_source.values()):
        for name in order:
            if by_source[name] and len(picked) < cfg.calls:
                picked.append(by_source[name].pop())
    return picked


def build_examples(
    chunks: Sequence[RetrievedChunk], golden_questions: Sequence[str], evidence_quotes: Sequence[str], cfg: BuildConfig,
    neighbours: Neighbours, teacher: Teacher,
) -> BuildResult:
    rng = random.Random(cfg.seed)  # noqa: S311 - reproducible sampling of training examples, not security
    result = BuildResult()
    seen: set[str] = set()
    pool = [c for c in chunks if usable_chunk(c, cfg)]
    result.dropped["unusable_chunk"] = len(chunks) - len(pool)
    safe = [c for c in pool if not is_holdout_chunk(c.text, evidence_quotes)]
    result.dropped["holdout_chunk"] = len(pool) - len(safe)

    def candidates(text: str, exclude: set[str], k: int) -> list[RetrievedChunk]:
        out: list[RetrievedChunk] = []
        for c in neighbours(text, cfg.neighbour_pool):
            if c.chunk_id in exclude or not usable_chunk(c, cfg) or is_holdout_chunk(c.text, evidence_quotes):
                continue
            if any(c.text.strip() == o.text.strip() for o in out):
                continue
            out.append(c)
            if len(out) == k:
                break
        return out

    for gold in pick_gold_chunks(safe, cfg, rng):
        distractors = candidates(gold.text, {gold.chunk_id}, cfg.context_size - 1)
        if len(distractors) < cfg.context_size - 1:
            result.dropped["too_few_neighbours"] += 1
            continue
        context = [gold, *distractors]
        rng.shuffle(context)
        gold_index = next(i for i, c in enumerate(context, start=1) if c.chunk_id == gold.chunk_id)

        result.teacher_calls += 1
        parsed = parse_teacher_reply(teacher(build_teacher_messages(format_context(context), gold_index)))
        if parsed is None:
            result.dropped["teacher_unparseable"] += 1
            continue
        question, answer = parsed
        reason = validate_answerable(question, answer, [c.text for c in context], NO_EVIDENCE_ANSWER)
        if reason is None and too_close_to_golden(question, golden_questions):
            reason = "too_close_to_golden_question"
        if reason is None and example_key(question) in seen:
            reason = "duplicate_question"
        if reason is not None:
            result.dropped[reason] += 1
            continue
        seen.add(example_key(question))
        meta = {"question": question, "source": gold.source_name, "gold_chunk": gold.chunk_id}
        result.examples.append({"messages": [*build_rag_messages(question, context), {"role": "assistant", "content": answer}],
                                "meta": {**meta, "kind": "answerable", "chunks": [c.chunk_id for c in context]}})

        if rng.random() < cfg.refusal_share:  # the same question, but the passages that can answer it are taken away
            nearest = candidates(question, {gold.chunk_id}, cfg.neighbour_pool)
            clean = [c for c in nearest if not answered_by_other_passages(question, answer, [c.text])][: cfg.context_size]
            if len(clean) < cfg.context_size:
                result.dropped["refusal_context_not_clean"] += 1
                continue
            rng.shuffle(clean)
            result.examples.append({"messages": [*build_rag_messages(question, clean), {"role": "assistant", "content": NO_EVIDENCE_ANSWER}],
                                    "meta": {**meta, "kind": "refusal", "chunks": [c.chunk_id for c in clean]}})
    return result

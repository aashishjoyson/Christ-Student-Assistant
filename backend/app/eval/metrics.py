"""Deterministic evaluation metrics (stdlib only). The same functions are used by the runner, the tests and the Evidently report.

Everything here is a pure function over strings and numbers: no model, no network. An LLM judge, when used at all, is a separate,
optional, capped step (see scripts/run_evaluation.py).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from app.domain.prompts import NO_EVIDENCE_ANSWER

_DASHES = re.compile(r"[-‐-―−]")
_MARKDOWN = re.compile(r"[*_`#>|]+")
_ORDINAL = re.compile(r"(?<=\d)(?:st|nd|rd|th)\b")
_DIGIT_COMMA = re.compile(r"(?<=\d),(?=\d)")
_LEADING_ZERO = re.compile(r"\b0(?=\d\b)")
_SPACES = re.compile(r"\s+")
_CITATION = re.compile(r"\[(\d{1,3})\]")

# Wording that means "the answer is not in the documents". The first is the exact sentence the system prompt demands.
_REFUSAL_MARKERS = (
    "i could not find this in the available university documents",
    "could not find this in the available",
    "couldn't find this in the available",
    "not found in the available university documents",
)


def normalize(text: str) -> str:
    """Make two phrasings of the same fact comparable: case, markdown, dashes, ordinals ("10th"), digit commas ("2,60,000"), leading zeros."""
    t = unicodedata.normalize("NFKC", text).lower().replace("’", "'")
    t = _MARKDOWN.sub(" ", t)
    t = _DASHES.sub(" ", t)
    t = _ORDINAL.sub("", t)
    t = _DIGIT_COMMA.sub("", t)
    t = _LEADING_ZERO.sub("", t)
    return _SPACES.sub(" ", t).strip()


def fact_present(answer: str, fact: str) -> bool:
    """True if the answer states the fact. `fact` may list acceptable wordings separated by '|' ("10 november|november 10").
    Matches whole words, so "5000" is not found inside "15000"."""
    haystack = normalize(answer)
    for alternative in fact.split("|"):
        needle = normalize(alternative)
        if needle and re.search(rf"(?<![\w]){re.escape(needle)}(?![\w])", haystack):
            return True
    return False


def facts_recall(answer: str, facts: Sequence[str]) -> float | None:
    """Fraction of the expected facts the answer states; None when no facts are expected (an unanswerable question)."""
    if not facts:
        return None
    return round(sum(fact_present(answer, f) for f in facts) / len(facts), 4)


def is_refusal(answer: str) -> bool:
    text = normalize(answer)
    return any(normalize(marker) in text for marker in (NO_EVIDENCE_ANSWER, *_REFUSAL_MARKERS))


def citation_indices(answer: str) -> list[int]:
    return [int(m) for m in _CITATION.findall(answer)]


def citations_valid(answer: str, available: int) -> bool:
    """Every [n] in the answer points at a passage that was actually supplied (1..available). An answer with no [n] is valid here."""
    return all(1 <= n <= available for n in citation_indices(answer))


def source_matches(name: str, expected: Iterable[str]) -> bool:
    wanted = {normalize(e) for e in expected}
    return normalize(name) in wanted


def first_hit_rank(retrieved_sources: Sequence[str], expected: Sequence[str]) -> int | None:
    """1-based rank of the first retrieved passage that comes from an expected source, or None."""
    for rank, name in enumerate(retrieved_sources, start=1):
        if source_matches(name, expected):
            return rank
    return None


def hit_at_k(rank: int | None, k: int) -> bool:
    return rank is not None and rank <= k


def reciprocal_rank(rank: int | None) -> float:
    return 0.0 if rank is None else round(1.0 / rank, 4)


def percentile(values: Sequence[float], p: float) -> float | None:
    """Linear-interpolation percentile (p in 0..100); None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p / 100
    low, high = math.floor(pos), math.ceil(pos)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (pos - low), 2)


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _rate(flags: Sequence[bool]) -> float | None:
    return round(sum(flags) / len(flags), 4) if flags else None


def score_row(row: dict[str, Any]) -> dict[str, Any]:
    """Derived per-answer metrics. `row` needs: answerable, answer, expected_facts, citations (list of {index, source_name, cited}),
    optional expected_sources, retrieved_sources, rag (bool: this mode is supposed to use the documents), error_code."""
    answer = row.get("answer") or ""
    answerable = bool(row["answerable"])
    recall = facts_recall(answer, row.get("expected_facts") or [])
    refused = is_refusal(answer)
    cited = [c["source_name"] for c in row.get("citations", []) if c.get("cited")]
    rank = first_hit_rank(row.get("retrieved_sources") or [], row.get("expected_sources") or []) if answerable else None
    return {
        "fact_recall": recall,
        "answered_correctly": bool(answerable and recall == 1.0 and not refused),
        "refused": refused,
        "false_refusal": bool(answerable and refused),  # the answer was in the documents, the system said it was not
        "correct_refusal": bool(not answerable and refused),
        "unsupported_answer": bool(not answerable and not refused),  # said something when the documents hold nothing
        "citation_hit": bool(answerable and any(source_matches(n, row.get("expected_sources") or []) for n in cited)),
        # [n] must point at a passage the model was actually given. The response only lists the cited ones (and merges repeats from the same
        # page), so the number supplied is recorded by the runner; without it the best available guess is the number of citations returned.
        "citations_valid": citations_valid(answer, row.get("passages_supplied", len(row.get("citations", [])))),
        "retrieval_rank": rank,
        "routed_academic": (row["intent"] == "academic_qa") if row.get("intent") else None,  # did the router treat it as a documents question?
    }


def summarize(rows: Sequence[dict[str, Any]], k: int = 4) -> dict[str, Any]:
    """Aggregate scored rows (each = the row dict merged with score_row output) per mode, then per category inside each mode."""
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_mode[r["mode"]].append(r)
    return {mode: _aggregate(items, k) | {"by_category": {c: _aggregate([r for r in items if r["category"] == c], k)
                                                          for c in sorted({r["category"] for r in items})}}
            for mode, items in sorted(by_mode.items())}


def _aggregate(items: Sequence[dict[str, Any]], k: int) -> dict[str, Any]:
    answerable = [r for r in items if r["answerable"]]
    unanswerable = [r for r in items if not r["answerable"]]
    ok = [r for r in items if not r.get("error_code")]
    rag_answerable = [r for r in answerable if r.get("rag")]
    ranks = [r["retrieval_rank"] for r in rag_answerable]
    has_context = [r for r in rag_answerable if r.get("evidence_in_context") is not None]
    with_evidence = [r for r in has_context if r["evidence_in_context"]]
    uses_documents = any(r.get("rag") for r in items)  # refusals are only meaningful for modes that are given documents
    latencies = [float(r["latency_ms"]) for r in ok if r.get("latency_ms") is not None]
    costs = [float(r["est_cost_usd"]) for r in ok if r.get("est_cost_usd") is not None]
    return {
        "n": len(items), "n_answerable": len(answerable), "n_unanswerable": len(unanswerable), "errors": len(items) - len(ok),
        "answer_accuracy": _rate([r["answered_correctly"] for r in answerable]),
        "fact_recall": _mean([r["fact_recall"] for r in answerable if r["fact_recall"] is not None]),
        "false_refusal_rate": _rate([r["false_refusal"] for r in answerable]) if uses_documents else None,
        "correct_refusal_rate": _rate([r["correct_refusal"] for r in unanswerable]) if uses_documents else None,
        "unsupported_answer_rate": _rate([r["unsupported_answer"] for r in unanswerable]) if uses_documents else None,
        # Where do failures come from? context_recall: the proving quote reached the model's context. accuracy_when_evidence_present:
        # of those, how many were then answered correctly (a gap here is a prompt/model/threshold problem, not a retrieval problem).
        "context_recall": _rate([bool(r["evidence_in_context"]) for r in has_context]),
        "accuracy_when_evidence_present": _rate([r["answered_correctly"] for r in with_evidence]),
        "citation_hit_rate": _rate([r["citation_hit"] for r in answerable if r.get("rag")]),
        "citations_valid_rate": _rate([r["citations_valid"] for r in items]),
        "routed_academic_rate": _rate([r["routed_academic"] for r in items if r.get("routed_academic") is not None]),
        f"retrieval_hit_at_{k}": _rate([hit_at_k(x, k) for x in ranks]),
        "retrieval_mrr": _mean([reciprocal_rank(x) for x in ranks]),
        "latency_p50_ms": percentile(latencies, 50), "latency_p95_ms": percentile(latencies, 95),
        "cost_usd_total": round(sum(costs), 6) if costs else None,
        "input_tokens_total": sum(int(r["input_tokens"]) for r in ok if r.get("input_tokens") is not None) or None,
        "output_tokens_total": sum(int(r["output_tokens"]) for r in ok if r.get("output_tokens") is not None) or None,
    }


def calibrate_threshold(answerable: Sequence[float], unanswerable: Sequence[float], current: float | None = None) -> dict[str, Any]:
    """Pick the retrieval-distance cut-off (cosine distance, lower = closer) that best separates questions the documents can answer from
    those they cannot. The rule is "best passage distance <= t means answerable"; the score is balanced accuracy (so the smaller group is
    not drowned out). With a handful of questions this is a rough guide, so the result says how much the two groups overlap."""
    if not answerable or not unanswerable:
        return {"status": "needs_both_groups", "n_answerable": len(answerable), "n_unanswerable": len(unanswerable)}

    def balanced(t: float) -> float:
        tpr = sum(d <= t for d in answerable) / len(answerable)
        tnr = sum(d > t for d in unanswerable) / len(unanswerable)
        return round((tpr + tnr) / 2, 4)

    points = sorted({*answerable, *unanswerable})
    candidates = [points[0] - 1e-6, *[(a + b) / 2 for a, b in zip(points, points[1:], strict=False)], points[-1] + 1e-6]
    best = max(candidates, key=lambda t: (balanced(t), -abs(t - current) if current is not None else 0.0))
    return {
        "status": "ok", "n_answerable": len(answerable), "n_unanswerable": len(unanswerable),
        "recommended_max_distance": round(best, 4), "balanced_accuracy_at_recommended": balanced(best),
        "current_max_distance": current, "balanced_accuracy_at_current": balanced(current) if current is not None else None,
        "answerable_distance_max": round(max(answerable), 4), "unanswerable_distance_min": round(min(unanswerable), 4),
        "groups_overlap": max(answerable) >= min(unanswerable),
    }

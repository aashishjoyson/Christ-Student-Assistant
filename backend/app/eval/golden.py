"""The golden question set: loading, validation and a fingerprint (stdlib only).

A golden case is a question a student could ask, with what a correct answer must state. Answerable cases name the source file and
carry `evidence`: short literal quotes from that file that prove the expected facts (scripts/check_golden_set.py checks them
against the real documents, so no fact is invented). Unanswerable cases carry `absent_terms`: words that must not occur in any
document, which is what makes "the documents do not say" the correct outcome.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

_FIELDS = {"id", "question", "answerable", "expected_sources", "expected_facts", "category", "evidence", "absent_terms"}


@dataclass(frozen=True)
class GoldenCase:
    id: str
    question: str
    answerable: bool
    category: str
    expected_sources: tuple[str, ...] = ()
    expected_facts: tuple[str, ...] = ()  # '|' separates acceptable wordings, see app.eval.metrics.fact_present
    evidence: tuple[str, ...] = ()
    absent_terms: tuple[str, ...] = ()


def load_golden(path: Path) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        unknown = set(raw) - _FIELDS
        if unknown:
            raise ValueError(f"{path.name} line {number}: unknown field(s) {sorted(unknown)}")
        case = GoldenCase(
            id=raw["id"], question=raw["question"].strip(), answerable=bool(raw["answerable"]), category=raw["category"],
            expected_sources=tuple(raw.get("expected_sources", [])), expected_facts=tuple(raw.get("expected_facts", [])),
            evidence=tuple(raw.get("evidence", [])), absent_terms=tuple(raw.get("absent_terms", [])),
        )
        _validate(case, path, number)
        cases.append(case)
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: duplicate ids")
    return cases


def _validate(case: GoldenCase, path: Path, number: int) -> None:
    where = f"{path.name} line {number} ({case.id})"
    if not case.question:
        raise ValueError(f"{where}: empty question")
    if case.answerable and not (case.expected_sources and case.expected_facts):
        raise ValueError(f"{where}: an answerable case needs expected_sources and expected_facts")
    if not case.answerable and (case.expected_sources or case.expected_facts):
        raise ValueError(f"{where}: an unanswerable case must not name sources or facts")


def golden_fingerprint(path: Path) -> str:
    """Hash of the file with line endings normalised, so Windows and Linux checkouts give the same value."""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()

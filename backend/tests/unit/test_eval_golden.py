"""The golden set file is part of the product: its shape is enforced, and the committed set must always load."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import REPO_ROOT
from app.eval.golden import golden_fingerprint, load_golden

REAL = REPO_ROOT / "data" / "eval" / "academic_real.jsonl"


def write(tmp_path: Path, *cases: dict) -> Path:
    path = tmp_path / "g.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in cases) + "\n", encoding="utf-8")
    return path


GOOD = {"id": "a", "question": "When?", "answerable": True, "expected_sources": ["x.pdf"], "expected_facts": ["1 july"], "category": "calendar"}
NONE = {"id": "u", "question": "Menu?", "answerable": False, "category": "unanswerable", "absent_terms": ["menu"]}


def test_the_committed_golden_set_loads_and_is_balanced() -> None:
    cases = load_golden(REAL)
    answerable = [c for c in cases if c.answerable]
    assert len(cases) >= 30 and len(answerable) >= 20 and len(cases) - len(answerable) >= 5
    assert all(c.evidence for c in answerable), "every answerable case must carry literal evidence (scripts/check_golden_set.py proves it)"
    assert all(c.absent_terms for c in cases if not c.answerable)
    assert {c.category for c in cases} >= {"calendar", "handbook", "faq", "courses", "unanswerable"}


def test_valid_cases_load(tmp_path: Path) -> None:
    cases = load_golden(write(tmp_path, GOOD, NONE))
    assert [c.id for c in cases] == ["a", "u"] and cases[0].expected_facts == ("1 july",) and cases[1].absent_terms == ("menu",)


@pytest.mark.parametrize(("case", "message"), [
    ({**GOOD, "expected_facts": []}, "needs expected_sources and expected_facts"),
    ({**GOOD, "expected_sources": []}, "needs expected_sources and expected_facts"),
    ({**NONE, "expected_facts": ["x"]}, "must not name sources or facts"),
    ({**GOOD, "question": "  "}, "empty question"),
    ({**GOOD, "expectd_facts": ["typo"]}, "unknown field"),
])
def test_malformed_cases_are_rejected_with_the_line_number(tmp_path: Path, case: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_golden(write(tmp_path, case))


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate ids"):
        load_golden(write(tmp_path, GOOD, GOOD))


def test_fingerprint_ignores_line_endings_and_changes_with_content(tmp_path: Path) -> None:
    unix, windows = tmp_path / "u.jsonl", tmp_path / "w.jsonl"
    unix.write_bytes(b'{"a": 1}\n{"b": 2}\n')
    windows.write_bytes(b'{"a": 1}\r\n{"b": 2}\r\n')
    assert golden_fingerprint(unix) == golden_fingerprint(windows)
    windows.write_bytes(b'{"a": 1}\r\n{"b": 3}\r\n')
    assert golden_fingerprint(unix) != golden_fingerprint(windows)

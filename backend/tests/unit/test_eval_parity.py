"""Phrasing / name parity (Phase 7.6): names must never change behaviour; phrasing gaps must not get worse.

The phrasing audit measures the deterministic intent rules only (no LLM). Samples are tiny and synthetic: this is an audit
harness that reports effect sizes, not a statistical proof of fairness.
Set PARITY_RESULTS_JSON=<path> to write rows for the Evidently report (scripts/evidently_report.py).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.core.config import REPO_ROOT
from app.domain.intents import classify_intent
from app.eval.parity import accuracy_by_slice, load_parity_cases, regressions

DATA = REPO_ROOT / "data" / "eval"
BASELINE = json.loads((DATA / "baselines" / "parity_intent_baseline.json").read_text(encoding="utf-8"))["slices"]
CASES = load_parity_cases(DATA / "parity_cases.jsonl")
TARGET_GAP = 0.10  # proposed gate from the PRD; calibrate after the first accepted run

NAMES = ["Aarav Sharma", "Fatima Khan", "Joseph Thomas", "Zhang Wei", "Lakshmi Iyer", "Mohammed Ali", "Gurpreet Singh",
         "Oluwaseun Adeyemi", "Maria Fernandes", "Priya Nair"]
PROGRAMMES = ["MBA", "MSc Data Science", "BCom", "PhD", "MA English"]
REQUESTS = {
    "resend_interview_email": "I have not received my interview email.",
    "interview_details": "When is my interview?",
    "applicant_status": "What is the status of my application?",
}


def _measure() -> tuple[dict[str, float], list[dict[str, str]]]:
    rows = []
    for c in CASES:
        got = classify_intent(c.message).intent.value
        rows.append({"id": c.id, "slice": c.slice, "family": c.family, "correct": "yes" if got == c.expected_intent else "no",
                     "expected": c.expected_intent, "got": got})
    return accuracy_by_slice((r["slice"], r["correct"] == "yes") for r in rows), rows


def test_dataset_covers_every_slice_and_family() -> None:
    assert {c.slice for c in CASES} == {"formal", "informal", "typos", "non_native", "hinglish", "caps_punct", "emoji"}
    assert {c.family for c in CASES} == {"resend", "interview", "status"}


def test_phrasing_slices_do_not_regress_against_the_accepted_baseline() -> None:
    accuracy, rows = _measure()
    target = os.environ.get("PARITY_RESULTS_JSON")
    if target:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    assert regressions(accuracy, BASELINE) == {}


def test_the_recorded_live_run_of_the_hybrid_router_meets_the_gap_target() -> None:
    """Rules alone leave typos and Hinglish at 0% (see the rules-only baseline). ADR-015 adds a gated LLM fallback; this checks the
    RECORDED live run (scripts/eval_intent_fallback.py --save-baseline). CI never calls the LLM, so refresh the record after changing
    the classifier prompt, the gate or the model."""
    record = json.loads((DATA / "baselines" / "parity_intent_hybrid_live.json").read_text(encoding="utf-8"))
    assert set(record["hybrid"]) == {c.slice for c in CASES}
    assert record["errors"] == 0
    assert record["gap_hybrid"] <= TARGET_GAP
    assert record["gap_rules_only"] > TARGET_GAP  # the gap that motivated the fallback is real, and the rules alone do not close it


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("intent", list(REQUESTS))
def test_a_name_in_the_message_never_changes_the_intent(name: str, intent: str) -> None:
    base = classify_intent(REQUESTS[intent])
    assert classify_intent(f"Hi, I'm {name}. {REQUESTS[intent]}").intent == base.intent
    assert classify_intent(f"{REQUESTS[intent]} Regards, {name}").intent == base.intent


@pytest.mark.parametrize("programme", PROGRAMMES)
@pytest.mark.parametrize("intent", list(REQUESTS))
def test_a_programme_in_the_message_never_changes_the_intent(programme: str, intent: str) -> None:
    base = classify_intent(REQUESTS[intent])
    assert classify_intent(f"As a {programme} applicant: {REQUESTS[intent]}").intent == base.intent

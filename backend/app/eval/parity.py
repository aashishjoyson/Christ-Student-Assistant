"""Phrasing-parity audit: does the same request get the same treatment however it is worded? (stdlib only)

A "slice" is a phrasing style (formal, informal, typos, non-native English, Hinglish, ...). For each slice we measure how
often the deterministic intent rules route the message to the intent a human would expect, then compare slices.
Samples are tiny and synthetic, so report effect sizes, never claims of statistical fairness.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParityCase:
    id: str
    family: str  # resend | interview | status
    slice: str  # phrasing style
    message: str
    expected_intent: str


def load_parity_cases(path: Path) -> list[ParityCase]:
    cases = [ParityCase(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: duplicate ids")
    return cases


def accuracy_by_slice(rows: Iterable[tuple[str, bool]]) -> dict[str, float]:
    totals: dict[str, list[int]] = {}
    for slice_name, correct in rows:
        t = totals.setdefault(slice_name, [0, 0])
        t[0] += int(correct)
        t[1] += 1
    return {name: round(ok / n, 4) for name, (ok, n) in sorted(totals.items())}


def gap(accuracy: Mapping[str, float]) -> float:
    """Largest difference between any two slices (in fraction points, 0..1)."""
    return round(max(accuracy.values()) - min(accuracy.values()), 4) if accuracy else 0.0


def regressions(current: Mapping[str, float], baseline: Mapping[str, float], tolerance: float = 0.0) -> dict[str, tuple[float, float]]:
    """Slices whose accuracy dropped below the accepted baseline: {slice: (baseline, current)}."""
    return {
        name: (base, current.get(name, 0.0))
        for name, base in baseline.items()
        if current.get(name, 0.0) + tolerance < base
    }

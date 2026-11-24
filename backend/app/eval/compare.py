"""Promotion gates: may this evaluation run replace the accepted baseline? (stdlib only)

A change (a prompt, a model, a retrieval setting, a parser, an adapter) is promoted only if its evaluation run is comparable with the
baseline and no gate regresses. Gates are either "critical" (they block promotion) or warnings (reported, never blocking). The numbers below
come from the measured run-to-run noise of about one question (about 2.6 points on 38 questions): a tolerance smaller than that would fail
a run for nothing, a larger one would let real regressions through. See docs/PROMOTION_POLICY.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

HIGHER, LOWER = "higher", "lower"
PASS, WARN, FAIL = "pass", "warn", "fail"


@dataclass(frozen=True)
class Gate:
    metric: str
    direction: str  # HIGHER: bigger is better. LOWER: smaller is better.
    tolerance: float  # how much worse than the baseline is still acceptable
    critical: bool
    relative: bool = False  # True: tolerance is a ratio of the baseline (1.5 = up to 50% worse); False: an absolute difference
    note: str = ""


# Gates for the document-grounded mode ("rag"). Safety-like metrics have tolerance 0: they must not get worse at all.
RAG_GATES: tuple[Gate, ...] = (
    Gate("answer_accuracy", HIGHER, 0.06, True, note="about two questions of 38"),
    Gate("correct_refusal_rate", HIGHER, 0.0, True, note="an unanswerable question must still be refused"),
    Gate("unsupported_answer_rate", LOWER, 0.0, True, note="nothing may be invented where the documents are silent"),
    Gate("citations_valid_rate", HIGHER, 0.0, True, note="a citation number must point at a supplied passage"),
    Gate("routed_academic_rate", HIGHER, 0.03, True, note="documents questions must not be sent to the personal-data path"),
    Gate("errors", LOWER, 0.0, True, note="no new errors"),
    Gate("context_recall", HIGHER, 0.05, False),
    Gate("citation_hit_rate", HIGHER, 0.06, False),
    Gate("retrieval_mrr", HIGHER, 0.05, False),
    Gate("false_refusal_rate", LOWER, 0.06, False),
    Gate("latency_p95_ms", LOWER, 1.5, False, relative=True, note="a latency spike is a warning, not a verdict (one slow call moves p95)"),
    Gate("cost_per_answer_usd", LOWER, 1.5, False, relative=True),
)


@dataclass(frozen=True)
class GateResult:
    metric: str
    baseline: float | None
    current: float | None
    status: str  # PASS | WARN | FAIL
    critical: bool
    detail: str


@dataclass
class Comparison:
    comparable: bool
    problems: list[str] = field(default_factory=list)  # why the runs cannot be compared at all
    notes: list[str] = field(default_factory=list)  # things that differ but do not block (for example, the indexed documents)
    results: list[GateResult] = field(default_factory=list)

    @property
    def failed(self) -> list[GateResult]:
        return [r for r in self.results if r.status == FAIL]

    @property
    def warnings(self) -> list[GateResult]:
        return [r for r in self.results if r.status == WARN]

    @property
    def passed(self) -> bool:
        return self.comparable and not self.failed


def metric_value(mode_summary: dict[str, Any], metric: str) -> float | None:
    if metric == "cost_per_answer_usd":
        total, n = mode_summary.get("cost_usd_total"), mode_summary.get("n")
        return round(total / n, 6) if total is not None and n else None
    value = mode_summary.get(metric)
    return float(value) if value is not None else None


def _judge(gate: Gate, baseline: float, current: float) -> tuple[str, str]:
    if gate.relative:
        limit = baseline * gate.tolerance if gate.direction == LOWER else baseline / gate.tolerance
        worse = current > limit if gate.direction == LOWER else current < limit
        detail = f"{current:g} vs baseline {baseline:g} (allowed up to x{gate.tolerance:g})"
    else:
        diff = current - baseline
        worse = diff < -gate.tolerance if gate.direction == HIGHER else diff > gate.tolerance
        detail = f"{current:g} vs baseline {baseline:g} ({diff:+.4g}, allowed {'-' if gate.direction == HIGHER else '+'}{gate.tolerance:g})"
    if not worse:
        return PASS, detail
    return (FAIL if gate.critical else WARN), detail


def compare(baseline: dict[str, Any], current: dict[str, Any], gates: tuple[Gate, ...] = RAG_GATES, mode: str = "rag") -> Comparison:
    """`baseline` and `current` are the dicts written by write_baseline() / by a run (config + summary merged: keys `golden_set`, `modes`, `index`)."""
    out = Comparison(comparable=True)
    if baseline.get("golden_set", {}).get("sha256") != current.get("golden_set", {}).get("sha256"):
        out.comparable = False
        out.problems.append("The golden question set differs from the baseline's. A different set measures something else: "
                            "re-run both on the same set, or promote the new set with --allow-new-golden.")
    if mode not in baseline.get("modes", {}) or mode not in current.get("modes", {}):
        out.comparable = False
        out.problems.append(f"Mode '{mode}' is missing from the baseline or from the run.")
    if not out.comparable:
        return out
    if baseline.get("index", {}).get("sha256") != current.get("index", {}).get("sha256"):
        out.notes.append("The indexed documents differ from those the baseline was measured on; a difference may come from the data, not the change.")
    if baseline.get("prompt_versions") != current.get("prompt_versions"):
        out.notes.append(f"Prompt versions changed: {baseline.get('prompt_versions')} -> {current.get('prompt_versions')}")
    for key in ("llm", "retrieval"):
        if baseline.get(key) != current.get(key):
            changed = {k: (baseline.get(key, {}).get(k), v) for k, v in current.get(key, {}).items() if baseline.get(key, {}).get(k) != v}
            out.notes.append(f"{key} settings changed (baseline -> now): {changed}")
    for gate in gates:
        base = metric_value(baseline["modes"][mode], gate.metric)
        now = metric_value(current["modes"][mode], gate.metric)
        if base is None or now is None:
            out.results.append(GateResult(gate.metric, base, now, PASS, gate.critical, "not measured in one of the runs; skipped"))
            continue
        status, detail = _judge(gate, base, now)
        out.results.append(GateResult(gate.metric, base, now, status, gate.critical, detail + (f"; {gate.note}" if gate.note and status != PASS else "")))
    return out


def render(comparison: Comparison) -> str:
    lines: list[str] = []
    for problem in comparison.problems:
        lines.append(f"INCOMPARABLE: {problem}")
    for result in comparison.results:
        mark = {PASS: "ok  ", WARN: "WARN", FAIL: "FAIL"}[result.status]
        lines.append(f"  {mark} {result.metric:26s} {result.detail}{'  [critical]' if result.critical and result.status == FAIL else ''}")
    lines.extend(f"  note: {n}" for n in comparison.notes)
    if comparison.comparable:
        lines.append("RESULT: " + ("PASS" if comparison.passed else f"FAIL ({len(comparison.failed)} critical gate(s))")
                     + (f", {len(comparison.warnings)} warning(s)" if comparison.warnings else ""))
    return "\n".join(lines)


def make_baseline(config: dict[str, Any], summary: dict[str, Any], reason: str, now: datetime | None = None) -> dict[str, Any]:
    """The record a future run is compared with: who/what/when it was measured on, plus the metrics. No answers, no secrets."""
    return {
        "run_id": config["run_id"], "promoted_at": (now or datetime.now(UTC)).isoformat(), "reason": reason,
        "git": config.get("git"), "golden_set": config["golden_set"], "index": config["index"], "prompt_versions": config["prompt_versions"],
        "llm": config["llm"], "retrieval": config["retrieval"], "modes": summary["modes"], "calibration": summary.get("calibration"),
    }


def merge_run(config: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    """A run folder's config.json + summary.json in the same shape as a baseline, so compare() treats both alike."""
    return {**{k: config.get(k) for k in ("run_id", "git", "golden_set", "index", "prompt_versions", "llm", "retrieval")},
            "modes": summary["modes"], "calibration": summary.get("calibration")}

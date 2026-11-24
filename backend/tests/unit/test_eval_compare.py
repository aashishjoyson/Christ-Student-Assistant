"""Promotion gates and the compare/promote command."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.eval.compare import FAIL, PASS, WARN, compare, make_baseline, merge_run, metric_value, render

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "compare_eval.py"

RAG = {"n": 38, "errors": 0, "answer_accuracy": 0.9333, "correct_refusal_rate": 1.0, "unsupported_answer_rate": 0.0, "citations_valid_rate": 1.0,
       "routed_academic_rate": 1.0, "context_recall": 1.0, "citation_hit_rate": 0.9333, "retrieval_mrr": 0.9444, "false_refusal_rate": 0.0667,
       "latency_p95_ms": 3000.0, "cost_usd_total": 0.0055}


def run_dict(rag: dict | None = None, golden: str = "g1", index: str = "i1", prompts: dict | None = None) -> dict:
    return {"run_id": "eval-x", "git": {"commit": "abc", "dirty": False}, "golden_set": {"sha256": golden, "cases": 38}, "index": {"sha256": index},
            "prompt_versions": prompts or {"rag": "rag-v2"}, "llm": {"model": "m"}, "retrieval": {"top_k": 8},
            "modes": {"rag": {**RAG, **(rag or {})}}, "calibration": None}


def statuses(result) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {r.metric: r.status for r in result.results}


def test_an_identical_run_passes_every_gate() -> None:
    result = compare(run_dict(), run_dict())
    assert result.comparable and result.passed and not result.warnings
    assert set(statuses(result).values()) == {PASS}


def test_noise_of_about_one_question_is_tolerated() -> None:
    result = compare(run_dict(), run_dict({"answer_accuracy": 0.9, "context_recall": 0.97, "retrieval_mrr": 0.92}))  # 0.033 lower: one question
    assert result.passed and not result.warnings


def test_a_real_accuracy_drop_blocks_promotion() -> None:
    result = compare(run_dict(), run_dict({"answer_accuracy": 0.8333}))  # 0.10 lower: four questions
    assert not result.passed and statuses(result)["answer_accuracy"] == FAIL


@pytest.mark.parametrize(("metric", "value"), [
    ("correct_refusal_rate", 0.875),  # one unanswerable question was answered instead of refused
    ("unsupported_answer_rate", 0.125),
    ("citations_valid_rate", 0.97),
    ("errors", 1),
    ("routed_academic_rate", 0.9),
])
def test_safety_like_gates_have_no_slack(metric: str, value: float) -> None:
    result = compare(run_dict(), run_dict({metric: value}))
    assert not result.passed and statuses(result)[metric] == FAIL


def test_quality_side_metrics_only_warn() -> None:
    result = compare(run_dict(), run_dict({"context_recall": 0.8, "citation_hit_rate": 0.8, "retrieval_mrr": 0.8, "false_refusal_rate": 0.2}))
    assert result.passed
    assert {m for m, s in statuses(result).items() if s == WARN} == {"context_recall", "citation_hit_rate", "retrieval_mrr", "false_refusal_rate"}


def test_latency_and_cost_are_ratios_and_only_warn() -> None:
    fine = compare(run_dict(), run_dict({"latency_p95_ms": 4400.0, "cost_usd_total": 0.0080}))  # x1.47 and x1.45
    assert statuses(fine)["latency_p95_ms"] == PASS and statuses(fine)["cost_per_answer_usd"] == PASS
    slow = compare(run_dict(), run_dict({"latency_p95_ms": 9000.0, "cost_usd_total": 0.02}))
    assert slow.passed and statuses(slow)["latency_p95_ms"] == WARN and statuses(slow)["cost_per_answer_usd"] == WARN


def test_a_different_golden_set_is_incomparable_not_a_pass() -> None:
    result = compare(run_dict(), run_dict(golden="other"))
    assert not result.comparable and not result.passed and "golden" in result.problems[0].lower()


def test_a_missing_mode_is_incomparable() -> None:
    current = run_dict()
    current["modes"] = {"direct": {"n": 38}}
    assert not compare(run_dict(), current).comparable


def test_changes_that_explain_a_difference_are_reported_as_notes_not_failures() -> None:
    result = compare(run_dict(), run_dict(index="i2", prompts={"rag": "rag-v3"}))
    assert result.passed
    text = " ".join(result.notes)
    assert "documents differ" in text and "rag-v3" in text


def test_a_metric_missing_from_one_side_is_skipped_not_failed() -> None:
    result = compare(run_dict({"context_recall": None}), run_dict())
    assert result.passed and statuses(result)["context_recall"] == PASS


def test_cost_per_answer_is_derived_from_the_total() -> None:
    assert metric_value({"cost_usd_total": 0.0038, "n": 38}, "cost_per_answer_usd") == 0.0001
    assert metric_value({"cost_usd_total": None, "n": 38}, "cost_per_answer_usd") is None


def test_the_rendering_names_failures_and_the_verdict() -> None:
    text = render(compare(run_dict(), run_dict({"answer_accuracy": 0.7, "context_recall": 0.5})))
    assert "FAIL answer_accuracy" in text and "WARN context_recall" in text and "RESULT: FAIL (1 critical gate(s)), 1 warning(s)" in text


# ---------------------------------------------------------------- the command
def write_run(root: Path, run_id: str, rag: dict | None = None, golden: str = "g1", dirty: bool = False) -> Path:
    folder = root / run_id
    folder.mkdir(parents=True)
    run = run_dict(rag, golden)
    config = {**{k: run[k] for k in ("golden_set", "index", "prompt_versions", "llm", "retrieval")}, "run_id": run_id,
              "git": {"commit": "abc123", "dirty": dirty}}
    (folder / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (folder / "summary.json").write_text(json.dumps({"run_id": run_id, "modes": run["modes"], "calibration": None}), encoding="utf-8")
    return folder


def cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False, cwd=cwd)  # noqa: S603


def test_the_first_promotion_creates_the_baseline_and_needs_a_reason(tmp_path: Path) -> None:
    runs, baseline = tmp_path / "runs", tmp_path / "baseline.json"
    write_run(runs, "eval-001")
    refused = cli("latest", "--runs-root", str(runs), "--baseline", str(baseline), "--promote", cwd=tmp_path)
    assert refused.returncode == 2 and "--reason is required" in refused.stderr and not baseline.exists()
    done = cli("latest", "--runs-root", str(runs), "--baseline", str(baseline), "--promote", "--reason", "initial baseline", cwd=tmp_path)
    assert done.returncode == 0 and "PROMOTED" in done.stdout
    saved = json.loads(baseline.read_text(encoding="utf-8"))
    assert saved["run_id"] == "eval-001" and saved["reason"] == "initial baseline" and saved["modes"]["rag"]["answer_accuracy"] == 0.9333


def test_a_regressing_run_fails_the_comparison_and_cannot_be_promoted(tmp_path: Path) -> None:
    runs, baseline = tmp_path / "runs", tmp_path / "baseline.json"
    write_run(runs, "eval-001")
    cli("eval-001", "--runs-root", str(runs), "--baseline", str(baseline), "--promote", "--reason", "initial", cwd=tmp_path)
    bad = write_run(runs, "eval-002", {"answer_accuracy": 0.7})
    compared = cli(str(bad), "--baseline", str(baseline), cwd=tmp_path)
    assert compared.returncode == 1 and "FAIL answer_accuracy" in compared.stdout
    refused = cli(str(bad), "--baseline", str(baseline), "--promote", "--reason", "trying anyway", cwd=tmp_path)
    assert refused.returncode == 2 and "critical gate(s) failed" in refused.stderr
    assert json.loads(baseline.read_text(encoding="utf-8"))["run_id"] == "eval-001"  # untouched


def test_a_better_run_passes_and_can_replace_the_baseline(tmp_path: Path) -> None:
    runs, baseline = tmp_path / "runs", tmp_path / "baseline.json"
    write_run(runs, "eval-001")
    cli("eval-001", "--runs-root", str(runs), "--baseline", str(baseline), "--promote", "--reason", "initial", cwd=tmp_path)
    better = write_run(runs, "eval-002", {"answer_accuracy": 0.9667})
    assert cli(str(better), "--baseline", str(baseline), cwd=tmp_path).returncode == 0
    done = cli(str(better), "--baseline", str(baseline), "--promote", "--reason", "new re-rank weight", cwd=tmp_path)
    assert done.returncode == 0 and json.loads(baseline.read_text(encoding="utf-8"))["run_id"] == "eval-002"


def test_a_run_from_a_dirty_tree_or_with_errors_is_refused_unless_allowed(tmp_path: Path) -> None:
    runs, baseline = tmp_path / "runs", tmp_path / "baseline.json"
    dirty = write_run(runs, "eval-001", dirty=True)
    refused = cli(str(dirty), "--baseline", str(baseline), "--promote", "--reason", "x", cwd=tmp_path)
    assert refused.returncode == 2 and "uncommitted changes" in refused.stderr
    assert cli(str(dirty), "--baseline", str(baseline), "--promote", "--reason", "x", "--allow-dirty", cwd=tmp_path).returncode == 0
    broken = write_run(runs, "eval-002", {"errors": 2})
    assert "had errors" in cli(str(broken), "--baseline", str(tmp_path / "b2.json"), "--promote", "--reason", "x", cwd=tmp_path).stderr


def test_a_different_golden_set_needs_an_explicit_flag_to_promote(tmp_path: Path) -> None:
    runs, baseline = tmp_path / "runs", tmp_path / "baseline.json"
    write_run(runs, "eval-001")
    cli("eval-001", "--runs-root", str(runs), "--baseline", str(baseline), "--promote", "--reason", "initial", cwd=tmp_path)
    other = write_run(runs, "eval-002", golden="g2")
    assert cli(str(other), "--baseline", str(baseline), cwd=tmp_path).returncode == 2
    assert cli(str(other), "--baseline", str(baseline), "--promote", "--reason", "bigger set", cwd=tmp_path).returncode == 2
    assert cli(str(other), "--baseline", str(baseline), "--promote", "--reason", "bigger set", "--allow-new-golden", cwd=tmp_path).returncode == 0


def test_latest_picks_the_newest_run_that_has_the_mode_and_a_missing_run_is_a_clear_error(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    write_run(runs, "eval-001")
    only_direct = write_run(runs, "eval-002")
    (only_direct / "summary.json").write_text(json.dumps({"modes": {"direct": {"n": 1}}}), encoding="utf-8")
    out = cli("latest", "--runs-root", str(runs), "--baseline", str(tmp_path / "none.json"), cwd=tmp_path)
    assert "run: eval-001" in out.stdout and "No baseline yet" in out.stdout
    assert cli("latest", "--runs-root", str(tmp_path / "empty"), cwd=tmp_path).returncode == 2


def test_make_baseline_keeps_no_answers_or_secrets() -> None:
    run = run_dict()
    baseline = make_baseline({**{k: run[k] for k in ("golden_set", "index", "prompt_versions", "llm", "retrieval", "git")}, "run_id": "eval-x"},
                             {"modes": run["modes"]}, "because")
    text = json.dumps(baseline)
    assert baseline["reason"] == "because" and "answer\"" not in text and merge_run({"run_id": "r"}, {"modes": {}})["run_id"] == "r"
    assert copy.deepcopy(baseline) == baseline

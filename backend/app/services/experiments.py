"""The evaluation runs on disk and the accepted baseline, summarised for the admin page (read-only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KEY_METRICS = ("n", "answer_accuracy", "context_recall", "citation_hit_rate", "correct_refusal_rate", "unsupported_answer_rate",
               "false_refusal_rate", "retrieval_mrr", "latency_p50_ms", "latency_p95_ms", "cost_usd_total", "errors")


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _modes(modes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {name: {k: m.get(k) for k in KEY_METRICS} for name, m in modes.items() if isinstance(m, dict)}


def list_runs(eval_dir: Path, limit: int = 10) -> list[dict[str, Any]]:
    """The newest evaluation runs (folders named eval-<date>-<time>-<hash>), newest first."""
    runs: list[dict[str, Any]] = []
    if not eval_dir.is_dir():
        return runs
    for folder in sorted((p for p in eval_dir.glob("eval-*") if p.is_dir()), reverse=True):
        summary, config = _read(folder / "summary.json"), _read(folder / "config.json")
        if summary is None or config is None:
            continue
        runs.append({
            "run_id": config.get("run_id", folder.name), "created_at": config.get("created_at"), "git": config.get("git"),
            "golden_set_sha256": (config.get("golden_set") or {}).get("sha256"), "cases": (config.get("golden_set") or {}).get("cases"),
            "retrieval": config.get("retrieval"), "prompt_versions": config.get("prompt_versions"), "modes": _modes(summary.get("modes", {})),
        })
        if len(runs) >= limit:
            break
    return runs


def read_baseline(path: Path) -> dict[str, Any] | None:
    baseline = _read(path)
    if baseline is None:
        return None
    return {"run_id": baseline.get("run_id"), "promoted_at": baseline.get("promoted_at"), "reason": baseline.get("reason"), "git": baseline.get("git"),
            "golden_set_sha256": (baseline.get("golden_set") or {}).get("sha256"), "modes": _modes(baseline.get("modes", {}))}


def experiments_summary(eval_dir: Path, baseline_file: Path, limit: int = 10) -> dict[str, Any]:
    return {"baseline": read_baseline(baseline_file), "runs": list_runs(eval_dir, limit)}

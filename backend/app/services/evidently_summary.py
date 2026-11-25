"""What Evidently said about the latest evaluation run, read from the JSON that `scripts/evidently_report.py` saved.

Evidently is used only from scripts/ (requirements-eval.txt); the API just reads the files it wrote, so the dashboard needs no Evidently install."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

OUTCOMES = ("correct", "correct_refusal", "false_refusal", "wrong_answer", "unsupported_answer", "error")
REPORT_JSON = "evidently_evaluation.json"
REPORT_HTML = "evidently_evaluation.html"


def latest_run(eval_dir: Path) -> Path | None:
    """The newest evaluation run folder that has an Evidently report."""
    if not eval_dir.is_dir():
        return None
    for run in sorted((p for p in eval_dir.glob("eval-*") if p.is_dir()), reverse=True):
        if (run / REPORT_JSON).is_file():
            return run
    return None


def report_html(run: Path) -> Path | None:
    path = run / REPORT_HTML
    return path if path.is_file() else None


def summarize(run: Path) -> dict[str, Any]:
    data = json.loads((run / REPORT_JSON).read_text(encoding="utf-8"))
    by_mode: dict[str, dict[str, int]] = {}
    by_category: dict[str, dict[str, int]] = {}
    for metric in data.get("metrics", []):
        config = metric.get("config") or {}
        inner = config.get("metric") or {}
        categories = inner.get("categories") or ([inner["category"]] if inner.get("category") else [])
        if not str(config.get("type", "")).endswith("GroupByMetric") or inner.get("column") != "outcome" or not categories:
            continue
        target = by_mode if config.get("column_name") == "mode" else by_category if config.get("column_name") == "category" else None
        if target is not None:
            target.setdefault(str(config.get("label")), {})[str(categories[0])] = round(float((metric.get("value") or {}).get("count", 0)))
    tests = [{"name": t.get("name"), "description": t.get("description"), "status": t.get("status")} for t in data.get("tests", [])]
    html = report_html(run)
    stamp = (run / REPORT_JSON).stat().st_mtime
    return {
        "available": True,
        "run_id": run.name,
        "generated_at": datetime.fromtimestamp(stamp, UTC).isoformat(timespec="seconds"),
        "outcomes": list(OUTCOMES),
        "by_mode": by_mode,
        "by_category": by_category,
        "tests": tests,
        "tests_passed": sum(1 for t in tests if str(t["status"]).upper() == "SUCCESS"),
        "html_available": html is not None,
        "html_kb": round(html.stat().st_size / 1024) if html else None,
    }

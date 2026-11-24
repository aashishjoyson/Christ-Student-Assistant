"""Look at how the live system has been behaving: traffic, errors, latency, cost, "could not find" rate, retrieval-distance drift, thumbs, index age.

  python scripts/monitor_traces.py                      # last 24 h compared with the 7 days before
  python scripts/monitor_traces.py --hours 6 --reference-hours 72
  python scripts/monitor_traces.py --json               # the same report as the admin endpoint
  python scripts/monitor_traces.py --evidently          # also an Evidently data-drift report (needs requirements-eval.txt)

Reads storage/traces/requests.jsonl (no message text, by design), the feedback table and the sync history. It never calls a model.
Exit codes: 0 no critical alert (warnings are printed); 1 a critical alert; 2 no trace log. The alert thresholds are in backend/app/eval/monitoring.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.db.session import init_db, make_engine, make_session_factory  # noqa: E402
from app.domain.clock import utcnow  # noqa: E402
from app.eval.monitoring import in_window  # noqa: E402
from app.services.monitoring_service import build_report, read_traces  # noqa: E402

MIN_ROWS_FOR_DRIFT = 20
MARK = {"critical": "CRITICAL", "warning": "WARNING ", "info": "info    "}


def _line(label: str, value: object) -> str:
    return f"  {label:<26}{value}"


def print_report(report: dict) -> None:
    cur, ref = report["current"], report["reference"]
    print(f"Last {report['window_hours']:g} h (compared with the {report['reference_hours']:g} h before it)   status: {report['status'].upper()}")
    print(_line("requests", f"{cur['requests']}  (reference {ref['requests']})"))
    print(_line("errors", f"{cur['errors']}  rate {cur['error_rate']}  {cur['error_codes'] or ''}"))
    print(_line("latency p50 / p95 (ms)", f"{cur['latency_ms']['p50']} / {cur['latency_ms']['p95']}  (reference {ref['latency_ms']['p95']} p95)"))
    print(_line("first word p50 / p95 (ms)", f"{cur['first_word_ms']['p50']} / {cur['first_word_ms']['p95']}"))
    print(_line("cost per request (USD)", f"{cur['cost_usd_per_request']}  total {cur['cost_usd_total']}  (reference {ref['cost_usd_per_request']})"))
    print(_line("document questions", f"{cur['document_questions']}  no-passage rate {cur['no_evidence_rate']}  not indexed {cur['not_indexed']}"))
    d = cur["best_distance"]
    print(_line("nearest passage distance", f"mean {d['mean']}  p50 {d['p50']}  p90 {d['p90']}  (reference mean {ref['best_distance']['mean']})"))
    print(_line("intent mix", cur["intent_mix"]))
    print(_line("mode mix", cur["mode_mix"]))
    f = cur["feedback"]
    print(_line("thumbs", f"{f['votes']} votes, {f['down']} down ({f['thumbs_down_rate']})  {f['down_reasons'] or ''}"))
    idx = report["index"]
    print(_line("last document sync", f"{idx['last_successful_sync']}  age {idx['age_seconds']} s  automatic ingestion: {idx['automatic_ingestion']}"))
    for alert in report["alerts"]:
        print(f"  [{MARK[alert['level']]}] {alert['code']}: {alert['message']}")
    if not report["alerts"]:
        print("  no alerts")


def evidently_drift(traces: list[dict], now, hours: float, reference_hours: float, out_dir: Path) -> None:  # type: ignore[no-untyped-def]
    try:
        import pandas as pd
        from evidently import DataDefinition, Dataset, Report
        from evidently.presets import DataDriftPreset
    except ImportError as exc:
        print(f"Evidently is not installed ({exc}). pip install -r backend/requirements-eval.txt", file=sys.stderr)
        return

    def frame(items: list[dict]) -> pd.DataFrame:
        rows = [{"latency_ms": t.get("total_latency_ms"), "best_distance": (t.get("retrieval") or {}).get("best_distance"),
                 "cost_usd": float(t.get("est_cost_usd") or 0.0), "intent": str(t.get("intent")), "mode": str(t.get("model_mode_requested"))}
                for t in items if not t.get("error_code")]
        return pd.DataFrame(rows)

    cut = now - timedelta(hours=hours)
    current, reference = frame(in_window(traces, cut, now)), frame(in_window(traces, cut - timedelta(hours=reference_hours), cut))
    if len(current) < MIN_ROWS_FOR_DRIFT or len(reference) < MIN_ROWS_FOR_DRIFT:
        print(f"Drift report skipped: it needs at least {MIN_ROWS_FOR_DRIFT} requests in each window (now {len(current)} / {len(reference)}).")
        return
    definition = DataDefinition(numerical_columns=["latency_ms", "best_distance", "cost_usd"], categorical_columns=["intent", "mode"])
    snapshot = Report([DataDriftPreset()]).run(Dataset.from_pandas(current, data_definition=definition),
                                               Dataset.from_pandas(reference, data_definition=definition))
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"drift_{now.strftime('%Y%m%d-%H%M%S')}.html"
    snapshot.save_html(str(target))
    print(f"Evidently drift report: {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--reference-hours", type=float, default=168)
    parser.add_argument("--traces", type=Path, help="trace log (default: the app's)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--evidently", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    path = args.traces or settings.trace_dir / "requests.jsonl"
    if not path.is_file():
        print(f"No trace log at {path}. Ask the system something first.", file=sys.stderr)
        return 2
    engine = make_engine(settings.database_url)
    init_db(engine)
    now, traces = utcnow(), read_traces(path)
    report = build_report(settings, make_session_factory(engine), now, args.hours, args.reference_hours, traces=traces)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_report(report)
    if args.evidently:
        evidently_drift(traces, now, args.hours, args.reference_hours, REPO_ROOT / "storage" / "eval" / "monitoring")
    return 1 if report["status"] == "critical" else 0


if __name__ == "__main__":
    raise SystemExit(main())

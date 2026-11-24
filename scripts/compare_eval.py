"""Compare an evaluation run with the accepted baseline, and (deliberately) promote it to become the new baseline.

  python scripts/compare_eval.py latest                      # newest run in storage/eval that has Model 2 results
  python scripts/compare_eval.py storage/eval/<run_id>       # a specific run
  python scripts/compare_eval.py latest --promote --reason "why this replaces the baseline"

Gates and tolerances live in backend/app/eval/compare.py; the rules for when a change may be promoted are in docs/PROMOTION_POLICY.md.
Exit codes: 0 every critical gate passed (warnings are printed); 1 a critical gate failed; 2 the runs cannot be compared, or promotion was refused.
A promotion needs --reason (recorded in the baseline file), a passing comparison (or no baseline yet), a run without errors, and a run made on a
committed tree (--allow-dirty records that it was not). A different golden set needs --allow-new-golden.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.eval.compare import compare, make_baseline, merge_run, render  # noqa: E402

DEFAULT_BASELINE = REPO_ROOT / "data" / "eval" / "baselines" / "academic_real_baseline.json"
RUNS_ROOT = REPO_ROOT / "storage" / "eval"


def load_run(run_dir: Path) -> tuple[dict, dict]:
    return (json.loads((run_dir / "config.json").read_text(encoding="utf-8")),
            json.loads((run_dir / "summary.json").read_text(encoding="utf-8")))


def latest_run(root: Path, mode: str) -> Path | None:
    for candidate in sorted((p for p in root.glob("eval-*") if p.is_dir()), reverse=True):
        try:
            _, summary = load_run(candidate)
        except (OSError, ValueError):
            continue
        if mode in summary.get("modes", {}):
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", help="a run folder, or 'latest'")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--mode", default="rag")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--reason", default="")
    parser.add_argument("--allow-new-golden", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    if args.run == "latest":
        run_dir = latest_run(args.runs_root, args.mode)
    else:  # a path, or just the run id of a folder under the runs root
        run_dir = Path(args.run) if Path(args.run).is_dir() else args.runs_root / args.run
    if run_dir is None or not (run_dir / "summary.json").is_file():
        print(f"No evaluation run with '{args.mode}' results found (looked in {args.runs_root}).", file=sys.stderr)
        return 2
    config, summary = load_run(run_dir)
    current = merge_run(config, summary)
    print(f"run: {config['run_id']}  (git {str((config.get('git') or {}).get('commit'))[:8]}{', uncommitted changes' if (config.get('git') or {}).get('dirty') else ''})")

    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline.is_file() else None
    comparison = None
    if baseline is None:
        print(f"No baseline yet at {args.baseline}.")
    else:
        print(f"baseline: {baseline['run_id']}  promoted {baseline['promoted_at'][:10]}: {baseline.get('reason', '')}")
        comparison = compare(baseline, current, mode=args.mode)
        print(render(comparison))

    if not args.promote:
        if comparison is None:
            return 2
        return 0 if comparison.passed else (1 if comparison.comparable else 2)

    # ---- promotion: every refusal says why
    refusals: list[str] = []
    if not args.reason.strip():
        refusals.append("--reason is required (it is recorded in the baseline).")
    if summary["modes"].get(args.mode, {}).get("errors"):
        refusals.append("the run had errors; a baseline must be a clean run.")
    if (config.get("git") or {}).get("dirty") and not args.allow_dirty:
        refusals.append("the run was made with uncommitted changes, so it cannot be tied to a commit (commit first, or --allow-dirty).")
    if comparison is not None:
        if not comparison.comparable and not args.allow_new_golden:
            refusals.append("the runs are not comparable (different golden set or missing mode); --allow-new-golden if that is the point.")
        elif comparison.comparable and not comparison.passed:
            refusals.append(f"{len(comparison.failed)} critical gate(s) failed; promotion is refused.")
    if refusals:
        print("PROMOTION REFUSED:\n  - " + "\n  - ".join(refusals), file=sys.stderr)
        return 2
    args.baseline.parent.mkdir(parents=True, exist_ok=True)
    args.baseline.write_text(json.dumps(make_baseline(config, summary, args.reason.strip()), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"PROMOTED: {config['run_id']} is now the baseline ({args.baseline.relative_to(REPO_ROOT) if args.baseline.is_relative_to(REPO_ROOT) else args.baseline}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

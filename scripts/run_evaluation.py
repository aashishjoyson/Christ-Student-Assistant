"""Run the golden-set evaluation against the real system and write a frozen, comparable record of it.

  python scripts/run_evaluation.py                       # modes direct,rag on data/eval/academic_real.jsonl
  python scripts/run_evaluation.py --modes rag --limit 5 # a quick smoke run
  python scripts/run_evaluation.py --evidently           # also build the Evidently HTML report (needs requirements-eval.txt)

Costs real (small) API money: one answer per question per mode, plus one embedding call per question. It prints the call counts first.
Writes storage/eval/<run_id>/{config.json, summary.json, results.jsonl, results.csv, retrieval.jsonl}; the run's own trace log goes
inside that folder, so evaluation never mixes with real traffic. Stop the API first if you changed the index (one writer at a time).

Exit codes: 0 done; 2 not ready (no key, nothing indexed, golden file problem).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.container import build_container  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.models import IngestedFile  # noqa: E402
from app.domain.model_modes import PROMPT_VERSIONS  # noqa: E402
from app.eval.golden import load_golden  # noqa: E402
from app.eval.runner import (  # noqa: E402
    AskFailed,
    build_summary,
    git_state,
    index_fingerprint,
    run_cases,
    snapshot_config,
    write_run,
)
from app.llm.factory import build_model3_client  # noqa: E402
from app.schemas.chat import ChatRequest  # noqa: E402
from app.services.chat_service import ChatError  # noqa: E402

KNOWN_MODES = ("direct", "rag", "rag_peft", "rag_peft_base")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", type=Path, default=REPO_ROOT / "data" / "eval" / "academic_real.jsonl")
    parser.add_argument("--modes", default="direct,rag", help="comma list of: direct, rag, rag_peft, rag_peft_base (the ablation: the base model on the Model 3 endpoint). Model 3 errors are recorded, never replaced")
    parser.add_argument("--limit", type=int, help="only the first N cases (smoke run)")
    parser.add_argument("--out-root", type=Path, default=REPO_ROOT / "storage" / "eval")
    parser.add_argument("--evidently", action="store_true", help="also build the Evidently report for this run")
    args = parser.parse_args()
    args.out_root = args.out_root.resolve()
    args.set = args.set.resolve()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if not modes or any(m not in KNOWN_MODES for m in modes):
        print(f"--modes must be a comma list from {KNOWN_MODES}", file=sys.stderr)
        return 2
    try:
        cases = load_golden(args.set)
    except (OSError, ValueError) as exc:
        print(f"Golden set problem: {exc}", file=sys.stderr)
        return 2
    if args.limit:
        cases = cases[: args.limit]

    settings = get_settings()
    if not settings.primary_configured:
        print("The answering model is not configured (OPENAI_API_KEY / OPENAI_CHAT_MODEL in .env).", file=sys.stderr)
        return 2
    # The run keeps its own trace log, so evaluation never mixes with real traffic. The run id is only known once the configuration
    # is frozen, so traces are written to a staging folder and moved into the run's folder at the end.
    staging = args.out_root / f"_staging-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    container = build_container(settings.model_copy(update={"trace_dir": staging / "traces"}))
    retriever = container.deps.retriever
    if any(m in ("rag", "rag_peft", "rag_peft_base") for m in modes) and not retriever.ready:
        print("Nothing is indexed yet: run scripts/sync_drive_once.py first.", file=sys.stderr)
        return 2

    llm_calls = len(cases) * len(modes)
    print(f"{len(cases)} cases x {len(modes)} modes = {llm_calls} answers (+ {len(cases)} retrieval embeddings, + routing calls when a message is unclear).")

    ablation = None
    if "rag_peft_base" in modes:
        # Same graph, same retrieval, same prompt: only the model behind Model 3 changes to the base model served on the same endpoint.
        base_name = settings.model3_ablation_model or settings.model3_base_model_id
        client = build_model3_client(settings, served_model=base_name)
        if client is None or not base_name:
            print("rag_peft_base needs Model 3 configured (MODEL3_BASE_URL ... MODEL3_ADAPTER_ID) and MODEL3_ABLATION_MODEL.", file=sys.stderr)
            return 2
        ablation = build_container(settings.model_copy(update={"trace_dir": staging / "traces"}), deps_override=replace(container.deps, model3_llm=client))

    def ask(question: str, mode: str) -> dict:
        target, requested = (ablation, "rag_peft") if mode == "rag_peft_base" and ablation is not None else (container, mode)
        try:
            return target.chat_service.handle(ChatRequest(message=question, model_mode=requested), None).model_dump(mode="json")
        except ChatError as exc:
            raise AskFailed(exc.code, str(exc)) from exc

    rows, retrievals = run_cases(cases, modes, ask, retriever.retrieve, settings.rag_top_k, settings.rag_max_distance)

    with container.session_factory() as session:
        files = [{"source": f.source, "name": f.name, "status": f.status, "chunk_count": f.chunk_count, "content_sha256": f.content_sha256}
                 for f in session.execute(select(IngestedFile)).scalars()]
    describe = retriever.describe()
    chunks = describe.get("chunks")
    config = snapshot_config(
        settings, {m.value if hasattr(m, "value") else str(m): v for m, v in PROMPT_VERSIONS.items()}, args.set, cases, modes,
        index_fingerprint(files, int(chunks) if isinstance(chunks, int) else None), git_state(REPO_ROOT),
    )
    summary = build_summary(rows, retrievals, settings.rag_top_k, settings.rag_max_distance)
    run_dir = args.out_root / config["run_id"]
    paths = write_run(run_dir, config, rows, retrievals, summary)
    if (staging / "traces").is_dir():
        shutil.move(str(staging / "traces"), str(run_dir / "traces"))
    with contextlib.suppress(OSError):
        staging.rmdir()  # only succeeds when empty

    print(f"\nrun {config['run_id']}  (git {str(config['git']['commit'])[:8]}{' + uncommitted changes' if config['git']['dirty'] else ''})")
    k = settings.rag_top_k
    for mode, s in summary["modes"].items():
        print(f"\n[{mode}] n={s['n']} errors={s['errors']}  accuracy={s['answer_accuracy']}  fact_recall={s['fact_recall']}  "
              f"false_refusals={s['false_refusal_rate']}  correct_refusals={s['correct_refusal_rate']}  unsupported={s['unsupported_answer_rate']}")
        print(f"        citation_hit={s['citation_hit_rate']}  hit@{k}={s[f'retrieval_hit_at_{k}']}  mrr={s['retrieval_mrr']}  routed_academic={s['routed_academic_rate']}  "
              f"p50={s['latency_p50_ms']}ms p95={s['latency_p95_ms']}ms  cost=${s['cost_usd_total']}")
        print(f"        context_recall={s['context_recall']} (the proving quote reached the model)  accuracy_when_evidence_present={s['accuracy_when_evidence_present']}")
    print("\ncalibration:", json.dumps(summary["calibration"]))
    print("files:", ", ".join(str(p.relative_to(REPO_ROOT)) for p in paths.values()))

    if args.evidently:
        from subprocess import run

        return run([sys.executable, str(REPO_ROOT / "scripts" / "evidently_report.py"), "evaluation",  # noqa: S603
                    "--results", str(paths["results"]), "--out", str(paths["summary"].parent)], check=False).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

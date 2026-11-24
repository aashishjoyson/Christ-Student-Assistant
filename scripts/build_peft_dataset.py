"""Build the Model 3 (LoRA) training set from the indexed documents, with a hosted model as the teacher, and prove nothing from the evaluation leaks in.

  python scripts/build_peft_dataset.py --dry-run          # counts only: usable passages, held-out passages, estimated cost. Calls nothing.
  python scripts/build_peft_dataset.py --calls 400 --yes  # spends real (small) money: one teacher call per example, one embedding call per search

The adapter teaches BEHAVIOUR (cite [n], say "could not find" when the passages lack the answer), not facts. Each example uses the same prompt format the
app serves (app.domain.prompts.build_rag_messages). Passages that contain a golden-set proving quote are held out completely, and any question close to a
golden question is dropped. Output (data/peft/, git-ignored except the manifest): train.jsonl, val.jsonl ({"messages": [...]} only, what the trainer reads),
*.meta.jsonl (kind, source, passages: for audits) and dataset_manifest.json (counts, drop reasons, hashes, teacher, cost).
Stop the API first if you re-indexed (one writer at a time). Exit codes: 0 done; 2 not ready or confirmation missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.container import build_container  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.domain.documents import RetrievedChunk  # noqa: E402
from app.domain.model_modes import PROMPT_VERSIONS, ModelMode  # noqa: E402
from app.domain.pricing import estimate_cost_usd  # noqa: E402
from app.eval.golden import golden_fingerprint, load_golden  # noqa: E402
from app.eval.peft_builder import BuildConfig, build_examples, usable_chunk  # noqa: E402
from app.eval.peft_data import dataset_sha256, is_holdout_chunk, split_train_val  # noqa: E402
from app.eval.runner import git_state  # noqa: E402

EST_COST_PER_CALL = 0.0005  # a conservative guess for the teacher call (about 1.5k tokens in, a short JSON answer out, low reasoning)


def to_chunk(hit) -> RetrievedChunk:  # type: ignore[no-untyped-def]
    m = hit.metadata
    return RetrievedChunk(chunk_id=hit.id, text=hit.text, source_name=str(m.get("source_name", "")), source_id=str(m.get("source_file_id", "")),
                          page=m.get("page"), section=m.get("section"), source_url=m.get("source_url"), distance=None)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--calls", type=int, default=400, help="teacher calls (each gives one answerable example and often a refusal example)")
    parser.add_argument("--refusal-share", type=float, default=0.55)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--val-fraction", type=float, default=0.1)
    parser.add_argument("--max-cost-usd", type=float, default=0.60, help="stop when the teacher has cost this much")
    parser.add_argument("--golden", type=Path, default=REPO_ROOT / "data" / "eval" / "academic_real.jsonl")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "peft")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true", help="confirm that real API calls may be made")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.primary_configured:
        print("The teacher model is not configured (OPENAI_API_KEY / OPENAI_CHAT_MODEL in .env).", file=sys.stderr)
        return 2
    golden = load_golden(args.golden)
    questions = [g.question for g in golden]
    evidence = [q for g in golden for q in g.evidence]

    container = build_container(settings.model_copy(update={"trace_dir": args.out / "_traces"}))
    retriever, teacher_client = container.deps.retriever, container.deps.primary_llm
    store = getattr(retriever, "_store", None)
    if store is None or not retriever.ready or teacher_client is None:
        print("Nothing is indexed yet (or the teacher is missing): run scripts/sync_drive_once.py first.", file=sys.stderr)
        return 2

    chunks = [to_chunk(h) for h in store.all_chunks()]
    cfg = BuildConfig(calls=args.calls, refusal_share=args.refusal_share, seed=args.seed)
    usable = [c for c in chunks if usable_chunk(c, cfg)]
    held = [c for c in usable if is_holdout_chunk(c.text, evidence)]
    held_ids = {c.chunk_id for c in held}
    per_source = Counter(c.source_name for c in usable if c.chunk_id not in held_ids)
    print(f"{len(chunks)} indexed passages: {len(usable)} usable, {len(held)} held out because they prove a golden answer.")
    print("usable per source:", dict(per_source))
    print(f"plan: {args.calls} teacher calls, about ${args.calls * EST_COST_PER_CALL:.2f} (cap ${args.max_cost_usd:.2f}), "
          f"plus about {args.calls * 2} embedding calls (a few cents).")
    if args.dry_run:
        return 0
    if not args.yes:
        print("This spends real money. Re-run with --yes to proceed.", file=sys.stderr)
        return 2

    spent: dict[str, float] = {"usd": 0.0, "in": 0, "out": 0}

    def neighbours(text: str, k: int) -> list[RetrievedChunk]:
        return retriever.retrieve(text[:1000], k)

    def teacher(messages: list[dict[str, str]]) -> str | None:
        if spent["usd"] >= args.max_cost_usd:
            return None  # the cap is reached: remaining calls are skipped (counted as unparseable)
        try:
            result = teacher_client.complete(messages)
        except Exception as exc:  # noqa: BLE001 - one failed call must not lose the run
            print(f"  teacher call failed: {type(exc).__name__}", file=sys.stderr)
            return None
        spent["usd"] += estimate_cost_usd(result.model, result.input_tokens, result.output_tokens) or 0.0
        spent["calls"] = spent.get("calls", 0) + 1
        if spent["calls"] % 25 == 0:
            print(f"  {spent['calls']} teacher calls, ~${spent['usd']:.3f}", flush=True)
        spent["in"] += result.input_tokens or 0
        spent["out"] += result.output_tokens or 0
        return result.text

    result = build_examples(chunks, questions, evidence, cfg, neighbours, teacher)
    train, val = split_train_val(result.examples, args.val_fraction, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("train", train), ("val", val)):
        write_jsonl(args.out / f"{name}.jsonl", [{"messages": r["messages"]} for r in rows])
        write_jsonl(args.out / f"{name}.meta.jsonl", [r["meta"] for r in rows])
    kinds = Counter(r["meta"]["kind"] for r in result.examples)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(), "git": git_state(REPO_ROOT), "seed": args.seed,
        "prompt_version": PROMPT_VERSIONS[ModelMode.RAG_PEFT],
        "teacher": {"model": settings.primary_chat_model, "calls": result.teacher_calls, "input_tokens": spent["in"], "output_tokens": spent["out"],
                    "est_cost_usd": round(spent["usd"], 4)},
        "golden_set": {"file": args.golden.name, "sha256": golden_fingerprint(args.golden), "questions": len(questions), "held_out_passages": len(held)},
        "examples": {"total": len(result.examples), "answerable": kinds["answerable"], "refusal": kinds["refusal"], "train": len(train), "val": len(val)},
        "per_source": dict(Counter(r["meta"]["source"] for r in result.examples)),
        "dropped": dict(result.dropped),
        "train_sha256": dataset_sha256(train), "val_sha256": dataset_sha256(val),
        "format": "chat messages (system, user, assistant), identical to what the app sends to Model 2/3",
    }
    (args.out / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n{len(result.examples)} examples ({kinds['answerable']} answerable, {kinds['refusal']} refusal) -> train {len(train)}, val {len(val)}")
    print(f"teacher: {result.teacher_calls} calls, ~${spent['usd']:.3f}; dropped: {dict(result.dropped)}")
    print(f"train sha256 {manifest['train_sha256'][:16]}...  manifest: {args.out / 'dataset_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

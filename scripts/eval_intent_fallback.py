"""Live check of the LLM intent fallback: rules-only vs hybrid (rules + LLM) accuracy per phrasing slice.

Calls the configured hosted LLM (a few dozen tiny requests, capped by --max-calls). Needs OPENAI_API_KEY / model in .env,
read by the app's own settings; nothing secret is printed. Synthetic messages only.

Usage (from the repo root, backend venv):  python scripts/eval_intent_fallback.py [--max-calls 40]
Writes storage/eval/<run_id>/intent_fallback.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import STORAGE_DIR, get_settings  # noqa: E402
from app.domain.intent_fallback import build_intent_messages, needs_llm_fallback, parse_intent_label  # noqa: E402
from app.domain.intents import Intent, classify_intent  # noqa: E402
from app.domain.pricing import estimate_cost_usd  # noqa: E402
from app.eval.parity import accuracy_by_slice, gap, load_parity_cases  # noqa: E402
from app.llm.factory import build_primary_client  # noqa: E402

# Ordinary questions that must stay academic even when the gate opens (false-positive control).
CONTROLS = [
    "Tell me about the mail ID of the admissions office",
    "What is the main campus address?",
    "When are MBA interviews held?",
    "What is the application fee for the MBA programme?",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--save-baseline", action="store_true",
                        help="also write data/eval/baselines/parity_intent_hybrid_live.json (a record of this live run)")
    args = parser.parse_args()

    client = build_primary_client(get_settings())
    if client is None:
        print("Primary LLM is not configured (OPENAI_API_KEY + OPENAI_CHAT_MODEL in .env).", file=sys.stderr)
        return 2

    cases = load_parity_cases(REPO_ROOT / "data" / "eval" / "parity_cases.jsonl")
    calls = errors = in_tok = out_tok = 0
    cost = 0.0
    latencies: list[int] = []
    rows: list[dict] = []

    def llm_label(message: str) -> tuple[Intent | None, str | None]:
        nonlocal calls, errors, in_tok, out_tok, cost
        if calls >= args.max_calls:
            raise SystemExit(f"Stopped: reached --max-calls {args.max_calls}")
        calls += 1
        try:
            r = client.complete(build_intent_messages(message))
        except Exception as exc:  # noqa: BLE001 - report every failure kind
            errors += 1
            return None, getattr(exc, "code", type(exc).__name__)
        in_tok += r.input_tokens or 0
        out_tok += r.output_tokens or 0
        cost += estimate_cost_usd(r.model, r.input_tokens, r.output_tokens) or 0.0
        latencies.append(r.latency_ms)
        return parse_intent_label(r.text), None if parse_intent_label(r.text) else f"unparseable:{r.text[:30]!r}"

    for c in cases:
        rules = classify_intent(c.message)
        hybrid, note = rules.intent, None
        used = False
        if rules.rule == "default_academic" and needs_llm_fallback(c.message):
            used = True
            label, note = llm_label(c.message)
            if label is not None and label != Intent.ACADEMIC_QA:
                hybrid = label
        rows.append({"id": c.id, "slice": c.slice, "expected": c.expected_intent, "rules": rules.intent.value,
                     "hybrid": hybrid.value, "llm_used": used, "note": note})

    control_rows = []
    for q in CONTROLS:
        rules = classify_intent(q)
        label = None
        if rules.rule == "default_academic" and needs_llm_fallback(q):
            label, _ = llm_label(q)
        control_rows.append({"question": q, "gate_open": label is not None or needs_llm_fallback(q), "label": label.value if label else None})

    rules_acc = accuracy_by_slice((r["slice"], r["rules"] == r["expected"]) for r in rows)
    hybrid_acc = accuracy_by_slice((r["slice"], r["hybrid"] == r["expected"]) for r in rows)
    print(f"{'slice':12s} {'rules-only':>10s} {'hybrid':>8s}")
    for s in rules_acc:
        print(f"{s:12s} {rules_acc[s]:>10.2f} {hybrid_acc[s]:>8.2f}")
    print(f"gap best-worst: rules-only {gap(rules_acc):.2f} -> hybrid {gap(hybrid_acc):.2f}")
    still_wrong = [r for r in rows if r["hybrid"] != r["expected"]]
    print(f"still wrong after hybrid: {len(still_wrong)}/{len(rows)}")
    for r in still_wrong:
        print(f"  [{r['slice']}] expected {r['expected']}, got {r['hybrid']} (llm_used={r['llm_used']}, note={r['note']})")
    print("controls (must stay academic_qa):", [(x["question"][:40], x["label"]) for x in control_rows if x["label"] is not None] or "gate closed or labelled academic")
    avg = sum(latencies) / len(latencies) if latencies else 0
    print(f"LLM calls: {calls} (errors {errors}) | tokens in/out: {in_tok}/{out_tok} | est. cost: ${cost:.5f} | avg latency: {avg:.0f} ms | model: {client.model}")

    out_dir = STORAGE_DIR / "eval" / datetime.now(UTC).strftime("intent_%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "intent_fallback.json").write_text(json.dumps({
        "model": client.model, "calls": calls, "errors": errors, "input_tokens": in_tok, "output_tokens": out_tok,
        "est_cost_usd": round(cost, 6), "rules_only": rules_acc, "hybrid": hybrid_acc, "rows": rows, "controls": control_rows,
        "created": datetime.now(UTC).isoformat(),
    }, indent=1), encoding="utf-8")
    print("saved:", out_dir / "intent_fallback.json")
    if args.save_baseline:
        record = REPO_ROOT / "data" / "eval" / "baselines" / "parity_intent_hybrid_live.json"
        record.write_text(json.dumps({
            "created": datetime.now(UTC).date().isoformat(),
            "metric": "share of messages routed to the expected intent, per phrasing slice: deterministic rules + gated LLM fallback (ADR-015)",
            "note": "A record of ONE live run (LLM output is not deterministic); CI does not call the LLM. Re-run the script to refresh.",
            "model": client.model, "llm_calls": calls, "errors": errors, "est_cost_usd": round(cost, 6),
            "rules_only": rules_acc, "hybrid": hybrid_acc, "gap_rules_only": gap(rules_acc), "gap_hybrid": gap(hybrid_acc),
            "still_wrong": len(still_wrong),
        }, indent=2) + "\n", encoding="utf-8", newline="\n")
        print("recorded:", record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

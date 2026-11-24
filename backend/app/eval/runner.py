"""Evaluation run: ask every golden question in every mode, score the answers, freeze the configuration, write the artefacts.

The core takes the two things it needs as plain functions (`ask`, `retrieve`), so tests drive it with fakes and the CLI
(scripts/run_evaluation.py) drives it against the real system. Nothing here imports Evidently or any network library.

An evaluation run is only comparable with another if the configuration is known, so every run writes a frozen snapshot: git commit,
prompt versions, model ids, embedding model, retrieval settings, a hash of the golden file and a fingerprint of the indexed documents.
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import re
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.eval.golden import GoldenCase, golden_fingerprint
from app.eval.metrics import calibrate_threshold, score_row, summarize

RAG_MODES = frozenset({"rag", "rag_peft"})


class AskFailed(Exception):
    """The system answered with an error (for example Model 3 not configured). The run records it and carries on."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class _Chunk(Protocol):
    source_name: str
    text: str
    distance: float | None


Ask = Callable[[str, str], dict[str, Any]]  # (question, mode) -> {answer, citations, usage, intent, handled_by, grounded}
Retrieve = Callable[[str, int], Sequence[_Chunk]]


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def evidence_in_context(case: GoldenCase, chunks: Sequence[_Chunk]) -> bool | None:
    """Did the retrieved passages contain the quotes that prove the answer? None for cases without evidence (unanswerable ones)."""
    if not case.evidence:
        return None
    context = _squash(" ".join(c.text for c in chunks))
    return all(_squash(quote) in context for quote in case.evidence)


def run_cases(cases: Sequence[GoldenCase], modes: Sequence[str], ask: Ask, retrieve: Retrieve | None, top_k: int,
              max_distance: float | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (rows, retrieval): one scored row per (case, mode), and one retrieval record per case (used to calibrate the cut-off)."""
    rows: list[dict[str, Any]] = []
    retrievals: list[dict[str, Any]] = []
    for case in cases:
        chunks = list(retrieve(case.question, top_k)) if retrieve else []
        sources = [c.source_name for c in chunks]
        distances = [c.distance for c in chunks if c.distance is not None]
        top1 = min(distances) if distances else None  # the best vector match: what the "nothing relevant" cut-off is compared with
        given = [c for c in chunks if c.distance is None or max_distance is None or c.distance <= max_distance]  # what the model is given
        supplied = len(given)
        in_context = evidence_in_context(case, given) if retrieve else None
        retrievals.append({"case_id": case.id, "category": case.category, "answerable": case.answerable, "top1_distance": top1,
                           "retrieved_sources": sources, "evidence_in_context": in_context})
        for mode in modes:
            row: dict[str, Any] = {
                "mode": mode, "case_id": case.id, "category": case.category, "question": case.question, "answerable": case.answerable,
                "expected_sources": list(case.expected_sources), "expected_facts": list(case.expected_facts), "rag": mode in RAG_MODES,
                "retrieved_sources": sources if mode in RAG_MODES else [], "top1_distance": top1 if mode in RAG_MODES else None,
                "passages_supplied": supplied if mode in RAG_MODES else 0,
                "evidence_in_context": in_context if mode in RAG_MODES else None,
            }
            try:
                response = ask(case.question, mode)
            except AskFailed as exc:
                row |= {"answer": "", "citations": [], "intent": None, "error_code": exc.code, "latency_ms": None, "input_tokens": None,
                        "output_tokens": None, "est_cost_usd": None, "model": None, "grounded": None}
            else:
                usage = response.get("usage", {})
                row |= {
                    "answer": response.get("answer", ""), "citations": response.get("citations", []), "intent": response.get("intent"),
                    "error_code": None, "latency_ms": usage.get("latency_ms"), "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"), "est_cost_usd": usage.get("est_cost_usd"),
                    "model": (response.get("handled_by") or {}).get("model"), "grounded": response.get("grounded"),
                }
            row |= score_row(row)
            rows.append(row)
    return rows, retrievals


def build_summary(rows: Sequence[dict[str, Any]], retrievals: Sequence[dict[str, Any]], top_k: int, current_max_distance: float | None) -> dict[str, Any]:
    answerable = [r["top1_distance"] for r in retrievals if r["answerable"] and r["top1_distance"] is not None]
    unanswerable = [r["top1_distance"] for r in retrievals if not r["answerable"] and r["top1_distance"] is not None]
    return {"modes": summarize(rows, top_k), "calibration": calibrate_threshold(answerable, unanswerable, current_max_distance)}


def git_state(repo_root: Path) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            done = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=False, timeout=10)  # noqa: S603, S607
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    sha, status = run("rev-parse", "HEAD"), run("status", "--porcelain")
    return {"commit": sha, "dirty": bool(status) if status is not None else None}


def index_fingerprint(files: Sequence[dict[str, Any]], chunk_count: int | None) -> dict[str, Any]:
    """Which documents (and which versions of them) the answers were produced from. `files`: name, source, status, chunk_count, content_sha256."""
    listing = sorted(
        ({"source": f["source"], "name": f["name"], "chunks": f["chunk_count"], "content_sha256": f.get("content_sha256")}
         for f in files if f["status"] == "indexed"),
        key=lambda f: (f["source"], f["name"]),
    )
    digest = hashlib.sha256(json.dumps(listing, sort_keys=True).encode()).hexdigest()
    return {"chunks_in_store": chunk_count, "files": listing, "sha256": digest}


def snapshot_config(
    settings: Any, prompt_versions: dict[str, str], golden_path: Path, cases: Sequence[GoldenCase], modes: Sequence[str],
    index: dict[str, Any], git: dict[str, Any], now: datetime | None = None,
) -> dict[str, Any]:
    """Everything that can change an answer, in one dict. Never contains a key or a secret (only model ids and numbers)."""
    now = now or datetime.now(UTC)
    config = {
        "created_at": now.isoformat(), "git": git, "python": platform.python_version(), "modes": list(modes),
        "prompt_versions": prompt_versions,
        "llm": {"provider": settings.llm_provider, "model": settings.primary_chat_model, "reasoning_effort": settings.llm_reasoning_effort,
                "max_output_tokens": settings.llm_max_output_tokens, "temperature": settings.llm_temperature,
                "intent_llm_fallback": settings.intent_llm_fallback},
        "model3": {"configured": settings.model3_configured, "model": settings.model3_model or None,
                   "base_model_id": settings.model3_base_model_id or None, "adapter_id": settings.model3_adapter_id or None},
        "retrieval": {"embedding_model": settings.openai_embedding_model, "top_k": settings.rag_top_k, "max_distance": settings.rag_max_distance,
                      "lexical_weight": settings.rag_lexical_weight, "candidate_pool": settings.rag_candidate_pool,
                      "chunk_size": settings.rag_chunk_size, "chunk_overlap": settings.rag_chunk_overlap,
                      "no_evidence_short_circuit": settings.rag_no_evidence_short_circuit},
        "golden_set": {"file": golden_path.name, "sha256": golden_fingerprint(golden_path), "cases": len(cases),
                       "answerable": sum(c.answerable for c in cases)},
        "index": index,
    }
    config["run_id"] = make_run_id(now, config)
    return config


def make_run_id(now: datetime, config: dict[str, Any]) -> str:
    stable = {k: v for k, v in config.items() if k not in {"created_at", "run_id"}}
    short = hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()[:6]
    return f"eval-{now.strftime('%Y%m%d-%H%M%S')}-{short}"


def write_run(out_dir: Path, config: dict[str, Any], rows: Sequence[dict[str, Any]], retrievals: Sequence[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"config": out_dir / "config.json", "summary": out_dir / "summary.json", "results": out_dir / "results.jsonl",
             "results_csv": out_dir / "results.csv", "retrieval": out_dir / "retrieval.jsonl"}
    paths["config"].write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["summary"].write_text(json.dumps({"run_id": config["run_id"], **summary}, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["results"].write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    paths["retrieval"].write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in retrievals) + "\n", encoding="utf-8")
    flat = [{k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in r.items()} for r in rows]
    columns = list(dict.fromkeys(k for r in flat for k in r))
    with paths["results_csv"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(flat)
    return paths

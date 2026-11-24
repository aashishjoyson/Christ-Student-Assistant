"""Prove the golden set against the real documents, so no expected fact is invented.

For every answerable case, each `evidence` quote must occur literally in an expected source file. For every unanswerable case, none of
its `absent_terms` may occur in ANY document (that is what makes "not in the documents" the correct answer).
Whitespace is ignored when comparing (PDF line breaks), nothing else is.

Usage (repo root, backend venv):  python scripts/check_golden_set.py [--set data/eval/academic_real.jsonl] [--docs data/sample_docs]
Exit code 1 on any failure. Files named SYNTHETIC_* are placeholders and are not part of the real corpus.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.eval.golden import load_golden  # noqa: E402
from app.rag.parsers import is_supported, mime_for_name, parse  # noqa: E402


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def load_corpus(folder: Path) -> dict[str, str]:
    corpus: dict[str, str] = {}
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.name.startswith("SYNTHETIC_") or not is_supported(mime_for_name(path.name)):
            continue
        sections = parse(path.read_bytes(), mime_for_name(path.name), path.name)
        corpus[path.name] = squash(" ".join(f"{s.section or ''} {s.text}" for s in sections))
    return corpus


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", type=Path, default=REPO_ROOT / "data" / "eval" / "academic_real.jsonl")
    parser.add_argument("--docs", type=Path, default=REPO_ROOT / "data" / "sample_docs")
    args = parser.parse_args()

    cases = load_golden(args.set)
    corpus = load_corpus(args.docs)
    print(f"{len(cases)} cases; corpus: {', '.join(f'{n} ({len(t):,} chars)' for n, t in corpus.items())}")
    problems: list[str] = []
    for case in cases:
        if case.answerable:
            for source in case.expected_sources:
                if source not in corpus:
                    problems.append(f"{case.id}: expected source '{source}' is not in {args.docs}")
            haystacks = [corpus[s] for s in case.expected_sources if s in corpus]
            if not case.evidence:
                problems.append(f"{case.id}: no evidence quotes")
            for quote in case.evidence:
                if not any(squash(quote) in h for h in haystacks):
                    problems.append(f"{case.id}: evidence not found literally in {list(case.expected_sources)}: {quote!r}")
        else:
            if not case.absent_terms:
                problems.append(f"{case.id}: an unanswerable case needs absent_terms")
            for term in case.absent_terms:
                found = [name for name, text in corpus.items() if squash(term).lower() in text.lower()]
                if found:
                    problems.append(f"{case.id}: '{term}' IS present in {found}, so this question may be answerable")
    if problems:
        print("Golden set check FAILED:\n  " + "\n  ".join(problems))
        return 1
    answerable = sum(c.answerable for c in cases)
    print(f"Golden set check passed: {answerable} answerable cases proven by quotes, {len(cases) - answerable} unanswerable cases proven absent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

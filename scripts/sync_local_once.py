"""Index the local documents folder (LOCAL_DOCS_DIR, default data/sample_docs) into Chroma.

Usage (from the repo root, backend venv):
  python scripts/sync_local_once.py --dry-run   # parse + chunk only: prints chunk counts and the estimated embedding cost.
                                                # Nothing is sent to OpenAI and nothing is written.
  python scripts/sync_local_once.py             # real sync: sends the text chunks to OpenAI for embeddings (needs OPENAI_API_KEY)

Re-running is cheap: unchanged files are skipped without any embedding call.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.container import build_rag  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import init_db, make_engine, make_session_factory  # noqa: E402
from app.domain.chunking import chunk_sections  # noqa: E402
from app.rag.ingest import estimate_embedding_cost  # noqa: E402
from app.rag.parsers import ParseError, is_supported, parse  # noqa: E402
from app.rag.sources.local_folder import LocalFolderSource  # noqa: E402


def dry_run() -> int:
    s = get_settings()
    source = LocalFolderSource(s.local_docs_dir, include_synthetic=s.local_docs_include_synthetic)
    total_chunks = total_chars = 0
    for f in source.list_files():
        if not is_supported(f.mime_type):
            print(f"  SKIP   {f.name}: unsupported type ({f.mime_type})")
            continue
        try:
            content, mime = source.fetch(f)
            sections = parse(content, mime, f.name)
            chunks = chunk_sections(f.source_file_id, sections, s.rag_chunk_size, s.rag_chunk_overlap)
        except ParseError as exc:
            print(f"  FAIL   {exc}")
            continue
        chars = sum(len(c.text) for c in chunks)
        pages = sorted({c.page for c in chunks if c.page is not None})
        total_chunks, total_chars = total_chunks + len(chunks), total_chars + chars
        print(f"  OK     {f.name}: {len(sections)} sections, {len(chunks)} chunks, ~{chars // 4:,} tokens"
              + (f", pages {pages[0]}-{pages[-1]}" if pages else ""))
    tokens = total_chars // 4
    cost = estimate_embedding_cost(s.openai_embedding_model, tokens)
    cost_text = f"${cost:.4f}" if cost is not None else "unknown"
    print(f"TOTAL: {total_chunks} chunks, ~{tokens:,} tokens -> estimated embedding cost {cost_text} "
          f"({s.openai_embedding_model}). Dry run: nothing was sent or written.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        return dry_run()

    s = get_settings()
    engine = make_engine(s.database_url)
    init_db(engine)
    ingestion = build_rag(s, make_session_factory(engine)).local
    if ingestion is None:
        print("OPENAI_API_KEY is not set (needed for embeddings).", file=sys.stderr)
        return 2
    r = ingestion.sync("manual")
    cost = estimate_embedding_cost(s.openai_embedding_model, r.embed_tokens)
    print(f"sync {r.status}: seen {r.files_seen}, indexed {r.files_indexed}, skipped {r.files_skipped}, failed {r.files_failed}, "
          f"unsupported {r.files_unsupported}, deleted {r.files_deleted}")
    print(f"embeddings: {r.embed_calls} calls, {r.embed_tokens:,} tokens, ~${cost if cost is not None else 'n/a'}")
    if r.error:
        print("error:", r.error)
    return 0 if r.status in ("succeeded", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())

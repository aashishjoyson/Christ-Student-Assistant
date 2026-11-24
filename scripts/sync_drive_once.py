"""Sync the Google Drive folder into the search index (the same engine the automatic poller uses).

Usage (from the repo root, backend venv):
  python scripts/sync_drive_once.py --dry-run     # connect and LIST the folder only: nothing is downloaded, embedded or written
  python scripts/sync_drive_once.py               # real sync: downloads changed files and sends their text to OpenAI for embeddings
  python scripts/sync_drive_once.py --purge-local # first remove the local-folder documents from the index (when Drive becomes the
                                                  # source of truth, so the same document is not answered from two places)
--folder-id and --credentials override .env for a first test. Unchanged files are skipped without any download or embedding.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.container import build_rag  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.models import IngestedFile  # noqa: E402
from app.db.session import init_db, make_engine, make_session_factory  # noqa: E402
from app.rag.ingest import estimate_embedding_cost  # noqa: E402
from app.rag.parsers import is_supported  # noqa: E402
from app.rag.sources.google_drive import DriveError, GoogleDriveSource, build_drive_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--purge-local", action="store_true")
    parser.add_argument("--folder-id")
    parser.add_argument("--credentials", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    overrides: dict[str, object] = {}
    if args.folder_id:
        overrides["google_drive_folder_id"] = args.folder_id
    if args.credentials:
        overrides["google_drive_credentials_file"] = args.credentials.resolve()
    if not overrides.get("google_drive_credentials_file") and not settings.google_drive_credentials_file:
        overrides["google_drive_credentials_file"] = REPO_ROOT / "secrets" / "drive-service-account.json"  # the documented default
    settings = settings.model_copy(update=overrides)

    if not settings.google_drive_folder_id:
        print("No folder id: set GOOGLE_DRIVE_FOLDER_ID in .env or pass --folder-id.", file=sys.stderr)
        return 2

    if args.dry_run:
        try:
            service = build_drive_service(settings.google_drive_auth_mode, settings.google_drive_credentials_file,
                                          settings.google_drive_token_file)
            source = GoogleDriveSource(settings.google_drive_folder_id, service)
            files = source.list_files()
        except DriveError as exc:
            print(f"Drive problem: {exc}", file=sys.stderr)
            return 1
        print(f"Connected. The folder contains {len(files)} file(s) (sub-folders and shortcuts are ignored):")
        for f in files:
            kind = "Google-native (exported)" if f.mime_type.startswith("application/vnd.google-apps") else "binary"
            size = f"{f.size_bytes / 1024:,.0f} KB" if f.size_bytes else "n/a"
            print(f"  {'INDEXABLE ' if is_supported(f.mime_type) else 'UNSUPPORTED'} {f.name}  [{kind}, {size}]")
        if source.ignored:
            print(f"Ignored {len(source.ignored)} sub-folder(s)/shortcut(s): {', '.join(source.ignored[:5])}. "
                  "Files inside sub-folders are not read: move them directly into the folder.")
        elif not files:
            print("The folder is empty. Upload the documents (PDF, DOCX, XLSX, CSV, TXT, MD or Google Docs/Sheets) directly into it.")
        print("Dry run: nothing was downloaded, sent or written.")
        return 0

    engine = make_engine(settings.database_url)
    init_db(engine)
    parts = build_rag(settings, make_session_factory(engine))
    if parts.drive is None:
        print(f"Drive is not available: {parts.drive_error or 'OPENAI_API_KEY is missing (needed for embeddings).'}", file=sys.stderr)
        return 2
    if args.purge_local and parts.local is not None:
        print(f"Removed {parts.local.purge()} local-folder document(s) from the index.")
    r = parts.drive.sync("manual")
    cost = estimate_embedding_cost(settings.openai_embedding_model, r.embed_tokens)
    print(f"sync {r.status}: seen {r.files_seen}, indexed {r.files_indexed}, skipped {r.files_skipped}, failed {r.files_failed}, "
          f"unsupported {r.files_unsupported}, deleted {r.files_deleted}")
    print(f"embeddings: {r.embed_calls} calls, {r.embed_tokens:,} tokens, ~${cost if cost is not None else 'n/a'}")
    if r.error:
        print("error:", r.error)
    with make_session_factory(engine)() as session:
        for row in session.execute(select(IngestedFile).where(IngestedFile.source == "drive").order_by(IngestedFile.name)).scalars():
            note = f" - {row.last_error}" if row.last_error else ""
            print(f"  {row.status:11s} {row.name} ({row.chunk_count} chunks){note}")
    return 0 if r.status in ("succeeded", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())

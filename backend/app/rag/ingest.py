"""Ingestion: DocumentSource -> parse -> chunk -> embed -> Chroma, with change detection (ARCHITECTURE section 6).

Guarantees (each has a test):
- unchanged file: nothing is downloaded or embedded, chunk ids stay identical (AC-06.1)
- changed file: the NEW version is embedded and upserted first, only then are the old chunks deleted (AC-06.2)
- a failure on update keeps serving the old version; the row is marked failed with an error (AC-06.3)
- a file missing from the source is removed from the index and marked deleted (AC-06.4)
- unsupported types are reported, not retried as failures (AC-06.5)
- only one sync runs at a time
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core import flow
from app.db.models import IngestedFile, SyncRun
from app.domain.chunking import chunk_sections
from app.domain.clock import utcnow
from app.domain.pricing import PRICES_PER_MILLION
from app.rag.base import DocumentSource, SourceFile
from app.rag.embeddings import Embedder, EmbeddingError
from app.rag.parsers import ParseError, is_supported, parse
from app.rag.vector_store import ChromaStore

log = logging.getLogger("rag.ingest")


class SyncAlreadyRunning(Exception):
    """A sync is already in progress (single-flight)."""


@dataclass
class SyncResult:
    run_id: int
    status: str
    files_seen: int = 0
    files_indexed: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    files_deleted: int = 0
    files_unsupported: int = 0
    embed_calls: int = 0
    embed_tokens: int = 0
    error: str | None = None


def estimate_embedding_cost(model: str, tokens: int) -> float | None:
    prices = PRICES_PER_MILLION.get(model)
    return None if prices is None else round(tokens * prices[0] / 1_000_000, 6)


class IngestionService:
    def __init__(
        self,
        source: DocumentSource,
        embedder: Embedder,
        store: ChromaStore,
        session_factory: sessionmaker[Session],
        *,
        chunk_size: int = 900,
        chunk_overlap: int = 120,
        now: Callable[[], datetime] = utcnow,
        lock: threading.Lock | None = None,
    ) -> None:
        self._source = source
        self._embedder = embedder
        self._store = store
        self._session_factory = session_factory
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._now = now
        self._lock = lock or threading.Lock()  # share one lock across sources so two syncs never write to Chroma at once

    # ------------------------------------------------------------------ public
    def sync(self, trigger: str = "manual", force: bool = False) -> SyncResult:
        """force=True re-reads and re-parses every file even if the source says it did not change. Use it after changing the parser or
        chunker: a file is only re-embedded if its chunks actually differ from what is stored, so unchanged output costs nothing."""
        if not self._lock.acquire(blocking=False):
            raise SyncAlreadyRunning("a sync is already running")
        try:
            return self._sync(trigger, force)
        finally:
            self._lock.release()

    def purge(self) -> int:
        """Remove everything THIS source has indexed (chunks and bookkeeping). Used when the source of truth changes, e.g. from the
        local folder to Drive, so the same document is not answered from two places. Returns the number of files removed."""
        if not self._lock.acquire(blocking=False):
            raise SyncAlreadyRunning("a sync is already running")
        try:
            with self._session_factory() as session:
                rows = list(session.execute(select(IngestedFile).where(
                    IngestedFile.source == self._source.name, IngestedFile.status != "deleted")).scalars())
                for row in rows:
                    self._store.delete_file(row.source_file_id)
                    row.status, row.active_version, row.chunk_count, row.last_error = "deleted", None, 0, None
                session.commit()
                return len(rows)
        finally:
            self._lock.release()

    # ------------------------------------------------------------------ internals
    def _sync(self, trigger: str, force: bool = False) -> SyncResult:
        with self._session_factory() as session:
            run = SyncRun(source=self._source.name, trigger=trigger, started_at=self._now())
            session.add(run)
            session.commit()
            result = SyncResult(run_id=run.id, status="running")
            trace = f"sync-{run.id}"
            where = "drive" if "drive" in self._source.name.lower() else "ingest"
            flow.emit("ingest", "sync", "start", "ingest" if trigger == "manual" else "poller", f"Sync started ({trigger})", trace_id=trace,
                      detail={"source": self._source.name, "trigger": trigger, "force": force})
            try:
                listed = self._source.list_files()
            except Exception as exc:
                flow.emit("ingest", "list", "error", where, "Could not list the source", trace_id=trace, detail={"error": type(exc).__name__})
                return self._finish(session, run, result, "failed", f"could not list the source ({type(exc).__name__}: {exc})")

            result.files_seen = len(listed)
            flow.emit("ingest", "list", "end", where, f"Listed {len(listed)} files in the source", trace_id=trace, detail={"files": len(listed)})
            rows = {r.source_file_id: r for r in session.execute(
                select(IngestedFile).where(IngestedFile.source == self._source.name)).scalars()}

            for file in listed:
                try:
                    outcome = self._process(session, file, rows.get(file.source_file_id), result, force)
                except Exception as exc:  # one bad file must never stop the sync or lose the old version
                    session.rollback()
                    outcome = "failed"
                    self._mark_failed(session, file, rows.get(file.source_file_id), self._safe_error(exc))
                    log.warning("ingest failed for %s: %s", file.name, type(exc).__name__)
                session.commit()
                flow.emit("ingest", "file", "error" if outcome == "failed" else "end", "ingest", f"{file.name}: {outcome}", trace_id=trace,
                          detail={"outcome": outcome})
                counter = f"files_{outcome}"
                setattr(result, counter, getattr(result, counter) + 1)

            listed_ids = {f.source_file_id for f in listed}
            for row in rows.values():
                if row.source_file_id not in listed_ids and row.status != "deleted":
                    try:
                        self._store.delete_file(row.source_file_id)
                    except Exception as exc:
                        log.warning("could not delete chunks of a removed file: %s", type(exc).__name__)
                        continue
                    row.status, row.active_version, row.chunk_count, row.last_error = "deleted", None, 0, None
                    result.files_deleted += 1
            session.commit()

            failed, ok = result.files_failed, result.files_indexed + result.files_skipped + result.files_unsupported
            status = "succeeded" if failed == 0 else ("partial" if ok > 0 else "failed")
            finished = self._finish(session, run, result, status, None)
            flow.emit("ingest", "sync", "error" if status == "failed" else "end", "ingest",
                      f"Sync {status}: {result.files_indexed} indexed, {result.files_skipped} unchanged, {result.files_deleted} removed, {result.files_failed} failed",
                      trace_id=trace, detail={"status": status, "indexed": result.files_indexed, "unchanged": result.files_skipped,
                                              "removed": result.files_deleted, "failed": result.files_failed, "embed_tokens": result.embed_tokens})
            return finished

    def _finish(self, session: Session, run: SyncRun, result: SyncResult, status: str, error: str | None) -> SyncResult:
        run.finished_at = self._now()
        run.status, run.error = status, error
        run.files_seen, run.files_indexed = result.files_seen, result.files_indexed
        run.files_skipped = result.files_skipped + result.files_unsupported
        run.files_failed, run.files_deleted = result.files_failed, result.files_deleted
        session.commit()
        result.status, result.error = status, error
        return result

    def _process(self, session: Session, file: SourceFile, row: IngestedFile | None, result: SyncResult, force: bool = False) -> str:
        if row is None:
            row = IngestedFile(source=self._source.name, source_file_id=file.source_file_id, name=file.name,
                               mime_type=file.mime_type, status="pending")
            session.add(row)
        elif row.status == "deleted":  # the file reappeared: treat it as new
            row.status, row.active_version, row.chunk_count, row.content_sha256, row.remote_checksum = "pending", None, 0, None, None
        row.name, row.mime_type, row.source_url, row.modified_time = file.name, file.mime_type, file.source_url, file.modified_time

        if not is_supported(file.mime_type):
            if row.active_version:  # was indexed under a supported type; it must not keep answering
                self._store.delete_file(file.source_file_id)
                row.active_version, row.chunk_count = None, 0
            row.status, row.last_error = "unsupported", f"unsupported file type ({file.mime_type})"
            return "unsupported"

        indexed = row.status == "indexed" and bool(row.active_version)
        if indexed and not force and file.remote_checksum is not None and row.remote_checksum == file.remote_checksum:
            return "skipped"  # cheap check: nothing downloaded, nothing embedded

        content, mime = self._source.fetch(file)
        sha = hashlib.sha256(content).hexdigest()
        if indexed and not force and row.content_sha256 == sha:
            row.remote_checksum = file.remote_checksum  # metadata changed, content did not
            return "skipped"

        chunks = chunk_sections(file.source_file_id, parse(content, mime, file.name), self._chunk_size, self._chunk_overlap)
        if not chunks:
            raise ParseError(f"{file.name}: no extractable text")
        version = chunks[0].version
        if indexed and row.active_version == version:
            row.content_sha256, row.remote_checksum = sha, file.remote_checksum  # bytes differ, text identical
            return "skipped"

        embedded = self._embedder.embed([c.text for c in chunks])  # everything is embedded BEFORE the store is touched
        result.embed_calls += embedded.calls
        result.embed_tokens += embedded.tokens
        metadatas: list[dict[str, Any]] = []
        for c in chunks:
            meta: dict[str, Any] = {"source": self._source.name, "source_file_id": file.source_file_id,
                                    "source_name": file.name, "version": version, "chunk_index": c.index}
            for key, value in (("source_url", file.source_url), ("page", c.page), ("section", c.section),
                               ("modified_time", file.modified_time.isoformat() if file.modified_time else None)):
                if value is not None:
                    meta[key] = value
            metadatas.append(meta)
        try:
            self._store.upsert([c.chunk_id for c in chunks], embedded.vectors, [c.text for c in chunks], metadatas)
            self._store.delete_other_versions(file.source_file_id, version)  # old version goes only after the new one is in
        except Exception:
            if version != row.active_version:  # do not leave half a new version behind
                try:
                    self._store.delete_version(file.source_file_id, version)
                except Exception:
                    log.warning("could not clean up a partial version")
            raise
        row.status, row.active_version, row.chunk_count = "indexed", version, len(chunks)
        row.content_sha256, row.remote_checksum, row.last_error, row.indexed_at = sha, file.remote_checksum, None, self._now()
        return "indexed"

    def _mark_failed(self, session: Session, file: SourceFile, row: IngestedFile | None, message: str) -> None:
        """Record the failure. `active_version` is left alone, so an older good version keeps being served."""
        existing = session.execute(select(IngestedFile).where(
            IngestedFile.source == self._source.name, IngestedFile.source_file_id == file.source_file_id)).scalar_one_or_none()
        target = existing or IngestedFile(source=self._source.name, source_file_id=file.source_file_id, name=file.name,
                                          mime_type=file.mime_type)
        if existing is None:
            session.add(target)
        target.name, target.mime_type = file.name, file.mime_type
        target.status, target.last_error = "failed", message

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, ParseError | EmbeddingError):
            return str(exc)[:300]  # these messages are written to be safe (no file content)
        return f"{type(exc).__name__}: {str(exc)[:200]}"

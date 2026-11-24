"""Phase 2: local-folder ingestion into a real (temporary) Chroma store with a fake embedder. No network, no paid API."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.container import build_container
from app.db.models import IngestedFile, SyncRun
from app.db.session import init_db, make_engine, make_session_factory
from app.graph.deps import GraphDeps
from app.main import create_app
from app.rag.ingest import IngestionService, SyncAlreadyRunning
from app.rag.retriever import ChromaRetriever
from app.rag.sources.local_folder import LocalFolderSource
from app.rag.vector_store import ChromaStore, EmbeddingModelMismatch
from tests.doc_factory import make_docx, make_pdf, make_xlsx
from tests.fakes import FakeChatClient, FakeEmbedder, RecordingEmailProvider
from tests.integration.conftest import make_settings


@dataclass
class Rig:
    docs: Path
    tmp: Path
    session_factory: object
    embedder: FakeEmbedder
    store: ChromaStore
    service: IngestionService

    def rows(self) -> dict[str, IngestedFile]:
        with self.session_factory() as s:  # type: ignore[operator]
            return {r.name: r for r in s.execute(select(IngestedFile)).scalars()}

    def retriever(self) -> ChromaRetriever:
        return ChromaRetriever(self.embedder, self.store)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    docs = tmp_path / "docs"
    docs.mkdir()
    engine = make_engine(f"sqlite:///{(tmp_path / 'ingest.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)
    embedder = FakeEmbedder()
    store = ChromaStore(tmp_path / "chroma", "test_docs", embedder.model)
    service = IngestionService(LocalFolderSource(docs), embedder, store, factory, chunk_size=300, chunk_overlap=40)
    return Rig(docs, tmp_path, factory, embedder, store, service)


def populate(docs: Path) -> None:
    (docs / "calendar.pdf").write_bytes(make_pdf(["Term one starts in July for all programmes.", "Examinations are held in November."]))
    (docs / "rules.docx").write_bytes(make_docx([("h1", "Attendance"), ("p", "Students must keep 85 percent attendance every term.")]))
    (docs / "notes.md").write_bytes(b"# Hostel\nHostel curfew is at ten in the evening.\n")
    (docs / "courses.xlsx").write_bytes(make_xlsx({"c": [["Course Name", "Fees"], ["MBA", "Fees are payable per semester and include library access. " * 3]]}))
    (docs / "tool.exe").write_bytes(b"MZ\x90\x00 not a document")


def all_ids(rig: Rig) -> list[str]:
    return sorted(i for name in ("calendar.pdf", "rules.docx", "notes.md", "courses.xlsx") for i in rig.store.ids_for_file(name))


# ---------------- first sync ----------------
def test_first_sync_indexes_supported_files_with_citation_metadata(rig: Rig) -> None:
    populate(rig.docs)
    r = rig.service.sync("manual")
    assert r.status == "succeeded" and (r.files_seen, r.files_indexed, r.files_unsupported, r.files_failed) == (5, 4, 1, 0)
    rows = rig.rows()
    assert {n: row.status for n, row in rows.items()} == {"calendar.pdf": "indexed", "rules.docx": "indexed", "notes.md": "indexed",
                                                         "courses.xlsx": "indexed", "tool.exe": "unsupported"}
    assert all(rows[n].chunk_count > 0 and rows[n].active_version for n in ("calendar.pdf", "rules.docx", "notes.md", "courses.xlsx"))
    hits = rig.retriever().retrieve("when are examinations held in november", 2)
    assert (hits[0].source_name, hits[0].page, hits[0].source_id) == ("calendar.pdf", 2, "calendar.pdf")
    heading = rig.retriever().retrieve("attendance every term", 1)[0]
    assert (heading.source_name, heading.section) == ("rules.docx", "Attendance")
    row_hit = rig.retriever().retrieve("MBA fees payable per semester library", 1)[0]
    assert row_hit.source_name == "courses.xlsx" and row_hit.text.startswith("Course Name: MBA")  # row identity is in the chunk text
    with rig.session_factory() as s:  # type: ignore[operator]
        run = s.execute(select(SyncRun)).scalar_one()
    assert (run.status, run.files_seen, run.files_indexed, run.files_skipped) == ("succeeded", 5, 4, 1)  # unsupported counts as skipped


# ---------------- AC-06.1 unchanged re-sync ----------------
def test_unchanged_resync_makes_no_embedding_calls_and_keeps_identical_chunks(rig: Rig) -> None:
    populate(rig.docs)
    rig.service.sync("manual")
    ids_before, calls_before, count_before = all_ids(rig), rig.embedder.calls, rig.store.count()
    r = rig.service.sync("manual")
    assert rig.embedder.calls == calls_before and r.embed_calls == 0 and r.files_indexed == 0
    assert r.files_skipped == 4 and all_ids(rig) == ids_before and rig.store.count() == count_before


def test_same_text_in_different_bytes_is_not_re_embedded(rig: Rig) -> None:
    (rig.docs / "notes.md").write_bytes(b"# Hostel\nCurfew is at ten.\n")
    rig.service.sync("manual")
    calls = rig.embedder.calls
    (rig.docs / "notes.md").write_bytes(b"# Hostel\n\n\nCurfew   is at ten.   \n\n")  # whitespace only
    r = rig.service.sync("manual")
    assert rig.embedder.calls == calls and r.files_skipped == 1 and r.files_indexed == 0


# ---------------- AC-06.2 modified file ----------------
def test_modified_file_replaces_the_old_version_completely(rig: Rig) -> None:
    populate(rig.docs)
    rig.service.sync("manual")
    old_ids, old_version = rig.store.ids_for_file("rules.docx"), rig.rows()["rules.docx"].active_version
    (rig.docs / "rules.docx").write_bytes(make_docx([("h1", "Attendance"), ("p", "Students must keep 90 percent attendance every term.")]))
    r = rig.service.sync("manual")
    new_ids, row = rig.store.ids_for_file("rules.docx"), rig.rows()["rules.docx"]
    assert r.files_indexed == 1 and row.active_version != old_version
    assert new_ids and not set(new_ids) & set(old_ids)  # only the new version is present
    assert all(row.active_version in i for i in new_ids)
    top = rig.retriever().retrieve("attendance every term", 1)[0]
    assert "90 percent" in top.text and "85 percent" not in top.text


# ---------------- AC-06.3 failure keeps the old version ----------------
def test_embedding_failure_on_update_keeps_serving_the_old_version(rig: Rig) -> None:
    populate(rig.docs)
    rig.service.sync("manual")
    old_ids, old_version = rig.store.ids_for_file("rules.docx"), rig.rows()["rules.docx"].active_version
    (rig.docs / "rules.docx").write_bytes(make_docx([("h1", "Attendance"), ("p", "A brand new rule: 70 percent attendance.")]))
    rig.embedder.fail = True
    r = rig.service.sync("manual")
    row = rig.rows()["rules.docx"]
    assert r.status == "partial" and r.files_failed == 1 and r.files_skipped == 3
    assert row.status == "failed" and "scripted embedding failure" in (row.last_error or "") and row.active_version == old_version
    assert rig.store.ids_for_file("rules.docx") == old_ids  # the old chunks are untouched
    rig.embedder.fail = False
    assert "85 percent" in rig.retriever().retrieve("attendance every term", 1)[0].text
    healed = rig.service.sync("manual")  # the next successful sync heals it
    assert healed.files_indexed == 1 and rig.rows()["rules.docx"].status == "indexed" and rig.rows()["rules.docx"].last_error is None
    assert "70 percent" in rig.retriever().retrieve("brand new rule 70 percent attendance", 1)[0].text


# ---------------- AC-06.4 deletion ----------------
def test_deleted_file_disappears_from_the_index_and_can_come_back(rig: Rig) -> None:
    populate(rig.docs)
    rig.service.sync("manual")
    (rig.docs / "notes.md").unlink()
    r = rig.service.sync("manual")
    assert r.files_deleted == 1 and rig.store.ids_for_file("notes.md") == []
    row = rig.rows()["notes.md"]
    assert (row.status, row.active_version, row.chunk_count) == ("deleted", None, 0)
    assert all("Hostel curfew" not in h.text for h in rig.retriever().retrieve("hostel curfew evening", 5))
    (rig.docs / "notes.md").write_bytes(b"# Hostel\nHostel curfew is at ten in the evening.\n")
    assert rig.service.sync("manual").files_indexed == 1 and rig.rows()["notes.md"].status == "indexed"


# ---------------- AC-06.5 unsupported / corrupt ----------------
def test_unsupported_extension_is_reported_not_failed(rig: Rig) -> None:
    populate(rig.docs)
    r = rig.service.sync("manual")
    row = rig.rows()["tool.exe"]
    assert row.status == "unsupported" and "unsupported" in (row.last_error or "") and row.chunk_count == 0
    assert r.status == "succeeded" and r.files_failed == 0 and rig.store.ids_for_file("tool.exe") == []


def test_a_corrupt_file_fails_alone_with_a_safe_message(rig: Rig) -> None:
    populate(rig.docs)
    (rig.docs / "broken.pdf").write_bytes(b"%PDF-1.4 PRIVATE-CONTENT not really a pdf")
    r = rig.service.sync("manual")
    row = rig.rows()["broken.pdf"]
    assert r.status == "partial" and r.files_failed == 1 and r.files_indexed == 4
    assert row.status == "failed" and "PRIVATE-CONTENT" not in (row.last_error or "") and row.active_version is None


def test_a_file_that_becomes_unsupported_stops_answering(rig: Rig) -> None:
    (rig.docs / "memo.txt").write_bytes(b"Library opens at nine.")
    rig.service.sync("manual")
    assert rig.store.ids_for_file("memo.txt")
    (rig.docs / "memo.txt").rename(rig.docs / "memo.exe")  # same bytes, different listing: the txt is gone, the exe is unsupported
    rig.service.sync("manual")
    assert rig.store.ids_for_file("memo.txt") == [] and rig.rows()["memo.exe"].status == "unsupported"


def test_hidden_and_temp_files_and_missing_folder(rig: Rig, tmp_path: Path) -> None:
    (rig.docs / ".secret.txt").write_bytes(b"hidden")
    (rig.docs / "~$lock.docx").write_bytes(b"office lock file")
    assert rig.service.sync("manual").files_seen == 0
    broken = IngestionService(LocalFolderSource(tmp_path / "nope"), rig.embedder, rig.store, rig.session_factory)  # type: ignore[arg-type]
    r = broken.sync("manual")
    assert r.status == "failed" and "documents folder not found" in (r.error or "")


# ---------------- single flight + safety ----------------
def test_only_one_sync_runs_at_a_time(rig: Rig) -> None:
    populate(rig.docs)
    rig.embedder.gate, rig.embedder.entered = threading.Event(), threading.Event()
    worker = threading.Thread(target=lambda: rig.service.sync("poll"))
    worker.start()
    assert rig.embedder.entered.wait(timeout=10)  # type: ignore[attr-defined]
    with pytest.raises(SyncAlreadyRunning):
        rig.service.sync("manual")
    rig.embedder.gate.set()  # type: ignore[attr-defined]
    worker.join(timeout=30)
    assert not worker.is_alive() and rig.store.count() > 0


def test_a_collection_built_with_another_embedding_model_is_refused(rig: Rig, tmp_path: Path) -> None:
    with pytest.raises(EmbeddingModelMismatch, match="re-index"):
        ChromaStore(tmp_path / "chroma", "test_docs", "some-other-model")


def test_the_local_source_cannot_be_tricked_into_reading_outside_the_folder(rig: Rig, tmp_path: Path) -> None:
    (tmp_path / "outside.txt").write_bytes(b"outside the folder")
    source = LocalFolderSource(rig.docs)
    from app.rag.base import SourceFile

    with pytest.raises(ValueError, match="outside"):
        source.fetch(SourceFile("../outside.txt", "outside.txt", "text/plain", None, None))


# ---------------- admin API + the graph, end to end ----------------
def _client(rig: Rig, with_ingestion: bool) -> TestClient:
    settings = make_settings(rig.tmp, local_docs_dir=rig.docs)
    deps = GraphDeps(settings=settings, session_factory=rig.session_factory, primary_llm=FakeChatClient(reply="Exams are in November [1]."),  # type: ignore[arg-type]
                     model3_llm=None, retriever=rig.retriever(), email_provider=RecordingEmailProvider())
    container = build_container(settings, deps_override=deps, ingestion_override=rig.service if with_ingestion else None)
    client = TestClient(create_app(container))
    client.__enter__()
    return client


def test_admin_sync_endpoint_and_a_grounded_answer_with_real_citations(rig: Rig) -> None:
    populate(rig.docs)
    client = _client(rig, with_ingestion=True)
    try:
        assert client.post("/api/admin/local/sync").status_code in (401, 403)  # needs the admin key
        r = client.post("/api/admin/local/sync", headers={"X-Admin-Key": "test-admin-key"})
        body = r.json()
        assert r.status_code == 200 and body["files_indexed"] == 4 and body["embed_tokens"] > 0 and body["status"] == "succeeded"
        status = client.get("/api/admin/local/status", headers={"X-Admin-Key": "test-admin-key"}).json()
        assert status["counts"] == {"indexed": 4, "unsupported": 1} and status["retriever"]["backend"] == "chroma"
        assert status["local_docs_folder"] == "docs"  # the folder NAME, never the full path
        answer = client.post("/api/chat", json={"message": "When are examinations held in November?", "model_mode": "rag"}).json()
        assert answer["grounded"] is True and answer["citations"][0]["source_name"] == "calendar.pdf"
        assert (answer["citations"][0]["page"], answer["citations"][0]["cited"]) == (2, True)
    finally:
        client.__exit__(None, None, None)


def test_sync_endpoint_is_unavailable_without_embeddings(rig: Rig) -> None:
    client = _client(rig, with_ingestion=False)
    try:
        assert client.post("/api/admin/local/sync", headers={"X-Admin-Key": "test-admin-key"}).status_code == 503
    finally:
        client.__exit__(None, None, None)


# ---------------- placeholder (SYNTHETIC_*) documents must never answer real questions ----------------
def test_synthetic_placeholder_documents_are_not_indexed_unless_asked(rig: Rig, tmp_path: Path) -> None:
    (rig.docs / "SYNTHETIC_calendar.md").write_bytes(b"# Dates\nExams are on 1 January (invented placeholder).\n")
    (rig.docs / "calendar.md").write_bytes(b"# Dates\nExams are on 5 December.\n")
    r = rig.service.sync("manual")  # the rig's source uses the safe default: placeholders excluded
    assert r.files_seen == 1 and rig.store.ids_for_file("SYNTHETIC_calendar.md") == []
    assert all("1 January" not in h.text for h in rig.retriever().retrieve("exams date", 5))

    with_placeholders = IngestionService(LocalFolderSource(rig.docs, include_synthetic=True), rig.embedder, rig.store,
                                         rig.session_factory, chunk_size=300, chunk_overlap=40)  # type: ignore[arg-type]
    assert with_placeholders.sync("manual").files_indexed == 1  # opt-in (used for the synthetic evaluation set)
    assert rig.store.ids_for_file("SYNTHETIC_calendar.md")

    r = rig.service.sync("manual")  # back to the safe default: the placeholder must leave the index again
    assert r.files_deleted == 1 and rig.store.ids_for_file("SYNTHETIC_calendar.md") == []

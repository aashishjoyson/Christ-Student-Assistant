"""Phase 3: Google Drive -> parse -> embed -> Chroma, against a faithful fake Drive. No network, no credentials, no paid API."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.container import build_container
from app.db.models import IngestedFile
from app.db.session import init_db, make_engine, make_session_factory
from app.graph.deps import GraphDeps
from app.main import create_app
from app.rag.ingest import IngestionService
from app.rag.parsers import MIME_DOCX, MIME_PDF, MIME_XLSX
from app.rag.retriever import ChromaRetriever
from app.rag.sources.google_drive import GoogleDriveSource
from app.rag.sources.local_folder import LocalFolderSource
from app.rag.vector_store import ChromaStore
from tests.doc_factory import make_docx, make_pdf, make_xlsx
from tests.fakes import FakeChatClient, FakeEmbedder, RecordingEmailProvider
from tests.fakes_drive import FOLDER, GOOGLE_DOC, FakeDrive, http_error
from tests.integration.conftest import make_settings

REPO = Path(__file__).resolve().parents[3]
DEMO = REPO / "data" / "demo_docs"


@dataclass
class Rig:
    tmp: Path
    drive: FakeDrive
    session_factory: object
    embedder: FakeEmbedder
    store: ChromaStore
    service: IngestionService
    lock: threading.Lock

    def rows(self, source: str = "drive") -> dict[str, IngestedFile]:
        with self.session_factory() as s:  # type: ignore[operator]
            return {r.name: r for r in s.execute(select(IngestedFile).where(IngestedFile.source == source)).scalars()}

    def top(self, question: str, k: int = 1):  # type: ignore[no-untyped-def]
        return ChromaRetriever(self.embedder, self.store).retrieve(question, k)

    def says(self, question: str, needle: str, k: int = 6) -> bool:
        """True if `needle` is in the text of any of the best k chunks. The fake embedder is a crude 64-dim bag of words that cannot rank
        chunks *within* one document, so these checks prove the right document and fact are indexed (and old ones are gone); the real
        embedding model's ranking is what the live demo shows."""
        return any(needle in hit.text for hit in self.top(question, k))


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    engine = make_engine(f"sqlite:///{(tmp_path / 'drive.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)
    embedder, drive, lock = FakeEmbedder(), FakeDrive(), threading.Lock()
    store = ChromaStore(tmp_path / "chroma", "test_docs", embedder.model)
    service = IngestionService(GoogleDriveSource(FOLDER, drive), embedder, store, factory, chunk_size=300, chunk_overlap=40, lock=lock)
    return Rig(tmp_path, drive, factory, embedder, store, service, lock)


def seed(drive: FakeDrive) -> None:
    drive.put("pdf1", "calendar.pdf", make_pdf(["Term one starts in July.", "Examinations are held in November."]), MIME_PDF)
    drive.put("xls1", "courses.xlsx", make_xlsx({"c": [["Course Name", "Fees"], ["MBA", "Fees are payable per semester. " * 4]]}), MIME_XLSX)
    drive.put("gdoc1", "Hostel policy", make_docx([("h1", "Curfew"), ("p", "Hostel curfew is at ten in the evening.")]), GOOGLE_DOC, version=3)
    drive.put("img1", "campus.png", b"\x89PNG", "image/png")


def test_new_files_are_indexed_google_docs_exported_and_citations_link_to_drive(rig: Rig) -> None:
    seed(rig.drive)
    r = rig.service.sync("manual")
    assert (r.status, r.files_seen, r.files_indexed, r.files_unsupported, r.files_failed) == ("succeeded", 4, 3, 1, 0)
    assert {n: row.status for n, row in rig.rows().items()} == {"calendar.pdf": "indexed", "courses.xlsx": "indexed",
                                                                "Hostel policy": "indexed", "campus.png": "unsupported"}
    assert rig.drive.export_calls == [("gdoc1", MIME_DOCX)]  # the Google Doc was exported, not downloaded
    assert sorted(rig.drive.get_media_calls) == ["pdf1", "xls1"]  # the image was never downloaded
    hit = rig.top("when are examinations held in november")[0]
    assert (hit.source_name, hit.page, hit.source_url) == ("calendar.pdf", 2, "https://drive.google.com/file/d/pdf1/view")
    doc_hit = rig.top("hostel curfew evening")[0]
    assert doc_hit.source_name == "Hostel policy" and doc_hit.section == "Curfew"
    assert doc_hit.text.startswith("Document: Hostel policy\n")  # the document name travels with every chunk


def test_unchanged_files_are_not_downloaded_or_embedded_again(rig: Rig) -> None:
    seed(rig.drive)
    rig.service.sync("manual")
    media, exports, embeds, ids = list(rig.drive.get_media_calls), list(rig.drive.export_calls), rig.embedder.calls, rig.store.count()
    r = rig.service.sync("manual")
    assert rig.drive.get_media_calls == media and rig.drive.export_calls == exports  # nothing downloaded or exported
    assert rig.embedder.calls == embeds and r.embed_calls == 0 and rig.store.count() == ids
    assert (r.files_indexed, r.files_skipped) == (0, 3)  # the three indexable files were seen again and left alone


def test_an_edited_file_and_a_new_google_doc_version_are_reindexed(rig: Rig) -> None:
    seed(rig.drive)
    rig.service.sync("manual")
    old_ids = rig.store.ids_for_file("gdoc1")
    rig.drive.put("pdf1", "calendar.pdf", make_pdf(["Term one starts in August.", "Examinations are held in December."]), MIME_PDF, md5="new-md5")
    rig.drive.put("gdoc1", "Hostel policy", make_docx([("h1", "Curfew"), ("p", "Hostel curfew is at eleven in the evening.")]), GOOGLE_DOC, version=4)
    r = rig.service.sync("manual")
    assert r.files_indexed == 2 and r.files_skipped == 1  # the spreadsheet did not change
    assert "December" in rig.top("when are examinations held")[0].text
    assert "eleven" in rig.top("hostel curfew evening")[0].text
    assert not set(rig.store.ids_for_file("gdoc1")) & set(old_ids)  # old version fully replaced


def test_trashed_or_removed_files_leave_the_index(rig: Rig) -> None:
    seed(rig.drive)
    rig.service.sync("manual")
    rig.drive.trash("gdoc1")  # trashed in Drive = gone for us
    del rig.drive.items["xls1"]  # removed entirely
    r = rig.service.sync("manual")
    assert r.files_deleted == 2 and rig.store.ids_for_file("gdoc1") == [] and rig.store.ids_for_file("xls1") == []
    assert rig.rows()["Hostel policy"].status == "deleted" and rig.rows()["calendar.pdf"].status == "indexed"


def test_a_drive_outage_keeps_the_index_and_says_why(rig: Rig) -> None:
    seed(rig.drive)
    rig.service.sync("manual")
    before = rig.store.count()
    rig.drive.list_error = http_error(403, "forbidden")
    r = rig.service.sync("poll")
    assert r.status == "failed" and "may not be shared" in (r.error or "") and "403" in (r.error or "")
    assert rig.store.count() == before and all(row.status != "deleted" for row in rig.rows().values())  # nothing was thrown away
    rig.drive.list_error = None
    assert rig.service.sync("poll").status == "succeeded"  # and it heals by itself on the next run


def test_one_failed_download_does_not_stop_the_others(rig: Rig) -> None:
    seed(rig.drive)
    rig.drive.media_errors["xls1"] = http_error(503)
    r = rig.service.sync("manual")
    assert r.status == "partial" and r.files_failed == 1 and r.files_indexed == 2
    assert rig.rows()["courses.xlsx"].status == "failed" and "temporarily" in (rig.rows()["courses.xlsx"].last_error or "")


def test_local_and_drive_documents_share_the_store_without_touching_each_other(rig: Rig) -> None:
    local_dir = rig.tmp / "local"
    local_dir.mkdir()
    (local_dir / "notes.md").write_bytes(b"# Library\nThe library opens at nine.\n")
    local = IngestionService(LocalFolderSource(local_dir), rig.embedder, rig.store, rig.session_factory,  # type: ignore[arg-type]
                             chunk_size=300, chunk_overlap=40, lock=rig.lock)
    seed(rig.drive)
    local.sync("manual")
    rig.service.sync("manual")
    rig.drive.trash("pdf1")
    rig.service.sync("manual")  # a Drive sync must never delete the local folder's documents
    assert rig.store.ids_for_file("pdf1") == [] and rig.store.ids_for_file("notes.md") != []
    assert local.purge() == 1  # switching the source of truth removes only the local documents ...
    assert rig.store.ids_for_file("notes.md") == [] and rig.store.ids_for_file("gdoc1") != []  # ... Drive's stay


def test_the_sync_lock_is_shared_so_two_sources_never_write_at_once(rig: Rig) -> None:
    from app.rag.ingest import SyncAlreadyRunning

    seed(rig.drive)
    other = IngestionService(LocalFolderSource(rig.tmp), rig.embedder, rig.store, rig.session_factory, lock=rig.lock)  # type: ignore[arg-type]
    rig.embedder.gate, rig.embedder.entered = threading.Event(), threading.Event()
    worker = threading.Thread(target=lambda: rig.service.sync("poll"))
    worker.start()
    assert rig.embedder.entered.wait(timeout=10)  # type: ignore[attr-defined]
    with pytest.raises(SyncAlreadyRunning):
        other.sync("manual")
    rig.embedder.gate.set()  # type: ignore[attr-defined]
    worker.join(timeout=30)


# ---------------------------------------------------------------- the live demo, replayed with the real demo documents
def test_the_demo_script_works_with_the_real_demo_documents(rig: Rig) -> None:
    """Step 1 add four circulars, step 2 replace one with a revised version, step 3 delete one (docs/DEMO_SCRIPT.md)."""
    assert DEMO.is_dir(), "run scripts/make_demo_docs.py"
    fee, library, lecture, bonafide = ("Notice_Semester_Fee_Payment_Last_Date.docx", "Circular_Extended_Library_Hours_Examination_Period.docx",
                                       "Notice_Guest_Lecture_Responsible_AI_in_Higher_Education.docx", "Procedure_Bonafide_Certificate.docx")
    assert rig.service.sync("poll").files_seen == 0  # before the demo: an empty folder
    for i, name in enumerate((library, fee, lecture, bonafide)):
        rig.drive.put(f"d{i}", name, (DEMO / "step1_add" / name).read_bytes(), MIME_DOCX)
    assert rig.service.sync("poll").files_indexed == 4
    fee_q = "last date for payment without fine late fine per day"
    assert rig.says(fee_q, "Last date for payment without fine: 10 January 2027")
    assert rig.says("extended library hours examination period", "10:00 PM")
    assert rig.says("bonafide certificate fee how to apply", "Rs 50")
    assert rig.says("guest lecture responsible use of AI in higher education", "3 December 2026")

    rig.drive.put("d1", fee, (DEMO / "step2_edit" / fee).read_bytes(), MIME_DOCX, md5="revised")  # same file name, new content
    assert rig.service.sync("poll").files_indexed == 1
    assert rig.says(fee_q, "NEW last date for payment without fine: 17 January 2027")
    everything = " ".join(h.text for h in rig.top(fee_q, 20))
    assert "Last date for payment without fine: 10 January 2027" not in everything  # the old notice's wording is gone from the index
    assert rig.rows()[fee].status == "indexed" and len(rig.rows()) == 4  # still one document, not two

    rig.drive.trash("d2")  # delete the guest lecture notice
    assert rig.service.sync("poll").files_deleted == 1
    assert rig.store.ids_for_file("d2") == [] and all("guest lecture" not in h.text.lower() for h in rig.top("guest lecture AI", 5))


# ---------------------------------------------------------------- admin API
def _client(rig: Rig, **container_attrs: object) -> TestClient:
    settings = make_settings(rig.tmp)
    deps = GraphDeps(settings=settings, session_factory=rig.session_factory, primary_llm=FakeChatClient(),  # type: ignore[arg-type]
                     model3_llm=None, retriever=ChromaRetriever(rig.embedder, rig.store), email_provider=RecordingEmailProvider())
    container = build_container(settings, deps_override=deps, drive_ingestion_override=rig.service)
    for key, value in container_attrs.items():
        setattr(container, key, value)
    client = TestClient(create_app(container))
    client.__enter__()
    return client


def test_admin_drive_sync_and_freshness_status(rig: Rig) -> None:
    seed(rig.drive)
    client = _client(rig)
    key = {"X-Admin-Key": "test-admin-key"}
    try:
        assert client.post("/api/admin/drive/sync").status_code in (401, 403)
        body = client.post("/api/admin/drive/sync", headers=key).json()
        assert body["status"] == "succeeded" and body["files_indexed"] == 3 and body["embed_tokens"] > 0
        status = client.get("/api/admin/drive/status", headers=key).json()
        assert status["drive_ready"] is True and status["drive_error"] is None
        assert isinstance(status["seconds_since_last_success"], int) and status["seconds_since_last_success"] < 60
        assert status["counts"] == {"indexed": 3, "unsupported": 1}
    finally:
        client.__exit__(None, None, None)


def test_admin_drive_sync_explains_why_drive_is_unavailable(rig: Rig) -> None:
    client = _client(rig, drive_ingestion=None, drive_error="Drive folder or file not found. Check GOOGLE_DRIVE_FOLDER_ID")
    try:
        r = client.post("/api/admin/drive/sync", headers={"X-Admin-Key": "test-admin-key"})
        assert r.status_code == 503 and "GOOGLE_DRIVE_FOLDER_ID" in r.json()["detail"]
        status = client.get("/api/admin/drive/status", headers={"X-Admin-Key": "test-admin-key"}).json()
        assert status["drive_ready"] is False and "not found" in status["drive_error"]
    finally:
        client.__exit__(None, None, None)

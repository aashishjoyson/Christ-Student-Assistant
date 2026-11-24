"""GoogleDriveSource against a faithful fake of the Drive client (no network, no credentials)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.base import SourceFile
from app.rag.parsers import MIME_CSV, MIME_DOCX, MIME_MD, MIME_PDF, MIME_XLSX, is_supported
from app.rag.sources.google_drive import (
    LIST_FIELDS,
    MAX_DOWNLOAD_BYTES,
    DriveError,
    GoogleDriveSource,
    build_drive_service,
)
from tests.fakes_drive import FOLDER, GOOGLE_DOC, GOOGLE_SHEET, FakeDrive, http_error


def source(drive: FakeDrive) -> GoogleDriveSource:
    return GoogleDriveSource(FOLDER, drive)


def test_lists_every_page_of_only_this_folders_untrashed_files() -> None:
    drive = FakeDrive(page_size=2)
    for i in range(5):
        drive.put(f"f{i}", f"doc{i}.pdf", b"x", MIME_PDF)
    drive.put("old", "deleted.pdf", b"x", MIME_PDF, trashed=True)
    drive.put("elsewhere", "other.pdf", b"x", MIME_PDF, parent="OTHER")
    names = [f.name for f in source(drive).list_files()]
    assert names == [f"doc{i}.pdf" for i in range(5)]  # 3 pages; the trashed file and the other folder's file are absent
    assert len(drive.queries) == 3 and all(q == f"'{FOLDER}' in parents and trashed = false" for q in drive.queries)
    assert all(f == LIST_FIELDS for f in drive.requested_fields)


def test_folders_and_shortcuts_are_ignored_but_reported() -> None:
    drive = FakeDrive()
    drive.put("a", "real.pdf", b"x", MIME_PDF)
    drive.put("b", "Archive", b"", "application/vnd.google-apps.folder")
    drive.put("c", "Link to handbook", b"", "application/vnd.google-apps.shortcut")
    src = source(drive)
    assert [f.name for f in src.list_files()] == ["real.pdf"]
    assert sorted(src.ignored) == ["Archive", "Link to handbook"]


def test_file_types_are_mapped_by_drive_type_or_by_extension() -> None:
    drive = FakeDrive(page_size=50)
    drive.put("1", "handbook.pdf", b"x", MIME_PDF)
    drive.put("2", "courses.xlsx", b"x", MIME_XLSX)
    drive.put("3", "faq.md", b"x", "text/plain")  # Drive often labels markdown as plain text
    drive.put("4", "table.csv", b"x", "application/octet-stream")
    drive.put("5", "notice.docx", b"x", "application/octet-stream")
    drive.put("6", "Policy (Google Doc)", b"", GOOGLE_DOC)
    drive.put("7", "Fees (Google Sheet)", b"", GOOGLE_SHEET)
    drive.put("8", "photo.png", b"x", "image/png")
    drive.put("9", "slides", b"", "application/vnd.google-apps.presentation")
    got = {f.name: f for f in source(drive).list_files()}
    assert got["faq.md"].mime_type == MIME_MD and got["table.csv"].mime_type == MIME_CSV and got["notice.docx"].mime_type == MIME_DOCX
    assert got["Policy (Google Doc)"].mime_type == GOOGLE_DOC and got["Fees (Google Sheet)"].mime_type == GOOGLE_SHEET
    indexable = {n for n, f in got.items() if is_supported(f.mime_type)}
    assert indexable == {"handbook.pdf", "courses.xlsx", "faq.md", "table.csv", "notice.docx", "Policy (Google Doc)", "Fees (Google Sheet)"}


def test_change_signals_md5_for_files_and_version_for_google_native() -> None:
    drive = FakeDrive(page_size=50)
    drive.put("a", "a.pdf", b"x", MIME_PDF, md5="abc123")
    drive.put("b", "Policy", b"", GOOGLE_DOC, version=7)
    files = {f.name: f for f in source(drive).list_files()}
    assert files["a.pdf"].remote_checksum == "abc123"
    assert files["Policy"].remote_checksum.startswith("v7:")  # version + modified time
    assert files["a.pdf"].source_url == "https://drive.google.com/file/d/a/view" and files["a.pdf"].modified_time.tzinfo is not None


def test_binary_files_are_downloaded_and_google_docs_are_exported() -> None:
    drive = FakeDrive(page_size=50)
    drive.put("a", "a.pdf", b"PDF-BYTES", MIME_PDF)
    drive.put("g", "Policy", b"EXPORTED-DOCX", GOOGLE_DOC)
    drive.put("s", "Fees", b"EXPORTED-XLSX", GOOGLE_SHEET)
    files = {f.name: f for f in source(drive).list_files()}
    assert source(drive).fetch(files["a.pdf"]) == (b"PDF-BYTES", MIME_PDF)
    assert source(drive).fetch(files["Policy"]) == (b"EXPORTED-DOCX", MIME_DOCX)
    assert source(drive).fetch(files["Fees"]) == (b"EXPORTED-XLSX", MIME_XLSX)
    assert drive.get_media_calls == ["a"] and drive.export_calls == [("g", MIME_DOCX), ("s", MIME_XLSX)]


def test_oversized_files_are_refused_before_any_download() -> None:
    drive = FakeDrive()
    big = SourceFile("x", "huge.pdf", MIME_PDF, None, "md5", size_bytes=MAX_DOWNLOAD_BYTES + 1)
    with pytest.raises(DriveError, match="larger than"):
        source(drive).fetch(big)
    assert drive.get_media_calls == []


@pytest.mark.parametrize(("status", "reason", "expected"), [
    (404, "notFound", "shared with the service account"),
    (403, "accessNotConfigured", "not enabled"),
    (403, "exportSizeLimitExceeded", "10 MB"),
    (403, "forbidden", "may not be shared"),
    (401, "", "rejected the credentials"),
    (429, "rateLimitExceeded", "temporarily"),
    (503, "", "temporarily"),
])
def test_google_errors_become_clear_safe_messages(status: int, reason: str, expected: str) -> None:
    drive = FakeDrive()
    drive.list_error = http_error(status, reason)
    with pytest.raises(DriveError, match=expected):
        source(drive).list_files()


def test_a_download_error_is_explained_not_leaked() -> None:
    drive = FakeDrive()
    drive.put("a", "a.pdf", b"x", MIME_PDF)
    drive.media_errors["a"] = http_error(404, "notFound")
    file = source(drive).list_files()[0]
    with pytest.raises(DriveError, match="not found"):
        source(drive).fetch(file)


def test_an_empty_folder_id_is_rejected() -> None:
    with pytest.raises(DriveError, match="empty"):
        GoogleDriveSource("  ", FakeDrive())


# ---- credentials: loaded by Google's library; our messages never contain file contents ----
def test_missing_service_account_key_is_explained(tmp_path: Path) -> None:
    with pytest.raises(DriveError, match="key file not found"):
        build_drive_service("service_account", tmp_path / "nope.json")
    with pytest.raises(DriveError, match="key file not found"):
        build_drive_service("service_account", None)


def test_a_malformed_key_file_is_rejected_without_echoing_it(tmp_path: Path) -> None:
    bad = tmp_path / "key.json"
    bad.write_text("SECRET-GARBAGE-NOT-JSON", encoding="utf-8")
    with pytest.raises(DriveError) as exc:
        build_drive_service("service_account", bad)
    assert "SECRET-GARBAGE" not in str(exc.value) and "could not be read" in str(exc.value)
    wrong_kind = tmp_path / "other.json"
    wrong_kind.write_text('{"type": "authorized_user", "client_id": "SECRET-ID"}', encoding="utf-8")
    with pytest.raises(DriveError) as exc2:
        build_drive_service("service_account", wrong_kind)
    assert "SECRET-ID" not in str(exc2.value)


def test_oauth_mode_needs_a_token_file(tmp_path: Path) -> None:
    with pytest.raises(DriveError, match="drive_oauth_login"):
        build_drive_service("oauth", None, tmp_path / "missing-token.json")

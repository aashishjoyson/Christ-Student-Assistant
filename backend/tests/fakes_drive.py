"""A faithful in-memory stand-in for the Google Drive v3 client (files().list / get_media / export_media ... .execute()).

Honours the query the real source sends ("'<folder>' in parents and trashed = false"), pages results, counts every call, and can
raise real googleapiclient HttpError objects, so the error-mapping code is tested against the real exception type.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httplib2
from googleapiclient.errors import HttpError

from app.rag.parsers import MIME_DOCX, MIME_XLSX

FOLDER = "FOLDER123"


def http_error(status: int, reason: str = "") -> HttpError:
    body = {"error": {"code": status, "message": "x", "errors": [{"reason": reason}] if reason else []}}
    return HttpError(httplib2.Response({"status": str(status)}), json.dumps(body).encode())


class _Request:
    def __init__(self, thunk: Callable[[], Any]) -> None:
        self._thunk = thunk

    def execute(self, num_retries: int = 0) -> Any:  # noqa: ARG002 - mirrors the real signature
        return self._thunk()


class FakeDrive:
    """Files are plain dicts shaped like Drive's File resource; `content[id]` holds the bytes (or exported bytes)."""

    def __init__(self, page_size: int = 2) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.content: dict[str, bytes] = {}
        self.page_size = page_size
        self.queries: list[str] = []
        self.requested_fields: list[str] = []
        self.get_media_calls: list[str] = []
        self.export_calls: list[tuple[str, str]] = []
        self.list_error: Exception | None = None
        self.media_errors: dict[str, Exception] = {}

    # ------------------------------------------------------------ test helpers
    def put(self, file_id: str, name: str, data: bytes, mime: str, *, md5: str | None = None, version: int = 1,
            trashed: bool = False, parent: str = FOLDER) -> None:
        native = mime.startswith("application/vnd.google-apps")
        self.items[file_id] = {
            "id": file_id, "name": name, "mimeType": mime, "modifiedTime": f"2026-11-2{version}T10:00:00.000Z",
            "version": str(version), "webViewLink": f"https://drive.google.com/file/d/{file_id}/view", "size": str(len(data)),
            "trashed": trashed, "parent": parent,
        }
        if not native:
            self.items[file_id]["md5Checksum"] = md5 or f"md5-{abs(hash(data)) % 10**12}"
        self.content[file_id] = data

    def trash(self, file_id: str) -> None:
        self.items[file_id]["trashed"] = True

    # ------------------------------------------------------------ the Drive client surface
    def files(self) -> FakeDrive:
        return self

    def list(self, q: str, fields: str, pageSize: int, pageToken: str | None = None, **_: Any) -> _Request:  # noqa: N803
        self.queries.append(q)
        self.requested_fields.append(fields)

        def run() -> dict[str, Any]:
            if self.list_error:
                raise self.list_error
            wanted_folder = q.split("'")[1]
            rows = sorted((i for i in self.items.values() if i["parent"] == wanted_folder and not i["trashed"]), key=lambda i: i["name"])
            start = int(pageToken or 0)
            page = rows[start : start + self.page_size]
            result: dict[str, Any] = {"files": [{k: v for k, v in i.items() if k not in ("trashed", "parent")} for i in page]}
            if start + self.page_size < len(rows):
                result["nextPageToken"] = str(start + self.page_size)
            return result

        return _Request(run)

    def get_media(self, fileId: str, **_: Any) -> _Request:  # noqa: N803
        def run() -> bytes:
            self.get_media_calls.append(fileId)
            if fileId in self.media_errors:
                raise self.media_errors[fileId]
            return self.content[fileId]

        return _Request(run)

    def export_media(self, fileId: str, mimeType: str) -> _Request:  # noqa: N803
        def run() -> bytes:
            self.export_calls.append((fileId, mimeType))
            if fileId in self.media_errors:
                raise self.media_errors[fileId]
            return self.content[fileId]

        return _Request(run)


GOOGLE_DOC = "application/vnd.google-apps.document"
GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
__all__ = ["FOLDER", "FakeDrive", "GOOGLE_DOC", "GOOGLE_SHEET", "MIME_DOCX", "MIME_XLSX", "http_error"]

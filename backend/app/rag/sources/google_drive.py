"""DocumentSource over ONE Google Drive folder (non-recursive), read-only.

Checked against the Drive API v3 docs on 2026-11-24 (see docs/TECHNICAL_REFERENCES.md):
- list: q = "'<folder>' in parents and trashed = false", partial `fields`, pageSize <= 1000, nextPageToken paging
- md5Checksum exists only for files with binary content; Google-native files (Docs, Sheets) are identified by `version` + modifiedTime
- binary files: files.get(alt=media); Google Docs/Sheets: files.export to DOCX/XLSX (export is limited to 10 MB)
- scope drive.readonly covers both; 429 and 5xx are retried with exponential backoff (num_retries)
Credentials are loaded from a file by Google's own library; their contents are never read, logged or returned by our code.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.rag.base import SourceFile
from app.rag.parsers import NATIVE_EXPORT_MIME, SUPPORTED_MIME_TYPES, mime_for_name

log = logging.getLogger("rag.drive")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
MIME_FOLDER = "application/vnd.google-apps.folder"
MIME_SHORTCUT = "application/vnd.google-apps.shortcut"
LIST_FIELDS = "nextPageToken, files(id, name, mimeType, modifiedTime, md5Checksum, version, webViewLink, size)"
PAGE_SIZE = 200
RETRIES = 5  # googleapiclient retries 429/5xx with exponential backoff
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
GENERIC_MIME_TYPES = frozenset({"text/plain", "application/octet-stream", "binary/octet-stream"})


class DriveError(Exception):
    """A Drive problem with a message that is safe to show in the admin status (no credentials, no file contents)."""


def _explain(exc: Exception) -> DriveError:
    """Turn a Google API error into a clear, safe message."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    reason = ""
    try:  # HttpError carries the JSON error body; only the machine reason is used, never echoed text from the user's files
        body = json.loads(exc.content.decode("utf-8"))  # type: ignore[attr-defined]
        reason = str(body["error"]["errors"][0].get("reason", ""))
    except Exception:  # noqa: BLE001 - any parse problem just means "no reason available"
        log.debug("no machine-readable reason in the Drive error")
    if status == 404:
        return DriveError("Drive folder or file not found. Check GOOGLE_DRIVE_FOLDER_ID and that the folder is shared "
                          "with the service account's email (Viewer).")
    if status == 403 and reason in {"accessNotConfigured", "SERVICE_DISABLED"}:
        return DriveError("The Google Drive API is not enabled for this Google Cloud project.")
    if status == 403 and reason in {"exportSizeLimitExceeded", "fileNotExportable"}:
        return DriveError(f"Drive could not export this file ({reason}; exports are limited to 10 MB).")
    if status == 403:
        return DriveError(f"Drive refused access (403 {reason or 'forbidden'}). The folder may not be shared with the service account.")
    if status == 401:
        return DriveError("Google rejected the credentials (401). Check the service-account key file.")
    if status in {429, 500, 502, 503, 504}:
        return DriveError(f"Drive is temporarily unavailable or rate limiting ({status}); the next sync will retry.")
    return DriveError(f"Drive request failed ({type(exc).__name__}{f' {status}' if status else ''}).")


def build_drive_service(auth_mode: str, credentials_file: Any, token_file: Any = None) -> Any:
    """Create an authorised Drive v3 client. Paths come from settings; the key's contents are only read by Google's library."""
    if sys.platform == "win32":
        try:  # trust the Windows certificate store, like browsers do (antivirus / corporate HTTPS inspection re-signs traffic)
            import truststore

            truststore.inject_into_ssl()
        except Exception:  # noqa: BLE001 - optional; plain certifi still works on normal networks
            log.debug("truststore not available")
    from googleapiclient.discovery import build

    if auth_mode == "service_account":
        if not credentials_file or not credentials_file.is_file():
            raise DriveError("Service-account key file not found. Put it in secrets/ and set GOOGLE_DRIVE_CREDENTIALS_FILE "
                             "(see docs/SETUP_DRIVE.md).")
        from google.oauth2 import service_account

        try:
            creds = service_account.Credentials.from_service_account_file(str(credentials_file), scopes=SCOPES)
        except Exception as exc:  # malformed JSON, wrong kind of key, ...
            raise DriveError("The key file could not be read as a Google service-account key (is it the JSON key downloaded "
                             "from Google Cloud?).") from exc
    else:
        if not token_file or not token_file.is_file():
            raise DriveError("OAuth token not found. Run scripts/drive_oauth_login.py once (see docs/SETUP_DRIVE.md).")
        from google.oauth2.credentials import Credentials

        try:
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except Exception as exc:
            raise DriveError("The OAuth token file could not be read; run scripts/drive_oauth_login.py again.") from exc
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


class GoogleDriveSource:
    name = "drive"

    def __init__(self, folder_id: str, service: Any) -> None:
        if not folder_id.strip():
            raise DriveError("GOOGLE_DRIVE_FOLDER_ID is empty.")
        self._folder_id = folder_id.strip()
        self._service = service
        self.ignored: list[str] = []  # names of sub-folders / shortcuts skipped by the last listing (a common 'why is it empty?' cause)

    # ------------------------------------------------------------------ listing
    def list_files(self) -> list[SourceFile]:
        files: list[SourceFile] = []
        self.ignored = []
        page_token: str | None = None
        query = f"'{self._folder_id}' in parents and trashed = false"
        while True:
            try:
                response = self._service.files().list(
                    q=query, fields=LIST_FIELDS, pageSize=PAGE_SIZE, pageToken=page_token,
                    supportsAllDrives=True, includeItemsFromAllDrives=True, orderBy="name",
                ).execute(num_retries=RETRIES)
            except Exception as exc:
                raise _explain(exc) from exc
            for item in response.get("files", []):
                converted = self._convert(item)
                if converted is not None:
                    files.append(converted)
            page_token = response.get("nextPageToken")
            if not page_token:
                return files

    def _convert(self, item: dict[str, Any]) -> SourceFile | None:
        drive_mime = item.get("mimeType", "")
        if drive_mime in {MIME_FOLDER, MIME_SHORTCUT}:  # sub-folders and shortcuts are ignored in v1
            self.ignored.append(item.get("name", ""))
            return None
        name = item.get("name", "")
        by_name = mime_for_name(name)
        if drive_mime in NATIVE_EXPORT_MIME:
            mime = drive_mime
        elif by_name in SUPPORTED_MIME_TYPES and (drive_mime in GENERIC_MIME_TYPES or drive_mime not in SUPPORTED_MIME_TYPES):
            # Drive labels .md and .csv as text/plain or octet-stream: the extension is more specific, so it wins
            # (otherwise a Markdown file would be read as plain text and lose its headings).
            mime = by_name
        else:
            mime = drive_mime
        modified = item.get("modifiedTime")
        # Binary files have an md5; Google-native files only have a version (plus the modified time as a second signal).
        checksum = item.get("md5Checksum") or f"v{item.get('version', '?')}:{modified or ''}"
        size = item.get("size")
        return SourceFile(
            source_file_id=item["id"], name=name, mime_type=mime, modified_time=_parse_time(modified),
            remote_checksum=checksum, source_url=item.get("webViewLink"), size_bytes=int(size) if size else None,
        )

    # ------------------------------------------------------------------ download / export
    def fetch(self, file: SourceFile) -> tuple[bytes, str]:
        if file.size_bytes is not None and file.size_bytes > MAX_DOWNLOAD_BYTES:
            raise DriveError(f"{file.name}: file is larger than the {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB limit.")
        try:
            if file.mime_type in NATIVE_EXPORT_MIME:
                effective = NATIVE_EXPORT_MIME[file.mime_type]
                content = self._service.files().export_media(fileId=file.source_file_id, mimeType=effective).execute(num_retries=RETRIES)
                return bytes(content), effective
            content = self._service.files().get_media(fileId=file.source_file_id, supportsAllDrives=True).execute(num_retries=RETRIES)
            return bytes(content), file.mime_type
        except DriveError:
            raise
        except Exception as exc:
            raise _explain(exc) from exc

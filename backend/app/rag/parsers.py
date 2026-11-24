"""File parsers: bytes -> list[ParsedSection] with page / section metadata for citations.

PDF: one section per page (page=n). DOCX: split at headings (section=heading), tables kept as text. Markdown: split at '#'
headings. TXT: one section. CSV / XLSX: rows rendered as "column: value; ..." lines so every chunk is self-describing, grouped in
blocks of rows (section="<sheet> rows a-b"). Anything else raises UnsupportedFileType; unreadable files raise ParseError with a
message that is safe to show in the admin status (no file content).
"""

from __future__ import annotations

import codecs
import csv
import io
import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from app.domain.documents import ParsedSection

MIME_PDF = "application/pdf"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_MD = "text/markdown"
MIME_TXT = "text/plain"
MIME_CSV = "text/csv"
MIME_GOOGLE_DOC = "application/vnd.google-apps.document"  # Phase 3 exports these to DOCX before parsing

SUPPORTED_MIME_TYPES = frozenset({MIME_PDF, MIME_DOCX, MIME_XLSX, MIME_MD, MIME_TXT, MIME_CSV})
_EXTENSION_MIME = {
    ".pdf": MIME_PDF, ".docx": MIME_DOCX, ".xlsx": MIME_XLSX, ".md": MIME_MD, ".markdown": MIME_MD,
    ".txt": MIME_TXT, ".csv": MIME_CSV,
}
SHORT_CELL_CHARS = 80  # table cells up to this length describe the row (its identity); longer ones are its body
MAX_PREFIX_CHARS = 300
_EMPTY_CELLS = frozenset({"none", "null", "nan", "n/a", "na", "-"})


class UnsupportedFileType(Exception):
    """The file type cannot be indexed (reported as status 'unsupported', not as a failure)."""


class ParseError(Exception):
    """The file is of a supported type but could not be read (corrupt, encrypted, scanned PDF without text, ...)."""


def mime_for_name(name: str) -> str:
    """Effective mime type from the file extension (local folders have no reliable mime metadata)."""
    return _EXTENSION_MIME.get(PurePosixPath(name.lower()).suffix, "application/octet-stream")


def is_supported(mime_type: str) -> bool:
    return mime_type in SUPPORTED_MIME_TYPES


def parse(content: bytes, mime_type: str, name: str) -> list[ParsedSection]:
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise UnsupportedFileType(f"{name}: unsupported file type {mime_type}")
    try:
        if mime_type == MIME_PDF:
            sections = _parse_pdf(content)
        elif mime_type == MIME_DOCX:
            sections = _parse_docx(content)
        elif mime_type == MIME_XLSX:
            sections = _parse_xlsx(content)
        elif mime_type == MIME_CSV:
            sections = _parse_csv(_decode(content))
        elif mime_type == MIME_MD:
            sections = _parse_markdown(_decode(content))
        else:
            sections = [ParsedSection(text=_decode(content))]
    except (UnsupportedFileType, ParseError):
        raise
    except Exception as exc:  # parser libraries raise many types; never leak file content into the message
        raise ParseError(f"{name}: could not read the file ({type(exc).__name__})") from exc
    sections = [s for s in sections if s.text.strip()]
    if not sections:
        hint = " (a scanned PDF has no text layer; OCR is not supported)" if mime_type == MIME_PDF else ""
        raise ParseError(f"{name}: no extractable text{hint}")
    return sections


def _decode(content: bytes) -> str:
    """UTF-16 only with a byte-order mark (without one, cp1252 text can 'decode' as UTF-16 garbage and never fail)."""
    if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return content.decode("utf-16")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeError:
            continue
    return content.decode("utf-8", errors="replace")


# ---------------- PDF ----------------
def _parse_pdf(content: bytes) -> list[ParsedSection]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        raise ParseError("the PDF is encrypted")
    return [ParsedSection(text=page.extract_text() or "", page=number) for number, page in enumerate(reader.pages, start=1)]


# ---------------- DOCX ----------------
def _docx_blocks(document) -> Iterator[tuple[str, str]]:  # type: ignore[no-untyped-def]
    """Yield ("heading", text) / ("text", text) in document order, tables rendered row by row."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, document)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "").lower() if para.style is not None else ""
            yield ("heading" if style.startswith("heading") or style == "title" else "text", text)
        elif tag == "tbl":
            for row in Table(child, document).rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    yield "text", " | ".join(dict.fromkeys(cells))  # merged cells repeat; keep each value once


def _parse_docx(content: bytes) -> list[ParsedSection]:
    from docx import Document

    sections: list[ParsedSection] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            sections.append(ParsedSection(text="\n".join(buffer), section=heading))
            buffer.clear()

    for kind, text in _docx_blocks(Document(io.BytesIO(content))):
        if kind == "heading":
            flush()
            heading = text
        else:
            buffer.append(text)
    flush()
    return sections


# ---------------- Markdown ----------------
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def _parse_markdown(text: str) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append(ParsedSection(text=body, section=heading))
        buffer.clear()

    for line in text.splitlines():
        match = _MD_HEADING.match(line)
        if match:
            flush()
            heading = match.group(2).strip()
        else:
            buffer.append(line)
    flush()
    return sections


# ---------------- tables (CSV / XLSX) ----------------
def _render_rows(header: list[str], rows: list[list[str]], label: str) -> list[ParsedSection]:
    """One section per row. Short cells (name, campus, category, ...) form a prefix repeated at the top of EVERY chunk of that
    row; long cells (fees, eligibility text, ...) are the body. So a chunk from the middle of a long "Fees" cell still says
    which course it belongs to, both for the embedding and for the model reading it."""
    sections: list[ParsedSection] = []
    for number, row in enumerate(rows, start=1):
        cells = [(h, v) for h, v in zip(header, row, strict=False) if v and v.lower() not in _EMPTY_CELLS]
        if not cells:
            continue
        short = [(h, v) for h, v in cells if len(v) <= SHORT_CELL_CHARS]
        long = [(h, v) for h, v in cells if len(v) > SHORT_CELL_CHARS]
        title = cells[0][1][:100] or f"{label} row {number}"
        if long and short:
            prefix = "; ".join(f"{h}: {v}" for h, v in short)[:MAX_PREFIX_CHARS]
            sections.append(ParsedSection(text="\n".join(f"{h}: {v}" for h, v in long), section=title, prefix=prefix))
        else:
            sections.append(ParsedSection(text="\n".join(f"{h}: {v}" for h, v in cells), section=title))
    return sections


def _clean(cell: object) -> str:
    return " ".join(str(cell).split()) if cell is not None else ""


def _parse_csv(text: str) -> list[ParsedSection]:
    table = [[_clean(c) for c in row] for row in csv.reader(io.StringIO(text)) if any(c.strip() for c in row)]
    if len(table) < 2:
        return [ParsedSection(text="\n".join(" ".join(r) for r in table))] if table else []
    header = [h or f"column {i}" for i, h in enumerate(table[0], start=1)]
    return _render_rows(header, table[1:], "csv")


def _parse_xlsx(content: bytes) -> list[ParsedSection]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    sections: list[ParsedSection] = []
    try:
        for sheet in workbook.worksheets:
            table = [[_clean(c) for c in row] for row in sheet.iter_rows(values_only=True)]
            table = [r for r in table if any(r)]
            if len(table) < 2:
                if table:
                    sections.append(ParsedSection(text=" | ".join(c for c in table[0] if c), section=sheet.title))
                continue
            header = [h or f"column {i}" for i, h in enumerate(table[0], start=1)]
            sections += _render_rows(header, table[1:], sheet.title)
    finally:
        workbook.close()
    return sections

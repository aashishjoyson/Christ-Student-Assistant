"""File parsers: bytes -> list[ParsedSection] with page / section metadata for citations.

PDF: one section per page (page=n). DOCX: split at headings (section=heading), tables kept as text. Markdown: split at '#'
headings. TXT: one section. CSV / XLSX: rows rendered as "column: value; ..." lines so every chunk is self-describing, grouped in
blocks of rows (section="<sheet> rows a-b"). Anything else raises UnsupportedFileType; unreadable files raise ParseError with a
message that is safe to show in the admin status (no file content).
"""

from __future__ import annotations

import codecs
import csv
import html
import io
import re
from collections.abc import Iterator
from dataclasses import replace
from pathlib import PurePosixPath

from app.domain.documents import ParsedSection

MIME_PDF = "application/pdf"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_MD = "text/markdown"
MIME_TXT = "text/plain"
MIME_CSV = "text/csv"
MIME_GOOGLE_DOC = "application/vnd.google-apps.document"
MIME_GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
# Google-native files have no bytes of their own: the Drive source exports them (Doc -> DOCX, Sheet -> XLSX) and the exported bytes are parsed.
NATIVE_EXPORT_MIME = {MIME_GOOGLE_DOC: MIME_DOCX, MIME_GOOGLE_SHEET: MIME_XLSX}

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
    """Can this file be indexed? (Google Docs/Sheets are supported through export.)"""
    return mime_type in SUPPORTED_MIME_TYPES or mime_type in NATIVE_EXPORT_MIME


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
    if mime_type in (MIME_DOCX, MIME_MD):
        # A chunk under a heading such as "Last date and late fine" must still know which circular it comes from, both for
        # the embedding and for the model reading it. (PDF pages carry a page number; table rows get their own identity prefix.)
        label = "Document: " + PurePosixPath(name).stem.replace("_", " ").strip()
        sections = [s if s.prefix else replace(s, prefix=label) for s in sections]
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
    return _carry_month_headings([page.extract_text() or "" for page in reader.pages])


_MONTH_HEADING = re.compile(
    r"^[ \t]*(January|February|March|April|May|June|July|August|September|October|November|December)[ \t]+(20\d\d)[ \t]*$", re.MULTILINE)
# A calendar entry starts with a day and its weekday ("01 (Mon)", "27, 28, 29 (Thu, Fri, Sat)", "21-22 (Sat-Sun)"), a day range on its
# own ("(13-18)") or a range with month names ("28 Aug- 03 Sep"). Lines that do not start like this belong to the entry above them.
_CALENDAR_ENTRY = re.compile(
    r"^[ \t]*(?:\d{1,2}(?:[ \t]*[-–,][ \t]*\d{1,2})*[ \t]*\([A-Za-z]{3}"
    r"|\(\d{1,2}[ \t]*[-–][ \t]*\d{1,2}\)"
    r"|\d{1,2}[ \t]+[A-Z][a-z]{2}[ \t]*[-–])",
    re.MULTILINE,
)
MIN_CALENDAR_ENTRIES = 5


def _carry_month_headings(pages: list[str]) -> list[ParsedSection]:
    """One section per page, except calendar pages: there, entries such as "10 (Tue) Holiday- Deepavali" only say which month they are in
    through a heading ("November 2026") that may be pages away, and a chunk without it cannot answer "what is the date of Deepavali?".
    So a calendar page is split at its month headings, and each dated entry becomes its own section that repeats "Month: <month year>"
    at the top of its chunk (thirty near-identical "Last date for submission of CIA ..." lines in one 900-character chunk cannot be
    told apart; one entry per chunk can). The month is carried across consecutive calendar pages and dropped on any other page, so a
    table of dates in a handbook never gets a month it does not belong to."""
    sections: list[ParsedSection] = []
    current: str | None = None
    for number, text in enumerate(pages, start=1):
        if len(_CALENDAR_ENTRY.findall(text)) < MIN_CALENDAR_ENTRIES:
            current = None
            sections.append(ParsedSection(text=text, page=number))
            continue
        marks = list(_MONTH_HEADING.finditer(text))
        starts = [0, *[m.start() for m in marks]]
        labels = [current, *[f"{m.group(1)} {m.group(2)}" for m in marks]]
        for start, end, label in zip(starts, [*starts[1:], len(text)], labels, strict=True):
            prefix = f"Month: {label}" if label else None
            piece = text[start:end]
            cuts = [m.start() for m in _CALENDAR_ENTRY.finditer(piece)]
            lead = piece[: cuts[0]] if cuts else piece
            if lead.strip() and not _MONTH_HEADING.fullmatch(lead.strip()):  # the month heading alone says nothing the prefix does not
                sections.append(ParsedSection(text=lead, page=number, prefix=prefix))
            for cut, stop in zip(cuts, [*cuts[1:], len(piece)], strict=False):  # no entries at all: `lead` above already holds the piece
                sections.append(ParsedSection(text=piece[cut:stop], page=number, prefix=prefix))
        current = labels[-1]
    return sections


# ---------------- markup inside cells ----------------
_HTML_TAGS = (r"html|body|style|script|table|thead|tbody|tfoot|tr|td|th|div|span|p|br|ul|ol|li|a|b|i|u|em|strong|h[1-6]|img|section|header|"
              r"footer|nav|form|input|label|button|pre|code|small|sup|sub|hr|font|center|blockquote")
_TAG = re.compile(rf"</?(?:{_HTML_TAGS})\b[^<>]*>", re.IGNORECASE)
_STYLE_SCRIPT = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_CELL_END = re.compile(r"</(?:td|th)\s*>", re.IGNORECASE)
_ROW_END = re.compile(r"</(?:tr|p|div|li|ul|ol|h[1-6]|table)\s*>|<br\s*/?>", re.IGNORECASE)
_HAS_CSS = re.compile(r"\{[^{}]*[\w-]+\s*:[^{}]*;[^{}]*\}")
# A CSS rule: selector(s) made of tag names, .classes, #ids, pseudo-classes or an @rule, then { declarations }. Plain words are never selectors.
_SELECTOR_UNIT = (rf"(?:@[\w-]+[^{{}}]{{0,120}}|(?:[.#][\w-]+|\b(?:{_HTML_TAGS})\b|\*)"
                  r"(?:[.#:][\w-]+(?:\([^)]*\))?|\[[^\]]*\])*)")
_CSS_RULE = re.compile(rf"{_SELECTOR_UNIT}(?:[\s,>+~]+{_SELECTOR_UNIT})*\s*\{{[^{{}}]*:[^{{}}]*\}}")
_EMPTY_AT_RULE = re.compile(r"@[\w-]+[^{}]{0,120}\{\s*\}")


def strip_markup(text: str) -> str:
    """Remove HTML tags and pasted CSS from a text cell, keeping the readable text. Text without markup is returned unchanged."""
    if not text or not (_TAG.search(text) or _HAS_CSS.search(text)):
        return text
    cleaned = text
    if _TAG.search(cleaned):
        cleaned = _STYLE_SCRIPT.sub(" ", cleaned)
        cleaned = _ROW_END.sub("\n", _CELL_END.sub(" | ", cleaned))
        cleaned = html.unescape(_TAG.sub(" ", cleaned)).replace("\xa0", " ")
    for _ in range(4):  # nested rules (an @media block around other rules) need a few passes
        reduced = _EMPTY_AT_RULE.sub(" ", _CSS_RULE.sub(" ", cleaned))
        if reduced == cleaned:
            break
        cleaned = reduced
    lines = (re.sub(r"\s*\|\s*$", "", re.sub(r"[ \t]+", " ", line)).strip() for line in cleaned.splitlines())
    return "\n".join(line for line in lines if line)


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
            sections.extend(_split_questions(body, heading))
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


MIN_QUESTIONS = 3
MAX_QUESTION_CHARS = 300


def _split_questions(body: str, heading: str | None) -> list[ParsedSection]:
    """An FAQ is a run of paragraphs: a one-line question ending in "?", then its answer. Chopped into fixed-size pieces, an answer ends up
    in a chunk with other questions' text and no longer matches its own question. So when a block holds several questions, each question
    and its answer become one section (named after the question, which is also what a citation shows). Any other text stays as it was."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    is_question = [("\n" not in p and p.endswith("?") and len(p) <= MAX_QUESTION_CHARS) for p in paragraphs]
    if sum(is_question) < MIN_QUESTIONS:
        return [ParsedSection(text=body, section=heading)]
    sections: list[ParsedSection] = []
    pending: list[str] = []  # text before the first question (an intro line), or one question with its answer paragraphs
    name = heading
    for paragraph, question in zip(paragraphs, is_question, strict=True):
        if question:
            if pending:
                sections.append(ParsedSection(text="\n\n".join(pending), section=name))
            pending, name = [paragraph], paragraph
        else:
            pending.append(paragraph)
    if pending:
        sections.append(ParsedSection(text="\n\n".join(pending), section=name))
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
    return " ".join(strip_markup(str(cell)).split()) if cell is not None else ""


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

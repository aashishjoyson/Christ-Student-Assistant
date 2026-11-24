"""Parsers keep page / heading / row-identity metadata (Phase 2). Files are generated in memory; no real documents."""

from __future__ import annotations

import pytest

from app.rag.parsers import (
    MIME_CSV,
    MIME_DOCX,
    MIME_MD,
    MIME_PDF,
    MIME_TXT,
    MIME_XLSX,
    ParseError,
    UnsupportedFileType,
    is_supported,
    mime_for_name,
    parse,
)
from tests.doc_factory import make_blank_pdf, make_docx, make_pdf, make_xlsx

LONG_FEES = "Tuition for the programme is payable per semester and includes laboratory and library access. " * 3  # > 80 chars


def test_pdf_gives_one_section_per_page_with_page_numbers() -> None:
    sections = parse(make_pdf(["Attendance is 85 percent.", "Hostel rules apply."]), MIME_PDF, "handbook.pdf")
    assert [(s.page, s.text.strip()) for s in sections] == [(1, "Attendance is 85 percent."), (2, "Hostel rules apply.")]


def test_scanned_pdf_without_text_is_a_clear_parse_error() -> None:
    with pytest.raises(ParseError, match="scanned"):
        parse(make_blank_pdf(), MIME_PDF, "scan.pdf")


def test_corrupt_pdf_error_does_not_leak_content() -> None:
    with pytest.raises(ParseError) as exc:
        parse(b"%PDF-1.4 SECRET-CONTENT garbage", MIME_PDF, "bad.pdf")
    assert "SECRET-CONTENT" not in str(exc.value) and "bad.pdf" in str(exc.value)


def test_docx_splits_at_headings_and_keeps_table_rows() -> None:
    docx = make_docx([("h1", "Attendance"), ("p", "Students need 85%."), ("h1", "Fees"), ("p", "Paid per term.")],
                     table=[["Item", "Amount"], ["Library", "500"]])
    sections = parse(docx, MIME_DOCX, "rules.docx")
    assert [(s.section, s.text.split("\n")[0]) for s in sections][:2] == [("Attendance", "Students need 85%."), ("Fees", "Paid per term.")]
    assert "Library | 500" in sections[-1].text  # the table is part of the last section


def test_markdown_splits_at_headings() -> None:
    md = b"Intro line\n\n# Dates\nTerm starts in July.\n\n## Exams\nExams in November.\n"
    sections = parse(md, MIME_MD, "cal.md")
    assert [(s.section, s.text) for s in sections] == [(None, "Intro line"), ("Dates", "Term starts in July."), ("Exams", "Exams in November.")]


def test_txt_is_a_single_section_and_decoding_falls_back() -> None:
    assert [s.text for s in parse("Café hours".encode("cp1252"), MIME_TXT, "a.txt")] == ["Café hours"]


def test_spreadsheet_rows_carry_their_identity_in_a_prefix() -> None:
    xlsx = make_xlsx({"courses": [["Course Name", "Campus", "Department", "Fees"],
                                  ["MBA", "Central", None, LONG_FEES],
                                  ["BCom", "Yeshwanthpur", "Commerce", LONG_FEES]]})
    sections = parse(xlsx, MIME_XLSX, "courses.xlsx")
    assert [s.section for s in sections] == ["MBA", "BCom"]
    assert sections[0].prefix == "Course Name: MBA; Campus: Central"  # empty cells are dropped
    assert sections[1].prefix == "Course Name: BCom; Campus: Yeshwanthpur; Department: Commerce"
    assert sections[0].text.startswith("Fees: Tuition for the programme")


def test_csv_without_long_cells_is_one_self_contained_section_per_row() -> None:
    sections = parse(b"Course,Campus\nMBA,Central\nBCom,North\n", MIME_CSV, "c.csv")
    assert [s.text for s in sections] == ["Course: MBA\nCampus: Central", "Course: BCom\nCampus: North"]


def test_unsupported_type_and_extension_mapping() -> None:
    with pytest.raises(UnsupportedFileType):
        parse(b"MZ", "application/octet-stream", "tool.exe")
    assert mime_for_name("Handbook.PDF") == MIME_PDF and mime_for_name("Courses_data.csv.xlsx") == MIME_XLSX
    assert mime_for_name("notes.docx") == MIME_DOCX and mime_for_name("x.exe") == "application/octet-stream"
    assert is_supported(MIME_CSV) and not is_supported("image/png")


def test_empty_document_is_an_error_not_a_silent_success() -> None:
    with pytest.raises(ParseError, match="no extractable text"):
        parse(b"   \n  ", MIME_TXT, "empty.txt")

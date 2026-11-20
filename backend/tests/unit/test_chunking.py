import pytest

from app.domain.chunking import chunk_sections, content_version, split_text
from app.domain.documents import ParsedSection

LONG = " ".join(f"Sentence number {i} explains a synthetic policy detail." for i in range(80))


def test_chunk_ids_are_deterministic() -> None:
    sections = [ParsedSection(LONG, page=1, section="Attendance")]
    first = chunk_sections("file-abc", sections, size=300, overlap=50)
    second = chunk_sections("file-abc", sections, size=300, overlap=50)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert len({c.chunk_id for c in first}) == len(first)


def test_version_changes_only_when_content_changes() -> None:
    a = [ParsedSection("Hello   world", page=1)]
    b = [ParsedSection("Hello world", page=1)]  # whitespace-only difference
    c = [ParsedSection("Hello world!", page=1)]
    assert content_version(a) == content_version(b)
    assert content_version(a) != content_version(c)


def test_chunks_respect_size_and_overlap() -> None:
    pieces = split_text(LONG, size=300, overlap=50)
    assert len(pieces) > 3
    assert all(len(p) <= 300 for p in pieces)
    # consecutive chunks share some text because of the overlap
    assert any(pieces[i][-20:] in pieces[i + 1] or pieces[i + 1][:20] in pieces[i] for i in range(len(pieces) - 1))


def test_metadata_preserved_and_sections_not_merged() -> None:
    sections = [ParsedSection("Page one text.", page=1, section="Intro"), ParsedSection("Page two.", page=2)]
    chunks = chunk_sections("f", sections)
    assert [(c.page, c.section) for c in chunks] == [(1, "Intro"), (2, None)]
    assert [c.index for c in chunks] == [0, 1]


def test_empty_text_produces_no_chunks() -> None:
    assert chunk_sections("f", [ParsedSection("   \n\n  ")]) == []


def test_invalid_overlap_rejected() -> None:
    with pytest.raises(ValueError):
        split_text("abc", size=100, overlap=100)

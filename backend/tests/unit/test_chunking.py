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


# ---- section prefix: identity repeated in EVERY chunk (e.g. the course name of a table row) ----
def test_prefix_is_repeated_in_every_chunk_and_size_is_respected() -> None:
    section = ParsedSection(LONG, section="Course X", prefix="Course Name: MBA; Campus: Central")
    chunks = chunk_sections("f", [section], size=300, overlap=50)
    assert len(chunks) > 3
    assert all(c.text.startswith("Course Name: MBA; Campus: Central\n") for c in chunks)
    assert all(len(c.text) <= 300 for c in chunks)
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_prefix_changes_the_version_and_a_section_without_prefix_is_unchanged() -> None:
    plain = [ParsedSection("Hello world", page=1)]
    prefixed = [ParsedSection("Hello world", page=1, prefix="Course: A")]
    assert content_version(plain) != content_version(prefixed)
    assert chunk_sections("f", plain)[0].text == "Hello world"  # old behaviour untouched


def test_an_oversized_prefix_is_rejected_instead_of_looping() -> None:
    with pytest.raises(ValueError, match="prefix"):
        chunk_sections("f", [ParsedSection("text", prefix="p" * 400)], size=300, overlap=50)

from app.domain.citations import build_citations, extract_citation_indices
from app.domain.documents import RetrievedChunk
from app.domain.prompts import RAG_SYSTEM_PROMPT, build_direct_messages, build_rag_messages

CHUNKS = [
    RetrievedChunk("f1:v:0000", "Classes begin on 1 July.", "SYNTHETIC_calendar.md", "f1", page=None, section="Dates"),
    RetrievedChunk("f2:v:0003", "Attendance must be 80%.", "SYNTHETIC_handbook.pdf", "f2", page=4, section=None),
]


def test_direct_prompt_has_no_context_and_includes_history() -> None:
    msgs = build_direct_messages("When do classes start?", [{"role": "user", "content": "hi"}])
    assert msgs[0]["role"] == "system"
    assert "NOT been given any official university documents" in msgs[0]["content"]
    assert msgs[-1] == {"role": "user", "content": "When do classes start?"}
    assert "Context passages" not in str(msgs)


def test_rag_prompt_numbers_passages_with_sources() -> None:
    msgs = build_rag_messages("When do classes start?", CHUNKS)
    assert msgs[0]["content"] == RAG_SYSTEM_PROMPT
    user = msgs[-1]["content"]
    assert "[1] (source: SYNTHETIC_calendar.md, section: Dates)" in user
    assert "[2] (source: SYNTHETIC_handbook.pdf, page 4)" in user


def test_extract_citation_indices_handles_groups() -> None:
    assert extract_citation_indices("A [2] and B [1, 2] and C [3][1]") == [2, 1, 3]


def test_build_citations_uses_cited_passages() -> None:
    cites = build_citations("Attendance is 80% [2].", CHUNKS)
    assert [(c.index, c.source_name, c.page, c.cited) for c in cites] == [(2, "SYNTHETIC_handbook.pdf", 4, True)]


def test_build_citations_falls_back_to_retrieved_when_uncited() -> None:
    cites = build_citations("Some answer without markers.", CHUNKS)
    assert len(cites) == 2
    assert not any(c.cited for c in cites)


def test_out_of_range_markers_ignored() -> None:
    cites = build_citations("See [9].", CHUNKS)
    assert len(cites) == 2 and not cites[0].cited

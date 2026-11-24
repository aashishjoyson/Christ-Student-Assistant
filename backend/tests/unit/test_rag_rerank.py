"""Lexical re-ranking: rare query words separate near-duplicates that embeddings blur together."""

from __future__ import annotations

import pytest

from app.domain.documents import RetrievedChunk
from app.rag.rerank import distinctive_words, lexical_scores, rerank, words


def chunk(chunk_id: str, text: str, distance: float) -> RetrievedChunk:
    return RetrievedChunk(chunk_id, text, "f.pdf", "f", distance=distance)


def test_stop_words_and_single_letters_are_not_distinctive() -> None:
    assert distinctive_words("What is the fee for the BBA programme?") == {"fee", "bba", "programme"}
    assert distinctive_words("When do applications open for MBA Session I?") == {"applications", "open", "mba", "session"}
    assert distinctive_words("Is 2027 a leap year?") == {"2027", "leap", "year"}  # numbers count, single letters do not
    assert distinctive_words("") == set()


def test_a_word_that_few_candidates_contain_counts_more() -> None:
    texts = ["the fee for the programme", "the fee for the programme in finance", "the fee for the programme in finance and economics"]
    scores = lexical_scores("fee programme finance economics", texts)
    assert scores[2] > scores[1] > scores[0]
    assert scores[2] == 1.0


def test_no_query_words_or_no_candidates_give_zero() -> None:
    assert lexical_scores("the of and", ["anything"]) == [0.0]
    assert lexical_scores("fee", []) == []


def test_a_rarer_match_beats_a_slightly_closer_vector() -> None:
    near_but_generic = chunk("a", "Commencement of classes for Session I semester students", 0.39)
    farther_but_exact = chunk("b", "When will applications open? Applications open for MBA Session I in October", 0.43)
    plain = rerank("When do applications open for MBA Session I?", [near_but_generic, farther_but_exact], 2, 0.0)
    assert [c.chunk_id for c in plain] == ["a", "b"]
    boosted = rerank("When do applications open for MBA Session I?", [near_but_generic, farther_but_exact], 2, 0.25)
    assert [c.chunk_id for c in boosted] == ["b", "a"]


def test_the_reported_distance_is_never_changed() -> None:
    chunks = [chunk("a", "alpha beta", 0.5), chunk("b", "gamma delta", 0.4)]
    out = rerank("alpha", chunks, 2, 0.3)
    assert {c.chunk_id: c.distance for c in out} == {"a": 0.5, "b": 0.4}


def test_zero_weight_keeps_the_vector_order_and_top_k_truncates() -> None:
    chunks = [chunk(str(i), f"text {i}", 0.1 * i) for i in range(1, 6)]
    assert [c.chunk_id for c in rerank("text 5", chunks, 3, 0.0)] == ["1", "2", "3"]
    assert len(rerank("text", chunks, 2, 0.2)) == 2


def test_ties_keep_the_order_the_vector_store_returned() -> None:
    chunks = [chunk("first", "same words", 0.4), chunk("second", "same words", 0.4)]
    assert [c.chunk_id for c in rerank("same words", chunks, 2, 0.2)] == ["first", "second"]


@pytest.mark.parametrize("weight", [-0.1, 0.0])
def test_a_non_positive_weight_is_a_no_op(weight: float) -> None:
    chunks = [chunk("a", "alpha", 0.5), chunk("b", "beta", 0.4)]
    assert [c.chunk_id for c in rerank("alpha", chunks, 2, weight)] == ["a", "b"]


def test_words_lowercases_and_splits_on_punctuation() -> None:
    assert words("Session-I, MBA (2027)!") == ["session", "i", "mba", "2027"]

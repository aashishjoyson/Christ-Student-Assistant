"""Evaluation metrics are pure functions, so each rule is pinned by a small example."""

from __future__ import annotations

import pytest

from app.domain.prompts import NO_EVIDENCE_ANSWER
from app.eval.metrics import (
    calibrate_threshold,
    citations_valid,
    fact_present,
    facts_recall,
    first_hit_rank,
    hit_at_k,
    is_refusal,
    normalize,
    percentile,
    reciprocal_rank,
    score_row,
    summarize,
)


@pytest.mark.parametrize(("answer", "fact"), [
    ("Deepavali is on **10 November 2026**.", "10 november"),
    ("Deepavali is on 10th November 2026", "10 november|november 10"),
    ("It falls on November 10.", "10 november|november 10"),
    ("The fee is INR 2,60,000 per year", "260000"),
    ("The fee is 2,60,000 INR", "2,60,000"),
    ("Registration fee of Rs. 5,000", "5000"),
    ("Classes are held from 01 November", "1 november"),
    ("Phones must be switched-off in class", "switched off"),
    ("Exams run 1-17 October", "17 october"),
    ("Exams run 11–13 December", "11-13 december"),
    ("Founder’s Day is on 3 January", "founder's day"),
])
def test_a_fact_is_found_however_it_is_written(answer: str, fact: str) -> None:
    assert fact_present(answer, fact)


@pytest.mark.parametrize(("answer", "fact"), [
    ("The fee is 15000", "5000"),  # whole numbers only
    ("It is on 11 November", "10 november"),
    ("Not stated.", "10 november|november 10"),
    ("", "anything"),
])
def test_a_fact_is_not_found_when_it_is_not_there(answer: str, fact: str) -> None:
    assert not fact_present(answer, fact)


def test_facts_recall_is_the_fraction_found_and_none_without_expectations() -> None:
    assert facts_recall("2 books for 14 days", ["2 books|two books", "14 days"]) == 1.0
    assert facts_recall("2 books", ["2 books|two books", "14 days"]) == 0.5
    assert facts_recall("anything", []) is None


def test_the_exact_system_refusal_and_softer_wordings_count_as_refusals() -> None:
    assert is_refusal(NO_EVIDENCE_ANSWER)
    assert is_refusal("I could not find this in the available university documents. Please contact the office.")
    assert is_refusal("**I could not find this in the available university documents.**")
    assert not is_refusal("Applications open in October [1].")


def test_citation_indices_must_point_at_supplied_passages() -> None:
    assert citations_valid("Open in October [1] and closes in May [2].", 2)
    assert not citations_valid("Open in October [3].", 2)
    assert not citations_valid("Open [0].", 4)
    assert citations_valid("No citations at all.", 0)


def test_citation_validity_uses_the_passages_the_model_was_given_not_the_citations_listed() -> None:
    answer = "Exams end on 17 October [1][3]."
    merged = [{"index": 1, "source_name": "calendar.pdf", "cited": True}]  # [1] and [3] came from one page, so the response lists one
    assert score_row(row(answer=answer, citations=merged, passages_supplied=4))["citations_valid"]
    assert not score_row(row(answer="See [5].", citations=merged, passages_supplied=4))["citations_valid"]
    assert not score_row(row(answer="It is on 10 November [1].", citations=[], passages_supplied=0))["citations_valid"]  # a model given no sources cited one


def test_retrieval_rank_hit_and_reciprocal_rank() -> None:
    rank = first_hit_rank(["handbook.pdf", "Calendar.PDF", "faq.md"], ["calendar.pdf"])
    assert rank == 2 and hit_at_k(rank, 2) and not hit_at_k(rank, 1) and reciprocal_rank(rank) == 0.5
    assert first_hit_rank(["a", "b"], ["c"]) is None and reciprocal_rank(None) == 0.0 and not hit_at_k(None, 4)


def test_percentiles_interpolate() -> None:
    assert percentile([100, 200, 300, 400], 50) == 250.0
    assert percentile([100, 200, 300, 400], 95) == 385.0
    assert percentile([5], 95) == 5.0 and percentile([], 50) is None


def row(**kw: object) -> dict:
    base: dict = {"mode": "rag", "case_id": "x", "category": "calendar", "answerable": True, "answer": "", "expected_facts": ["10 november"],
                  "expected_sources": ["calendar.pdf"], "retrieved_sources": ["calendar.pdf"], "rag": True, "latency_ms": 1000,
                  "citations": [{"index": 1, "source_name": "calendar.pdf", "cited": True}], "input_tokens": 100, "output_tokens": 20,
                  "est_cost_usd": 0.001}
    return base | kw


def scored(**kw: object) -> dict:
    r = row(**kw)
    return r | score_row(r)


def test_a_correct_cited_answer_scores_fully() -> None:
    s = score_row(row(answer="It is on 10 November 2026 [1]."))
    assert s["answered_correctly"] and s["citation_hit"] and s["citations_valid"] and s["retrieval_rank"] == 1 and not s["false_refusal"]


def test_a_false_refusal_and_an_unsupported_answer_are_told_apart() -> None:
    false_refusal = score_row(row(answer=NO_EVIDENCE_ANSWER))
    assert false_refusal["false_refusal"] and not false_refusal["answered_correctly"]
    unsupported = score_row(row(answerable=False, expected_facts=[], expected_sources=[], answer="The menu has biryani."))
    assert unsupported["unsupported_answer"] and not unsupported["correct_refusal"]
    right = score_row(row(answerable=False, expected_facts=[], expected_sources=[], answer=NO_EVIDENCE_ANSWER))
    assert right["correct_refusal"] and not right["unsupported_answer"]


def test_the_right_words_from_the_wrong_document_do_not_earn_a_citation_hit() -> None:
    s = score_row(row(answer="10 November [1]", citations=[{"index": 1, "source_name": "handbook.pdf", "cited": True}]))
    assert s["answered_correctly"] and not s["citation_hit"]


def test_summary_is_per_mode_and_per_category() -> None:
    rows = [
        scored(answer="10 November [1]", latency_ms=1000),
        scored(case_id="y", category="faq", answer=NO_EVIDENCE_ANSWER, latency_ms=3000, est_cost_usd=0.003, citations=[]),  # a refusal cites nothing
        scored(case_id="z", category="faq", answerable=False, expected_facts=[], expected_sources=[], answer=NO_EVIDENCE_ANSWER),
        scored(mode="direct", rag=False, answer="Probably 10 November", citations=[], retrieved_sources=[]),
    ]
    s = summarize(rows)
    rag, direct = s["rag"], s["direct"]
    assert (rag["n"], rag["n_answerable"], rag["n_unanswerable"]) == (3, 2, 1)
    assert rag["answer_accuracy"] == 0.5 and rag["false_refusal_rate"] == 0.5 and rag["correct_refusal_rate"] == 1.0
    assert rag["retrieval_hit_at_4"] == 1.0 and rag["retrieval_mrr"] == 1.0 and rag["citation_hit_rate"] == 0.5
    assert rag["latency_p50_ms"] == 1000.0 and rag["cost_usd_total"] == 0.005
    assert rag["by_category"]["faq"]["false_refusal_rate"] == 1.0 and rag["by_category"]["calendar"]["answer_accuracy"] == 1.0
    assert direct["answer_accuracy"] == 1.0 and direct["citation_hit_rate"] is None and direct["retrieval_mrr"] is None


def test_routing_is_measured_so_a_documents_question_sent_elsewhere_is_visible() -> None:
    rows = [scored(answer="10 November [1]", intent="academic_qa"), scored(case_id="y", answer="Please verify your identity.", intent="applicant_status")]
    s = summarize(rows)["rag"]
    assert s["routed_academic_rate"] == 0.5
    assert summarize([scored(answer="10 November")])["rag"]["routed_academic_rate"] is None  # no intent recorded


def test_failures_are_split_into_retrieval_misses_and_generation_misses() -> None:
    rows = [
        scored(answer="10 November [1]", evidence_in_context=True),  # evidence reached the model and it answered correctly
        scored(case_id="b", answer=NO_EVIDENCE_ANSWER, citations=[], evidence_in_context=True),  # evidence was there, the system still refused
        scored(case_id="c", answer=NO_EVIDENCE_ANSWER, citations=[], evidence_in_context=False),  # the evidence never reached the model
        scored(case_id="d", answer="10 November [1]", evidence_in_context=None),  # a case without evidence quotes is left out
    ]
    s = summarize(rows)["rag"]
    assert s["context_recall"] == round(2 / 3, 4)
    assert s["accuracy_when_evidence_present"] == 0.5


def test_refusal_rates_are_not_reported_for_a_mode_that_is_given_no_documents() -> None:
    s = summarize([scored(mode="direct", rag=False, answer="Probably 10 November", citations=[], retrieved_sources=[]),
                   scored(mode="direct", rag=False, case_id="u", answerable=False, expected_facts=[], expected_sources=[],
                          answer="I do not have the university documents.", citations=[], retrieved_sources=[])])["direct"]
    assert s["false_refusal_rate"] is None and s["correct_refusal_rate"] is None and s["unsupported_answer_rate"] is None
    assert s["answer_accuracy"] == 1.0


def test_errors_are_counted_and_excluded_from_latency_and_cost() -> None:
    rows = [scored(answer="10 November"), scored(case_id="e", answer="", error_code="model3_not_configured", latency_ms=5, est_cost_usd=None)]
    s = summarize(rows)["rag"]
    assert s["errors"] == 1 and s["latency_p50_ms"] == 1000.0 and s["cost_usd_total"] == 0.001


def test_threshold_calibration_separates_groups_and_reports_overlap() -> None:
    clean = calibrate_threshold([0.20, 0.25, 0.30, 0.35], [0.55, 0.60, 0.70], current=0.6)
    assert clean["status"] == "ok" and not clean["groups_overlap"] and clean["balanced_accuracy_at_recommended"] == 1.0
    assert 0.35 < clean["recommended_max_distance"] < 0.55 and clean["balanced_accuracy_at_current"] < 1.0
    messy = calibrate_threshold([0.2, 0.5, 0.65], [0.4, 0.7], current=0.6)
    assert messy["groups_overlap"] and messy["balanced_accuracy_at_recommended"] < 1.0
    assert calibrate_threshold([0.2], [])["status"] == "needs_both_groups"


def test_normalize_is_idempotent() -> None:
    once = normalize("The 10th of **November**, 2,60,000 - ok")
    assert normalize(once) == once

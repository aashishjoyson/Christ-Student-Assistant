"""The Model 3 training-set builder, with a fake teacher and a fake vector search: no network, no model."""

from __future__ import annotations

import json
import re

import pytest

from app.domain.documents import RetrievedChunk
from app.domain.prompts import NO_EVIDENCE_ANSWER, RAG_SYSTEM_PROMPT, build_rag_messages
from app.eval.metrics import citation_indices
from app.eval.peft_builder import BuildConfig, build_examples, pick_gold_chunks, usable_chunk
from app.eval.peft_data import (
    dataset_sha256,
    is_holdout_chunk,
    jaccard,
    number_groups,
    parse_teacher_reply,
    split_train_val,
    too_close_to_golden,
    validate_answerable,
)

PAD = " This sentence only pads the passage to a realistic length so that it passes the minimum size check for training."


def chunk(i: int, source: str, topic: str, number: int) -> RetrievedChunk:
    text = f"Rule {i}: the {topic} fee is {number} rupees per day.{PAD}"
    return RetrievedChunk(f"{source}:{i}", text, source, source, page=i, distance=None)


TOPICS = ["library", "parking", "laboratory", "gymnasium", "transport", "hostel", "canteen", "uniform", "exam", "certificate", "locker", "sports"]
CHUNKS = [chunk(i, "a.pdf" if i % 2 else "b.pdf", t, 30 + i * 7) for i, t in enumerate(TOPICS)]


def neighbours(text: str, k: int) -> list[RetrievedChunk]:
    return list(CHUNKS)[:k]


def good_teacher(messages: list[dict[str, str]]) -> str:
    """Reads the prompt exactly as the real teacher would: finds the gold passage number, then answers from that passage."""
    user = messages[1]["content"]
    gold = int(re.search(r"The answer is in passage \[(\d+)\]", user).group(1))  # type: ignore[union-attr]
    block = re.search(rf"\[{gold}\] \(source: [^)]*\)\n(.*?)(?:\n\n\[|\n>>>)", user, re.S).group(1)  # type: ignore[union-attr]
    topic, number = re.search(r"the (\w+) fee is (\d+) rupees", block).groups()  # type: ignore[union-attr]
    return json.dumps({"question": f"What is the daily {topic} fee charged to students?", "answer": f"The {topic} fee is {number} rupees per day [{gold}]."})


CFG = BuildConfig(calls=8, refusal_share=1.0, seed=3)


def build(**overrides):  # type: ignore[no-untyped-def]
    args = {"chunks": CHUNKS, "golden_questions": [], "evidence_quotes": [], "cfg": CFG, "neighbours": neighbours, "teacher": good_teacher}
    return build_examples(**{**args, **overrides})


def test_examples_have_exactly_the_serving_format() -> None:
    result = build()
    answerable = [e for e in result.examples if e["meta"]["kind"] == "answerable"]
    assert answerable
    first = answerable[0]
    ctx = [c for c in CHUNKS if c.chunk_id in first["meta"]["chunks"]]
    ordered = [next(c for c in ctx if c.chunk_id == cid) for cid in first["meta"]["chunks"]]
    expected = build_rag_messages(first["meta"]["question"], ordered)
    assert first["messages"][:-1] == expected and first["messages"][0]["content"] == RAG_SYSTEM_PROMPT
    assert first["messages"][-1]["role"] == "assistant"


def test_answers_cite_the_gold_passage_and_say_only_what_it_says() -> None:
    for e in (x for x in build().examples if x["meta"]["kind"] == "answerable"):
        n = citation_indices(e["messages"][-1]["content"])
        assert len(n) == 1
        gold_id = e["meta"]["gold_chunk"]
        assert e["meta"]["chunks"][n[0] - 1] == gold_id  # the [n] points at the passage the answer came from


def test_refusal_examples_use_the_exact_refusal_and_never_contain_the_answer() -> None:
    result = build()
    refusals = [e for e in result.examples if e["meta"]["kind"] == "refusal"]
    assert refusals and all(e["messages"][-1]["content"] == NO_EVIDENCE_ANSWER for e in refusals)
    for e in refusals:
        gold = next(c for c in CHUNKS if c.chunk_id == e["meta"]["gold_chunk"])
        assert gold.chunk_id not in e["meta"]["chunks"]  # the passage that answers it has been taken away
        number = re.search(r"is (\d+) rupees", gold.text).group(1)  # type: ignore[union-attr]
        assert all(number not in c.text for c in CHUNKS if c.chunk_id in e["meta"]["chunks"])


def test_passages_that_prove_an_evaluation_answer_never_reach_training() -> None:
    held_out = CHUNKS[3]
    quote = "gymnasium fee is 51 rupees per day"
    assert is_holdout_chunk(held_out.text, [quote]) and quote in held_out.text
    result = build(evidence_quotes=[quote])
    assert result.dropped["holdout_chunk"] == 1
    for e in result.examples:  # neither as the source of an answer nor as a distractor
        assert held_out.chunk_id not in e["meta"]["chunks"] and e["meta"]["gold_chunk"] != held_out.chunk_id


def test_a_question_that_is_an_evaluation_question_is_dropped() -> None:
    result = build(golden_questions=["What is the daily library fee charged to students?"])
    assert all("library" not in e["meta"]["question"] for e in result.examples)
    assert result.dropped["too_close_to_golden_question"] >= 1


def test_an_invented_number_is_rejected() -> None:
    def liar(messages: list[dict[str, str]]) -> str:
        gold = int(re.search(r"The answer is in passage \[(\d+)\]", messages[1]["content"]).group(1))  # type: ignore[union-attr]
        return json.dumps({"question": "What is the daily fee charged to students?", "answer": f"The fee is 9999 rupees per day [{gold}]."})

    result = build(teacher=liar)
    assert result.examples == [] and result.dropped["number_not_in_cited_passage"] == CFG.calls


@pytest.mark.parametrize(("reply", "reason"), [
    ("not json at all", "teacher_unparseable"),
    (json.dumps({"question": "q?"}), "teacher_unparseable"),
    (None, "teacher_unparseable"),
])
def test_unusable_teacher_replies_are_counted_not_crashed_on(reply: str | None, reason: str) -> None:
    result = build(teacher=lambda m: reply)
    assert result.examples == [] and result.dropped[reason] == CFG.calls


def test_the_same_question_is_never_used_twice() -> None:
    def same_question(messages: list[dict[str, str]]) -> str:
        data = json.loads(good_teacher(messages))
        data["question"] = "What is the daily fee charged to students at the university?"
        return json.dumps(data)

    result = build(teacher=same_question)
    assert sum(e["meta"]["kind"] == "answerable" for e in result.examples) == 1 and result.dropped["duplicate_question"] == CFG.calls - 1


def test_sources_take_turns_and_the_result_is_reproducible() -> None:
    import random

    picked = pick_gold_chunks(CHUNKS, BuildConfig(calls=6, seed=1), random.Random(1))  # noqa: S311 - reproducible, not security
    assert [c.source_name for c in picked] == ["a.pdf", "b.pdf"] * 3
    assert build().examples == build().examples
    assert build().examples != build(cfg=BuildConfig(calls=8, refusal_share=1.0, seed=4)).examples


def test_tiny_or_style_leftover_chunks_are_not_used() -> None:
    cfg = BuildConfig(calls=1)
    assert not usable_chunk(RetrievedChunk("x", "short", "a", "a"), cfg)
    assert not usable_chunk(RetrievedChunk("x", "ul { padding-left: 20px; } " + PAD * 2, "a", "a"), cfg)
    assert usable_chunk(CHUNKS[0], cfg)


def test_split_is_deterministic_disjoint_and_roughly_the_requested_size() -> None:
    items = [{"messages": [{"role": "user", "content": str(i)}], "meta": {"question": f"question number {i}"}} for i in range(400)]
    train, val = split_train_val(items, 0.1, seed=5)
    assert len(train) + len(val) == 400 and 20 <= len(val) <= 60
    assert not {i["meta"]["question"] for i in train} & {i["meta"]["question"] for i in val}
    assert split_train_val(items, 0.1, seed=5) == (train, val)


def test_dataset_hash_follows_the_messages_only() -> None:
    a = [{"messages": [{"role": "user", "content": "x"}], "meta": {"question": "1"}}]
    b = [{"messages": [{"role": "user", "content": "x"}], "meta": {"question": "different meta"}}]
    c = [{"messages": [{"role": "user", "content": "y"}], "meta": {"question": "1"}}]
    assert dataset_sha256(a) == dataset_sha256(b) != dataset_sha256(c) and len(dataset_sha256(a)) == 64


def test_teacher_replies_are_parsed_leniently_but_not_loosely() -> None:
    assert parse_teacher_reply('{"question": "Q  x?", "answer": "A [1]"}') == ("Q x?", "A [1]")
    assert parse_teacher_reply('```json\n{"question": "Q?", "answer": "A [1]"}\n```') == ("Q?", "A [1]")
    assert parse_teacher_reply('["question", "answer"]') is None and parse_teacher_reply('{"question": "", "answer": "A"}') is None


def test_numbers_are_compared_without_thousands_separators() -> None:
    assert number_groups("Fees are 2,60,000 INR and 8000/-, due 17 January 2027 (1 of 3).") == {"260000", "8000", "17", "2027"}


@pytest.mark.parametrize(("question", "answer", "reason"), [
    ("What is the library fee per day?", "The fee is 37 rupees per day [1].", None),
    ("What is the library fee per day?", "The fee is 37 rupees per day.", "no_citation"),
    ("What is the library fee per day?", "The fee is 37 rupees per day [4].", "invalid_citation"),
    ("What is the library fee per day?", "I could not find this in the available university documents [1].", "teacher_refused"),
    ("What is the library fee per day?", "37 [1]", "answer_length"),
    ("Fee?", "The fee is 37 rupees per day [1].", "question_shape"),
    ("What is the library fee per day?", "The fee is 38 rupees per day [1].", "number_not_in_cited_passage"),
])
def test_validation_reasons(question: str, answer: str, reason: str | None) -> None:
    passages = ["Rule 1: the library fee is 37 rupees per day.", "Rule 2: the parking fee is 12 rupees per day."]
    assert validate_answerable(question, answer, passages, NO_EVIDENCE_ANSWER) == reason


def test_question_similarity_uses_distinctive_words() -> None:
    assert jaccard("When is the library open?", "When is the library open on Sundays?") > 0.5
    assert too_close_to_golden("What is the attendance needed for the mid semester exam?", ["What attendance is needed for the mid semester exam?"])
    assert not too_close_to_golden("How do I get a bonafide certificate?", ["What attendance is needed for the mid semester exam?"])

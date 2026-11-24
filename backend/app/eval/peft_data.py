"""Helpers for building the Model 3 (LoRA) training set (stdlib only; no model, no network).

The adapter teaches BEHAVIOUR: answer only from the numbered passages, cite them as [n], and say "could not find" when they do not contain the
answer. It does not teach university facts (those stay in retrieval, so documents can change without retraining). These helpers keep that
promise honest: every example is checked, and nothing the evaluation relies on may leak into training.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence

from app.eval.metrics import citation_indices, normalize
from app.rag.rerank import distinctive_words

MAX_ANSWER_WORDS = 80
MIN_ANSWER_WORDS = 3
_NUMBER = re.compile(r"\d[\d.,]*\d|\d")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

TEACHER_SYSTEM = """You write training examples for a university student-helpdesk assistant.
You are given numbered passages from official documents and told which passage contains the answer.
Write ONE realistic question a student could ask that this passage answers, and the ideal short answer.
Rules for the question: self-contained (name the thing it is about), natural, one sentence, and it must not repeat the answer.
Rules for the answer: use ONLY facts that are in the passages; cite every passage you used as [n]; at most 60 words; never mention "passage" or
"context" in words, only the [n] markers; never add facts from your own knowledge.
Reply with JSON only, no other text: {"question": "...", "answer": "..."}"""


def build_teacher_messages(passages_block: str, gold_index: int) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": TEACHER_SYSTEM},
        {"role": "user", "content": f"Passages:\n<<<\n{passages_block}\n>>>\n\nThe answer is in passage [{gold_index}]."},
    ]


def parse_teacher_reply(text: str | None) -> tuple[str, str] | None:
    """The question and answer from the teacher's JSON reply, or None if it is not a clean object with both."""
    if not text:
        return None
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        data = json.loads(cleaned)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    question, answer = data.get("question"), data.get("answer")
    if not isinstance(question, str) or not isinstance(answer, str) or not question.strip() or not answer.strip():
        return None
    return " ".join(question.split()), answer.strip()


def number_groups(text: str) -> set[str]:
    """Numbers in a text with thousands separators removed, so "2,60,000" and "260000" match. Single digits are ignored: too common to prove anything."""
    return {re.sub(r"[,.]+$", "", n).replace(",", "") for n in _NUMBER.findall(text) if len(n.replace(",", "")) >= 2}


def validate_answerable(question: str, answer: str, passages: Sequence[str], answer_marker_refusal: str) -> str | None:
    """Why this teacher example must be rejected, or None if it is usable. `passages` are the texts shown to the teacher, in order."""
    words = len(answer.split())
    if not MIN_ANSWER_WORDS <= words <= MAX_ANSWER_WORDS:
        return "answer_length"
    if len(question.split()) < 4 or len(question) > 300:
        return "question_shape"
    if normalize(answer_marker_refusal)[:40] in normalize(answer):
        return "teacher_refused"
    cited = citation_indices(answer)
    if not cited:
        return "no_citation"
    if any(not 1 <= n <= len(passages) for n in cited):
        return "invalid_citation"
    cited_text = normalize(" ".join(passages[n - 1] for n in set(cited)))
    cited_text_nocomma = cited_text.replace(",", "")
    for number in number_groups(re.sub(r"\[\d+\]", "", answer)):
        if number not in cited_text_nocomma:
            return "number_not_in_cited_passage"  # a figure the passages do not contain: the teacher invented it
    if normalize(question) in normalize(answer):
        return "question_repeated"
    return None


def jaccard(a: str, b: str) -> float:
    left, right = distinctive_words(a), distinctive_words(b)
    return len(left & right) / len(left | right) if left | right else 0.0


def too_close_to_golden(question: str, golden_questions: Iterable[str], threshold: float = 0.6) -> bool:
    """A training question that is (nearly) one of the evaluation questions would let the adapter learn the test."""
    return any(jaccard(question, g) >= threshold for g in golden_questions)


def is_holdout_chunk(text: str, evidence_quotes: Iterable[str]) -> bool:
    """A passage that contains a golden-set proving quote. Such passages are kept out of training entirely (as an answer source and as a distractor)."""
    squashed = re.sub(r"\s+", "", text)
    return any(re.sub(r"\s+", "", quote) in squashed for quote in evidence_quotes if quote.strip())


def answered_by_other_passages(question: str, answer: str, passages: Sequence[str], max_overlap: float = 0.5) -> bool:
    """Used to build a REFUSAL example: True if any of these passages could answer the question (it shares most of the question's distinctive
    words, or it contains a figure from the answer). Such a passage must not appear in a context labelled "not in the documents"."""
    from app.rag.rerank import lexical_scores

    answer_numbers = number_groups(re.sub(r"\[\d+\]", "", answer))
    scores = lexical_scores(question, list(passages))
    for text, score in zip(passages, scores, strict=True):
        flat = normalize(text).replace(",", "")
        if score >= max_overlap or any(number in flat for number in answer_numbers):
            return True
    return False


def example_key(question: str) -> str:
    return normalize(question)


def split_train_val(items: Sequence[dict], val_fraction: float, seed: int) -> tuple[list[dict], list[dict]]:
    """Deterministic split by a hash of the question, so the same question is always on the same side and re-running changes nothing."""
    train: list[dict] = []
    val: list[dict] = []
    for item in items:
        digest = hashlib.sha256(f"{seed}:{example_key(item['meta']['question'])}".encode()).digest()
        (val if digest[0] / 255 < val_fraction else train).append(item)
    return train, val


def dataset_sha256(examples: Sequence[dict]) -> str:
    """A hash of exactly what the trainer will read (the messages, in order), recorded in the adapter manifest."""
    h = hashlib.sha256()
    for example in examples:
        h.update(json.dumps(example["messages"], ensure_ascii=False, sort_keys=True).encode())
        h.update(b"\n")
    return h.hexdigest()

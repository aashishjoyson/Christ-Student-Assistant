"""A Roman numeral "I" ("Session-I", "I semester") is a number, not the student talking about themselves.

Found by the golden-set evaluation: "When are the Session-I admission interviews held?" was routed to the personal interview path
(and asked the visitor to verify their identity) because the "I" in "Session-I" looked like a first-person pronoun.
"""

from __future__ import annotations

import pytest

from app.domain.intent_fallback import INTENT_PROMPT_VERSION, INTENT_SYSTEM_PROMPT, needs_llm_fallback
from app.domain.intents import Intent, classify_intent, strip_ordinals


@pytest.mark.parametrize(("message", "expected"), [
    ("When are the Session-I admission interviews held?", "When are the Session-1 admission interviews held?"),
    ("Dates for MBA Session I", "Dates for MBA Session 1"),
    ("exams for I semester UG and PG", "exams for 1 semester UG and PG"),
    ("results of the I Semester", "results of the 1 Semester"),
    ("I am worried about my interview", "I am worried about my interview"),  # a real first person is untouched
    ("session i think I will apply", "session i think I will apply"),  # lowercase "i" after a word is not guessed at
    ("I'm in semester three", "I'm in semester three"),
    ("Is it session I'm asking about?", "Is it session I'm asking about?"),
])
def test_roman_numeral_one_is_replaced_only_when_it_is_clearly_an_ordinal(message: str, expected: str) -> None:
    assert strip_ordinals(message) == expected


@pytest.mark.parametrize("message", [
    "When are the Session-I admission interviews held?",
    "When are the Session I interviews?",
    "What are the dates for I semester interviews?",
])
def test_general_questions_with_a_roman_one_stay_academic(message: str) -> None:
    assert classify_intent(message).intent == Intent.ACADEMIC_QA
    assert not needs_llm_fallback(message)  # and they do not spend a classification call either


@pytest.mark.parametrize(("message", "expected"), [
    ("When is my interview for Session-I?", Intent.INTERVIEW_DETAILS),
    ("I have not received my Session I interview email", Intent.RESEND_INTERVIEW_EMAIL),
    ("What is the status of my application for I semester?", Intent.APPLICANT_STATUS),
])
def test_a_real_first_person_next_to_a_roman_numeral_is_still_personal(message: str, expected: Intent) -> None:
    assert classify_intent(message).intent == expected


def test_the_classifier_prompt_keeps_policy_questions_out_of_unsupported_and_has_a_new_version() -> None:
    """Found by the evaluation: "How long does the refund take if I paid for the application but got no application number?" was
    labelled unsupported. The prompt now says what unsupported means (the student asks US to do it) and what it does not."""
    assert INTENT_PROMPT_VERSION == "intent-llm-v2"
    text = INTENT_SYSTEM_PROMPT.lower()
    assert "asks us to do" in text and "how long" in text and "refund" in text

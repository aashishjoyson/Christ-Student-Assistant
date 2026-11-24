"""Deterministic intent classification (no LLM call).

Order matters: unsupported actions -> resend -> interview -> application
status -> greetings/help -> academic question (default).

Personal intents (status, interview, resend) require a first-person cue
("my", "I", "me") or an application ID, so a general question such as
"When are MBA interviews held?" stays an academic question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Intent(StrEnum):
    ACADEMIC_QA = "academic_qa"
    APPLICANT_STATUS = "applicant_status"
    INTERVIEW_DETAILS = "interview_details"
    RESEND_INTERVIEW_EMAIL = "resend_interview_email"
    GENERAL_HELP = "general_help"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    rule: str  # which rule fired; recorded in traces for explainability


APPLICATION_ID_RE = re.compile(r"\bCUAPP-[A-Z0-9]+-\d{4}\b", re.IGNORECASE)

_PERSONAL = re.compile(r"\b(my|mine|i|i'm|i've|me)\b", re.IGNORECASE)

# "Session-I", "MBA Session I", "I semester": a Roman numeral one is a number, not the student speaking. Only an upper-case I that is
# clearly part of an ordinal is rewritten; "I'm" and a lower-case "i" are never guessed at.
_ORDINAL_NOUNS = r"session|semester|sem|trimester|term|year|part|phase|level|stage|round|batch|unit|module"
_ROMAN_ONE = re.compile(
    rf"(?i:\b(?:{_ORDINAL_NOUNS})[\s\-\u2013]+)I\b(?!['\u2019])|\bI(?=[\s\-\u2013]+(?i:{_ORDINAL_NOUNS})\b)"
)


def strip_ordinals(text: str) -> str:
    return _ROMAN_ONE.sub(lambda m: m.group(0)[:-1] + "1", text)  # every match ends in the "I" being replaced

_UNSUPPORTED_ACTION = re.compile(
    r"^\s*(please\s+)?((can|could|would|will)\s+you\s+)?(please\s+)?"
    r"(change|update|modify|edit|correct|cancel|withdraw|reschedule|delete|pay|waive|increase)\b"
    r".*\b(grade|grades|marks|attendance|application|interview|fee|fees|record|records|result|results)\b",
    re.IGNORECASE,
)

_RESEND = [
    re.compile(
        r"\b(not|never|didn't|didnt|did not|haven't|havent|have not|no)\b.{0,40}"
        r"\b(receive|received|get|got|gotten)\b.{0,40}\b(email|e-mail|mail|invite|invitation|link)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(resend|re-send|send)\b.{0,30}\b(interview)\b.{0,30}\b(email|e-mail|mail|invite|invitation|details|link)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bresend\b.{0,30}\b(email|e-mail|mail|invite|invitation)\b", re.IGNORECASE),
]

_INTERVIEW_WORD = re.compile(r"\binterviews?\b", re.IGNORECASE)
_INTERVIEW_DETAIL = re.compile(
    r"\b(when|where|time|date|day|schedule|scheduled|venue|location|link|mode|details|slot|online|offline)\b",
    re.IGNORECASE,
)

_STATUS = re.compile(
    r"\b(application|admission|applied)\b.*\b(status|update|progress|result|shortlist|shortlisted|selected|accepted|rejected|decision)\b"
    r"|\b(status|progress|update)\b.*\b(application|admission)\b",
    re.IGNORECASE,
)

_GREETING = re.compile(
    r"^\s*(hi|hello|hey|hii+|good (morning|afternoon|evening)|thanks|thank you|ok|okay)\b[\s!.?]*\w*[\s!.?]*$",
    re.IGNORECASE,
)

_CAPABILITY = re.compile(
    r"^\s*(help|what can you do|how can you help|who are you|what do you do)\b[\s?!.]*$", re.IGNORECASE
)


def _is_personal(text: str) -> bool:
    return bool(_PERSONAL.search(strip_ordinals(text)) or APPLICATION_ID_RE.search(text))


def classify_intent(message: str) -> IntentResult:
    text = " ".join(message.split())
    if not text:
        return IntentResult(Intent.GENERAL_HELP, "empty")

    if _UNSUPPORTED_ACTION.search(text):
        return IntentResult(Intent.UNSUPPORTED, "unsupported_action")

    personal = _is_personal(text)
    mentions_interview_or_email = re.search(r"\b(interview|email|e-mail|mail|invite|invitation)\b", text, re.I)

    if personal and mentions_interview_or_email and any(p.search(text) for p in _RESEND):
        return IntentResult(Intent.RESEND_INTERVIEW_EMAIL, "resend_pattern")

    if personal and _INTERVIEW_WORD.search(text) and _INTERVIEW_DETAIL.search(text):
        return IntentResult(Intent.INTERVIEW_DETAILS, "interview_pattern")

    if personal and _STATUS.search(text):
        return IntentResult(Intent.APPLICANT_STATUS, "status_pattern")

    if _GREETING.match(text) or _CAPABILITY.match(text):
        return IntentResult(Intent.GENERAL_HELP, "greeting_or_capability")

    return IntentResult(Intent.ACADEMIC_QA, "default_academic")

import pytest

from app.domain.intents import Intent, classify_intent


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # resend - clear first-person "did not receive" phrasing
        ("I have not received my interview email", Intent.RESEND_INTERVIEW_EMAIL),
        ("I didn't get the interview invite yet", Intent.RESEND_INTERVIEW_EMAIL),
        ("Can you resend my interview email?", Intent.RESEND_INTERVIEW_EMAIL),
        ("please send my interview details email again", Intent.RESEND_INTERVIEW_EMAIL),
        # interview details
        ("When is my interview?", Intent.INTERVIEW_DETAILS),
        ("What is the venue for my interview", Intent.INTERVIEW_DETAILS),
        ("my interview link please, is it online?", Intent.INTERVIEW_DETAILS),
        # application status
        ("What is the status of my application?", Intent.APPLICANT_STATUS),
        ("Has my application been shortlisted?", Intent.APPLICANT_STATUS),
        ("status of application CUAPP-DEMO-0003", Intent.APPLICANT_STATUS),
        # general help
        ("hi", Intent.GENERAL_HELP),
        ("Hello there!", Intent.GENERAL_HELP),
        ("what can you do?", Intent.GENERAL_HELP),
        ("", Intent.GENERAL_HELP),
        # unsupported actions
        ("Can you change my grade in maths?", Intent.UNSUPPORTED),
        ("please reschedule my interview to Friday", Intent.UNSUPPORTED),
        ("pay my fees", Intent.UNSUPPORTED),
        # academic questions (default), including non-personal interview/application questions
        ("When are MBA interviews usually held?", Intent.ACADEMIC_QA),
        ("What is the minimum attendance requirement?", Intent.ACADEMIC_QA),
        ("When is the fee payment deadline for semester 2?", Intent.ACADEMIC_QA),
        ("How do I change my elective course?", Intent.ACADEMIC_QA),
        ("What documents are needed for the application process?", Intent.ACADEMIC_QA),
    ],
)
def test_classify_intent(message: str, expected: Intent) -> None:
    assert classify_intent(message).intent == expected


def test_rule_is_reported_for_traces() -> None:
    result = classify_intent("When is my interview?")
    assert result.rule == "interview_pattern"


def test_resend_beats_interview_details_when_both_present() -> None:
    msg = "When is my interview? I never received the email"
    assert classify_intent(msg).intent == Intent.RESEND_INTERVIEW_EMAIL

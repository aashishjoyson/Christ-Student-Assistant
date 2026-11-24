"""Structure-aware parsing: calendar pages keep their month, FAQ answers stay with their question."""

from __future__ import annotations

from app.rag.parsers import MIME_MD, _carry_month_headings, parse

NL = chr(10)


def runs(sections) -> list[tuple[int | None, str | None]]:  # type: ignore[no-untyped-def]
    """(page, month prefix) of each consecutive run of sections: every dated entry is its own section, so runs show the month changes."""
    out: list[tuple[int | None, str | None]] = []
    for s in sections:
        if not out or out[-1] != (s.page, s.prefix):
            out.append((s.page, s.prefix))
    return out


def calendar_page(*entries: str, heading: str | None = None) -> str:
    lines = ([f"{heading} "] if heading else []) + list(entries)
    return NL.join(lines)


ENTRIES = [f"{day:02d} (Mon) Something happens {day}" for day in range(1, 7)]  # six dated entries: a calendar-like page


def test_every_piece_of_a_calendar_page_knows_its_month() -> None:
    page = NL.join(["June 2026 ", *ENTRIES, "July 2026 ", *ENTRIES])
    sections = _carry_month_headings([page])
    assert runs(sections) == [(1, "Month: June 2026"), (1, "Month: July 2026")]
    assert [s.prefix for s in sections] == ["Month: June 2026"] * 6 + ["Month: July 2026"] * 6  # one section per dated entry


def test_the_month_is_carried_across_the_page_break() -> None:
    first = NL.join(["November 2026 ", *ENTRIES])
    second = NL.join(ENTRIES)  # no heading at the top: still November
    third = NL.join(["December 2026 ", *ENTRIES])
    sections = _carry_month_headings([first, second, third])
    assert runs(sections) == [(1, "Month: November 2026"), (2, "Month: November 2026"), (3, "Month: December 2026")]


def test_a_page_that_is_not_a_calendar_gets_no_month_and_breaks_the_carry() -> None:
    calendar = NL.join(["November 2026 ", *ENTRIES])
    prose = "The handbook says that classes resume in June 2026 after the break."
    after = NL.join(ENTRIES)
    sections = _carry_month_headings([calendar, prose, after])
    assert runs(sections) == [(1, "Month: November 2026"), (2, None), (3, None)]  # never a month it does not belong to
    assert [s.text for s in sections if s.page == 2] == [prose]


def test_a_heading_on_a_page_with_few_dates_is_not_treated_as_a_calendar() -> None:
    page = NL.join(["June 2026 ", "01 (Mon) one entry only"])
    sections = _carry_month_headings([page])
    assert len(sections) == 1 and sections[0].prefix is None and sections[0].text == page


FAQ = NL.join([
    "# FAQs", "", "FAQs on application process", "",
    "When will applications open?", "", "Applications open in October.", "",
    "Where do I find the fees?", "", "Under Related Links.", "", "Fees are listed per programme.", "",
    "Why do I need a unique ID?", "", "It lets you apply for more than one programme.", "",
])


def test_each_faq_question_and_its_answer_become_one_section() -> None:
    sections = parse(FAQ.encode(), MIME_MD, "faq.md")
    by_name = {s.section: s.text for s in sections}
    assert "When will applications open?" in by_name
    assert by_name["When will applications open?"] == "When will applications open?" + NL * 2 + "Applications open in October."
    assert by_name["Where do I find the fees?"].endswith("Fees are listed per programme.")  # a two-paragraph answer stays together
    assert "Applications open in October." not in by_name["Where do I find the fees?"]  # and never mixes with another answer
    assert by_name["FAQs"].strip() == "FAQs on application process"  # the intro line keeps the heading as its name
    assert all(s.prefix == "Document: faq" for s in sections)


def test_ordinary_markdown_with_a_question_or_two_is_left_alone() -> None:
    text = NL.join(["# Notes", "", "Is the library open?", "", "Yes, until nine.", "", "More text follows here.", ""])
    sections = parse(text.encode(), MIME_MD, "notes.md")
    assert len(sections) == 1 and sections[0].section == "Notes" and "Is the library open?" in sections[0].text


def test_a_long_or_multiline_paragraph_ending_in_a_question_mark_is_not_a_question() -> None:
    long_one = "x" * 400 + "?"
    text = NL.join(["# T", "", long_one, "", "a?", "", "b?", "", "answer", ""])
    sections = parse(text.encode(), MIME_MD, "t.md")
    assert not any(s.section == long_one for s in sections)

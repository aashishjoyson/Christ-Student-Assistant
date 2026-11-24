"""Cleaning and splitting that the golden-set evaluation showed were needed.

1. Table cells that contain pasted HTML/CSS (25 of 312 course rows) produced chunks of pure style rules that still carried the
   course name, so they outranked the real fee text. Markup is now removed from cells; ordinary text is never touched.
2. Calendar pages are split per dated entry, so "18 (Sat) Last date for submission of CIA I marks ..." is its own small chunk
   instead of one line among thirty near-identical ones in a 900-character block.
"""

from __future__ import annotations

import pytest

from app.rag.parsers import _carry_month_headings, strip_markup

NL = chr(10)


def test_css_rules_pasted_into_a_cell_are_removed_and_the_real_text_survives() -> None:
    cell = ("body { font-family: Arial, sans-serif; margin: 0; background: #f6f8fb; } "
            ".container { max-width: 1100px; padding: 25px; } @media (max-width: 600px) { .container { padding: 10px; } } "
            "1. Admission Registration fee of INR 8000/ (Non-Refundable) 2. Programme fee as per the table")
    assert strip_markup(cell) == "1. Admission Registration fee of INR 8000/ (Non-Refundable) 2. Programme fee as per the table"


def test_a_cell_that_is_only_css_becomes_empty() -> None:
    assert strip_markup("x ul { padding-left: 20px; margin: 10px 0 0; list-style: disc; }") == "x"
    assert strip_markup(".guideline-box ul { padding-left: 20px; margin: 0; }") == ""


def test_html_tags_become_text_with_cells_and_rows_kept_apart() -> None:
    html = "<style>p { color: red; }</style><table><tr><th>Year</th><th>Fee</th></tr><tr><td>1</td><td>2,60,000 INR</td></tr></table><p>Pay on time&nbsp;&amp; save</p>"
    out = strip_markup(html)
    assert "color" not in out and "<" not in out
    assert "Year | Fee" in out and "1 | 2,60,000 INR" in out and "Pay on time & save" in out


@pytest.mark.parametrize("plain", [
    "Eligibility: a pass with a minimum of 55% in the postgraduate programme.",
    "Fees: 1. Admission Registration fee of INR 8000/ (Non-Refundable)",
    "Use the form {name} to apply",  # braces without style declarations are text
    "If x < 5 and y > 3 then apply",  # comparison signs are not tags
    "Karnataka: 2,60,000 INR; Other states: 2,80,000 INR",  # colons and semicolons alone are not CSS
    "",
])
def test_ordinary_text_is_never_changed(plain: str) -> None:
    assert strip_markup(plain) == plain


ENTRIES = [f"{day:02d} (Mon) Entry number {day} happens here" for day in range(1, 7)]


def test_a_calendar_page_is_split_into_one_section_per_dated_entry() -> None:
    page = NL.join(["July 2026 ", "06 (Mon) Commencement of classes for V semester UG BBA, ", "All Bangalore Campuses",
                    "09 (Thu) Last date for submission of CIA I Marks for I and IV trimester - MBA", *ENTRIES])
    sections = _carry_month_headings([page])
    texts = [s.text.strip() for s in sections]
    assert "06 (Mon) Commencement of classes for V semester UG BBA, " + NL + "All Bangalore Campuses" in texts  # a wrapped line stays with its entry
    assert "09 (Thu) Last date for submission of CIA I Marks for I and IV trimester - MBA" in texts
    assert all(s.prefix == "Month: July 2026" for s in sections) and all(s.page == 1 for s in sections)
    assert len(sections) >= 8


@pytest.mark.parametrize("entry", [
    "(13-18)" + NL + "(Mon-Sat) Mid Trimester Examinations",
    "27, 28, 29 (Thu, Fri, Sat) Convocation - Bangalore Central Campus",
    "21-22 (Sat-Sun) Daksh & Open Day",
    "28 Aug- 03 Sep" + NL + "(Fri-Thu) End trimester Examinations",
])
def test_ranges_and_lists_of_days_start_their_own_entries(entry: str) -> None:
    page = NL.join(["November 2026 ", *ENTRIES, entry, "30 (Mon) The last entry"])
    texts = [s.text.strip() for s in _carry_month_headings([page])]
    assert entry in texts

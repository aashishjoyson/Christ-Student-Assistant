"""Create the demo circulars used to show automatic ingestion live (see docs/DEMO_SCRIPT.md).

Run from the repo root (backend venv):  python scripts/make_demo_docs.py
Output: data/demo_docs/step1_add/*.docx (new documents), data/demo_docs/step2_edit/*.docx (a revised version of one of them).

They look like ordinary university circulars so the demo reads naturally, but every detail is FICTIONAL (reference numbers,
dates, fees, addresses on the reserved .example domain) and each file carries a small footer saying so. They are NOT indexed
unless you put them in the Drive folder, and you should delete them from Drive after the demo.
Each topic was checked against the real indexed documents: none of them is answered there today.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

OUT = Path(__file__).resolve().parents[1] / "data" / "demo_docs"
FOOTER = "Prepared for the helpdesk demonstration. The details in this circular are fictional."
NAVY = RGBColor(0x11, 0x30, 0x6B)


def circular(path: Path, *, ref: str, date: str, subject: str, intro: str, sections: list[tuple[str, list[str]]],
             signatory: str) -> None:
    doc = Document()
    head = doc.add_paragraph()
    head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = head.add_run("CHRIST UNIVERSITY")
    r.bold, r.font.size, r.font.color.rgb = True, Pt(18), NAVY
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run("Student Services · Circular").font.size = Pt(11)

    meta = doc.add_paragraph()
    meta.add_run(f"Ref: {ref}").bold = True
    meta.add_run(f"  Date: {date}")
    subj = doc.add_paragraph()
    subj.add_run("Subject: ").bold = True
    subj.add_run(subject).bold = True
    doc.add_paragraph(intro)

    for heading, lines in sections:
        doc.add_heading(heading, level=2)
        for line in lines:
            if line.startswith("- "):
                doc.add_paragraph(line[2:], style="List Bullet")
            elif line.startswith("# "):
                doc.add_paragraph(line[2:], style="List Number")
            else:
                doc.add_paragraph(line)

    sign = doc.add_paragraph()
    sign.paragraph_format.space_before = Pt(18)
    sign.add_run(signatory).bold = True
    note = doc.add_paragraph()
    nr = note.add_run(FOOTER)
    nr.italic, nr.font.size, nr.font.color.rgb = True, Pt(8), RGBColor(0x77, 0x77, 0x77)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    print("wrote", path.relative_to(OUT.parents[1]))


LIBRARY = "Circular_Extended_Library_Hours_Examination_Period.docx"
FEES = "Notice_Semester_Fee_Payment_Last_Date.docx"
LECTURE = "Notice_Guest_Lecture_Responsible_AI_in_Higher_Education.docx"
BONAFIDE = "Procedure_Bonafide_Certificate.docx"

# ------------------------------------------------------------------ step 1: four NEW documents
circular(
    OUT / "step1_add" / LIBRARY,
    ref="CU/LIB/2026-27/014", date="20 November 2026",
    subject="Extended library hours during the supplementary examination period",
    intro="In view of the supplementary and end-semester examinations beginning on 1 December 2026, the Central Library will "
          "extend its working hours as follows.",
    sections=[
        ("Extended library hours", [
            "- Monday to Saturday: 8:00 AM to 10:00 PM",
            "- Sundays and public holidays: 9:00 AM to 5:00 PM",
            "- Period: 1 December 2026 to 12 December 2026. Regular hours resume on 14 December 2026.",
        ]),
        ("Reading halls and borrowing", [
            "- The two reading halls on the first floor stay open for the full extended hours; entry is by university ID card.",
            "- Borrowing continues until 8:00 PM. Books issued in this period may be kept for 14 days.",
            "- Silence must be maintained in all reading areas; mobile phones must be on silent.",
        ]),
        ("Contact", ["Central Library help desk: library.helpdesk@christ-demo.example, extension 2240."]),
    ],
    signatory="Chief Librarian",
)
circular(
    OUT / "step1_add" / FEES,
    ref="CU/ACC/2026-27/031", date="20 November 2026",
    subject="Last date for payment of second-semester tuition fees",
    intro="Students are informed of the deadline for paying the second-semester tuition fees for the academic year 2026-27.",
    sections=[
        ("Last date and late fine", [
            "- Last date for payment without fine: 10 January 2027.",
            "- Late fine: Rs 100 per day after the last date, up to a maximum of Rs 1,000.",
            "- Students who have not paid by 25 January 2027 will not be issued a hall ticket for the second-semester examinations.",
        ]),
        ("How to pay", [
            "# Log in to the student fee portal with your register number.",
            "# Choose Semester 2 fees and pay by UPI, net banking or card.",
            "# Download the receipt and keep it for future reference.",
            "Payment by demand draft is accepted only at the Accounts Office counter, between 10:00 AM and 3:30 PM on working days.",
        ]),
        ("Help with payment", ["Accounts Office: accounts.office@christ-demo.example. Scholarship holders should first check "
                               "their fee status with the Scholarship Cell before paying."]),
    ],
    signatory="Finance Officer",
)
circular(
    OUT / "step1_add" / LECTURE,
    ref="CU/STU/2026-27/052", date="22 November 2026",
    subject="Guest lecture: Responsible use of AI in higher education",
    intro="The Office of Student Services invites all students to a guest lecture on the responsible use of artificial intelligence "
          "in study and research.",
    sections=[
        ("Lecture details", [
            "- Date and time: 3 December 2026, 2:00 PM to 3:30 PM.",
            "- Venue: Seminar Hall, Main Block.",
            "- Speaker: Dr. Meera Krishnan, visiting faculty in computer science.",
            "- Open to all undergraduate and postgraduate students; no fee.",
        ]),
        ("Registration", [
            "Register at your department office or at studentservices@christ-demo.example by 30 November 2026. Seats are limited to 250.",
            "A certificate of participation will be issued to students who attend the full session.",
        ]),
    ],
    signatory="Director, Student Services",
)
circular(
    OUT / "step1_add" / BONAFIDE,
    ref="CU/REG/2026-27/009", date="15 November 2026",
    subject="Procedure to obtain a bonafide certificate",
    intro="A bonafide certificate confirms that a student is currently enrolled. It is issued for passport, bank, scholarship "
          "and visa applications.",
    sections=[
        ("How to apply", [
            "# Submit the request form at the Student Services counter, or apply through the student portal under Certificates.",
            "# Carry your university ID card and state the purpose of the certificate.",
            "# Pay the fee of Rs 50 (Rs 100 for same-day issue) at the counter or on the portal.",
        ]),
        ("Processing time and collection", [
            "- The certificate is ready in 3 working days; same-day issue is available for urgent requests made before 12:00 noon.",
            "- Collect it from the Student Services counter between 10:00 AM and 4:00 PM. Another person may collect it only with your signed authorisation letter.",
        ]),
        ("Contact", ["Student Services counter, Ground Floor, Main Block: studentservices@christ-demo.example."]),
    ],
    signatory="Registrar",
)

# ------------------------------------------------------------------ step 2: a REVISED version of the fee notice (same file name)
circular(
    OUT / "step2_edit" / FEES,
    ref="CU/ACC/2026-27/031-R1", date="2 December 2026",
    subject="REVISED: Last date for payment of second-semester tuition fees",
    intro="This revised notice replaces circular CU/ACC/2026-27/031. The last date for paying the second-semester tuition fees "
          "has been extended.",
    sections=[
        ("Revised last date and late fine", [
            "- NEW last date for payment without fine: 17 January 2027 (extended from 10 January 2027).",
            "- Late fine: Rs 100 per day after the new last date, up to a maximum of Rs 1,000.",
            "- Students who have not paid by 31 January 2027 will not be issued a hall ticket for the second-semester examinations.",
        ]),
        ("How to pay", [
            "# Log in to the student fee portal with your register number.",
            "# Choose Semester 2 fees and pay by UPI, net banking or card.",
            "# Download the receipt and keep it for future reference.",
            "Payment by demand draft is accepted only at the Accounts Office counter, between 10:00 AM and 3:30 PM on working days.",
        ]),
        ("Help with payment", ["Accounts Office: accounts.office@christ-demo.example. Scholarship holders should first check "
                               "their fee status with the Scholarship Cell before paying."]),
    ],
    signatory="Finance Officer",
)

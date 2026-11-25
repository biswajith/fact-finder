"""Write the intake mock's sample documents into web/mock/public/samples/, and a zip of them all.

The mock does not read files: it knows these names and shows its own data for them (see data.ts).
The files are real (PDF, Word, Excel, text) so they can be dropped in like any upload, and so the
same bid can later be tried against the real app. Everything in them is made up.

    uv run python web/mock/make_samples.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pymupdf
from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font

OUT = Path(__file__).parent / "public" / "samples"


def pdf(path: Path, pages: list[list[tuple[str, str]]]) -> None:
    """A PDF from pages of (style, text) blocks: "h" a heading, "s" a speaker line, "p" a paragraph."""
    doc = pymupdf.open()
    for blocks in pages:
        page = doc.new_page()
        y = 64.0
        for style, text in blocks:
            size, font = {"h": (14, "hebo"), "s": (10, "hebo"), "p": (10.5, "helv")}[style]
            rect = pymupdf.Rect(64, y, page.rect.width - 64, page.rect.height - 56)
            left = page.insert_textbox(rect, text, fontsize=size, fontname=font)
            used = rect.height - left
            y += used + (10 if style == "h" else 2 if style == "s" else 8)
        page.insert_text((64, page.rect.height - 32), f"Page {doc.page_count} of {len(pages)}", fontsize=8, fontname="helv")
    doc.save(path)


def rfp(path: Path) -> None:
    pdf(path, [
        [("h", "CITY OF ALBANY - DEPARTMENT OF GENERAL SERVICES"),
         ("h", "REQUEST FOR PROPOSALS No. 2027-04"),
         ("p", "Transit Hub CCTV Replacement and Monitoring"),
         ("p", "Issue date: May 3, 2027"),
         ("p", "Proposals due: June 10, 2027, 2:00 PM Eastern"),
         ("p", "Contact: Dana Pike, Purchasing Office, City of Albany. All questions must be sent by email by May 24, 2027.")],
        [("h", "1. Scope of work"),
         ("p", "The City seeks a vendor to replace 212 cameras at the Transit Hub, install a new recording platform, and monitor "
               "the system around the clock for three years, with two option years."),
         ("p", "The vendor must keep the existing system running until the new one is accepted. A site visit will be held on May 17, 2027.")],
        [("h", "2. Instructions to proposers"),
         ("h", "2.1 Format of Proposals"),
         ("p", "Proposals shall not exceed 30 pages, excluding forms. Proposals must use 11 point type or larger."),
         ("p", "One signed original must be delivered to the Purchasing Office. Proposals received after June 10, 2027 will not be opened."),
         ("h", "2.2 Forms"),
         ("p", "Proposers must complete Attachment C, Price Form, and return it with the proposal.")],
        [("h", "3. Evaluation"),
         ("p", "Technical approach 40 points; transition plan 25 points; price 25 points; references 10 points."),
         ("p", "The City may interview the two highest-ranked proposers.")],
    ])


def addendum(path: Path) -> None:
    pdf(path, [
        [("h", "ADDENDUM NO. 1 to RFP No. 2027-04"),
         ("p", "Issued May 20, 2027"),
         ("p", "This addendum forms part of the RFP. Proposers must acknowledge it on the proposal cover page."),
         ("p", "1. The proposal due date is changed to June 24, 2027 at 2:00 PM Eastern."),
         ("p", "2. Section 2.1, Format of Proposals, is replaced in full by the following."),
         ("h", "2.1 Format of Proposals"),
         ("p", "Proposals shall not exceed 40 pages, excluding forms. Proposals must use 11 point type or larger. "
               "Proposals may be submitted through the City's bid portal or delivered to the Purchasing Office.")],
        [("p", "3. The site visit on May 17, 2027 is unchanged."),
         ("p", "All other terms of the RFP remain unchanged."),
         ("p", "Dana Pike, Purchasing Office")],
    ])


def qa(path: Path) -> None:
    doc = Document()
    doc.add_heading("Addendum 2 - Responses to bidder questions", 0)
    doc.add_paragraph("RFP No. 2027-04, Transit Hub CCTV Replacement and Monitoring")
    for q, a in [
        ("May bidders propose a phased cut-over?", "Yes. Describe each phase in the transition plan."),
        ("Is on-site storage of footage required?", "Thirty days on site; anything older may be stored off site in the United States."),
        ("Will the City provide the camera network drawings?", "Yes, to proposers who sign the confidentiality form."),
        ("Can the page limit exclude resumes?", "Yes. Resumes do not count toward the 40 pages."),
    ]:
        doc.add_heading(q, 2)
        doc.add_paragraph(a)
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Question deadline", "Answer"
    row = table.add_row()
    row.cells[0].text, row.cells[1].text = "Further questions", "No further questions will be answered."
    doc.save(path)


def price_form(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Price form"
    ws.append(["Attachment C - Price Form - RFP No. 2027-04 (issued May 3, 2027)"])
    ws["A1"].font = Font(bold=True)
    ws.append([])
    ws.append(["Item", "Unit", "Quantity", "Year 1", "Year 2", "Year 3", "Option year 1", "Option year 2"])
    for c in ws[3]:
        c.font = Font(bold=True)
    for item, unit, qty in [("Camera replacement", "each", 212), ("Recording platform", "lump sum", 1),
                            ("Monitoring service", "month", 12), ("Training", "day", 5)]:
        ws.append([item, unit, qty])
    ws.append([])
    ws.append(["Prices must include all taxes and fees. Sign below."])
    ws.append(["Authorized signature:", "", "", "Date:"])
    ws.column_dimensions["A"].width = 26
    wb.save(path)


CALL1 = [
    ("Tom Okafor", "0:04", "Morning all, thanks for making the time. I know the addendum only went out last week."),
    ("Dana Pike", "0:11", "Sure. Anything formal still has to go through Purchasing in writing, this is just so we are not talking past each other."),
    ("Dana Pike", "0:19", "Just to confirm, proposals are now due June 24 at 2 PM Eastern."),
    ("Lena Voss", "0:31", "Is the contract budget capped at ninety thousand, or is that a guide?"),
    ("Raj Mehta", "0:38", "It is capped. Council approved ninety for year one."),
    ("Ann Lee", "0:47", "From the advisory side, the county will weight the transition plan heavily. I would put real detail there."),
    ("Dana Pike", "1:02", "I think hand delivery to the clerk would probably be fine too, but do not hold me to that."),
    ("Tom Okafor", "1:15", "Understood. We will send our list of questions on Friday."),
]


def call_pdf(path: Path) -> None:
    head = [("h", "Capture call - Albany Transit Hub CCTV"),
            ("p", "Microsoft Teams - recorded and transcribed - May 27, 2027, 10:02 AM"),
            ("p", "Attendees: Tom Okafor, Lena Voss (Halvard Systems); Dana Pike, Raj Mehta (City of Albany); Ann Lee (Fenwick Advisory)")]
    turns = [b for who, t, said in CALL1 for b in (("s", f"{who}   {t}"), ("p", said))]
    pdf(path, [head + turns[:8], turns[8:]])


CALL2 = [
    ("Dana Pike", "00:00:02", "Thanks for joining. I have Kevin from IT on the line as well."),
    ("+1 518 555 0143", "00:00:09", "Hi, Kevin here, I look after the camera network at the hub."),
    ("Marco Ruiz", "00:00:15", "Thanks Kevin. On the price form, are option years priced per camera or as a lump sum?"),
    ("Dana Pike", "00:00:24", "Per camera. We will put that in writing in the next addendum."),
    ("+1 518 555 0143", "00:00:33", "And the existing fibre stays. You would not need to pull new cable to the platforms."),
    ("Tom Okafor", "00:00:41", "That helps a lot. We will reflect it in the transition plan."),
    ("Marco Ruiz", "00:00:48", "One more: is there a cap on the monitoring rate in year two?"),
    ("Dana Pike", "00:00:55", "No cap, but the council will compare it with year one."),
]


def call_txt(path: Path) -> None:
    lines = ["Clarification call - RFP 2027-04 Transit Hub CCTV", "June 3, 2027 - Microsoft Teams - transcript", ""]
    for who, t, said in CALL2:
        lines += [f"{who}  {t}", said, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


NOTES = """# Albany CCTV - capture notes

Exported from CRM on June 1, 2027

| Field | Value |
|---|---|
| Stage | Proposal |
| Close date | 2027-08-15 |
| Owner | Tom Okafor |
| Competitors | Northgate Security, Vantage Systems |

## What we heard

- Dana (Purchasing) is the gatekeeper; Raj in Finance holds the budget.
- Their budget is probably around 85k, my guess. Raj said 90 on the call, capped.
- Fenwick (Ann Lee) advises the county on the evaluation. Transition plan matters most to them.

## To do

- Send the reference list to Dana by Friday
- Ask whether option years can be priced per camera
- Check if Northgate bid the 2023 hub upgrade
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rfp(OUT / "RFP-2027-04 Transit Hub CCTV.pdf")
    addendum(OUT / "Addendum 1.pdf")
    qa(OUT / "Addendum 2 - Questions and answers.docx")
    price_form(OUT / "Attachment C - Price form.xlsx")
    call_pdf(OUT / "Capture call 2027-05-27.pdf")
    call_txt(OUT / "Clarification call 2027-06-03.txt")
    (OUT / "Deal notes - Albany CCTV.md").write_text(NOTES, encoding="utf-8")
    files = sorted(p for p in OUT.iterdir() if p.suffix != ".zip")
    with zipfile.ZipFile(OUT / "albany-cctv-sample-bid.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.name)
    for f in files:
        print(f.name)


if __name__ == "__main__":
    main()

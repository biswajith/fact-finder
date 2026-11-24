"""Cutters (cutters.py): transcripts, notes and sheets become units; stored units rebuild the document."""

import io
import json
from pathlib import Path

import pytest

from fact_extractor import cutters, results
from fact_extractor.api import document_from_units
from fact_extractor.models import Anchor

EXAMPLES = Path(__file__).parent.parent / "examples" / "multi-doc"


def read(name: str) -> bytes:
    return (EXAMPLES / name).read_bytes()


# --- any file, read by its format ---------------------------------------------------------------


def test_form_of_is_the_file_format_only():
    assert cutters.form_of("a.PDF", b"") == "pdf" and cutters.form_of("a.bin", b"%PDF-1.7") == "pdf"
    assert cutters.form_of("a.docx", b"PK") == "word"
    assert cutters.form_of("a.csv", b"") == "sheet" and cutters.form_of("a.xlsx", b"") == "sheet"
    assert cutters.form_of("a.json", b"{}") == "json"
    assert cutters.form_of("a.md", b"# t") == "text" and cutters.form_of("a.txt", b"[00:00:01] A: x") == "text"
    with pytest.raises(ValueError, match="read_document"):
        cutters.read(b"%PDF-1.7", "a.pdf")


def test_lines_that_each_say_something_stay_apart_and_a_wrapped_line_is_joined():
    units = cutters.read(b"Ann Lee: Hello all\nBo Kim: Thanks for\ncoming. Bye.\n", "call.txt")
    assert [u.text for u in units] == ["Ann Lee: Hello all", "Bo Kim: Thanks for coming.", "Bye."]


def test_any_json_is_read_as_its_text_whatever_the_keys():
    units = cutters.read(read("ulster-call-2026-08-12.gong.json"), "call.json")
    text = "\n".join(u.text for u in units)
    assert "name: Tom Okafor" in text and "Morning everyone, thanks for making time." in text
    assert cutters.read(b'{"a": {"b": ["x y", "z"]}, "n": 3}', "a.json")[0].text == "x y, z"
    assert [u.text for u in cutters.read(b"not json at all", "a.json")] == ["not json at all"]


def word_file() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading("Request for Proposals", 0)
    doc.add_heading("1. Scope", 1)
    doc.add_paragraph("The vendor must provide support. Proposals are due March 3, 2027.")
    doc.add_paragraph("Submit three copies.", style="List Bullet")
    t = doc.add_table(rows=2, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Item", "Requirement"
    t.rows[1].cells[0].text, t.rows[1].cells[1].text = "Uptime", "99.9%"
    doc.add_heading("2. Terms", 1)
    doc.add_paragraph("Three years.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_a_word_file_keeps_headings_lists_tables_and_sentences_in_order():
    units = cutters.read(word_file(), "rfp.docx")
    assert [(u.kind, u.text, u.page, u.section) for u in units] == [
        ("heading", "Request for Proposals", 1, "Request for Proposals"),
        ("heading", "1. Scope", 2, "1. Scope"),
        ("sentence", "The vendor must provide support.", 2, "1. Scope"),
        ("sentence", "Proposals are due March 3, 2027.", 2, "1. Scope"),
        ("list_item", "Submit three copies.", 2, "1. Scope"),
        ("table_row", "Item: Uptime | Requirement: 99.9%", 2, "1. Scope"),
        ("heading", "2. Terms", 3, "2. Terms"),
        ("sentence", "Three years.", 3, "2. Terms"),
    ]
    assert "Proposals are due March 3, 2027." in cutters.plain_text(word_file(), "rfp.docx", 20)


def test_read_document_reads_a_pdf_with_its_layout_and_anything_else_from_its_units(tmp_path):
    import pymupdf

    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Ann Lee: Hello all.")
    doc = cutters.read_document(pdf.tobytes(), "call.pdf", "call", tmp_path)
    assert [a.text for a in doc.anchors.values()] == ["Ann Lee: Hello all."] and doc.anchors["p1.1"].bbox
    doc = cutters.read_document(b"Ann Lee: Hello all.", "call.txt", "call", tmp_path)
    assert [a.text for a in doc.anchors.values()] == ["Ann Lee: Hello all."] and doc.anchors["p1.1"].bbox is None


# --- notes ---------------------------------------------------------------------------------

NOTES = """# Deal title

Exported 2026-08-14. Internal only.

| Field | Value |
|---|---|
| Stage | Proposal |
| Owner |  |
| Close | 2026-08-28 |

## Background

- First item that
  wraps over two lines.
- Second item. With two sentences.

A paragraph. It has two sentences.

## Risks

1. Numbered item
"""


def test_notes_cut_headings_items_rows_and_sentences():
    units = cutters.cut_notes(NOTES)
    got = [(u.kind, u.text, u.page, u.page_label, u.section) for u in units]
    assert got == [
        ("heading", "Deal title", 1, "0", "Deal title"),
        ("sentence", "Exported 2026-08-14.", 1, "0", "Deal title"),
        ("sentence", "Internal only.", 1, "0", "Deal title"),
        ("table_row", "Field: Stage | Value: Proposal", 1, "0", "Deal title"),
        ("table_row", "Field: Owner", 1, "0", "Deal title"),
        ("table_row", "Field: Close | Value: 2026-08-28", 1, "0", "Deal title"),
        ("heading", "Background", 2, "1", "Background"),
        ("list_item", "First item that wraps over two lines.", 2, "1", "Background"),
        ("list_item", "Second item. With two sentences.", 2, "1", "Background"),
        ("sentence", "A paragraph.", 2, "1", "Background"),
        ("sentence", "It has two sentences.", 2, "1", "Background"),
        ("heading", "Risks", 3, "2", "Risks"),
        ("list_item", "Numbered item", 3, "2", "Risks"),
    ]
    assert len({u.key for u in units}) == len(units)


def test_the_example_notes_start_a_page_for_each_section():
    units = cutters.cut_notes(read("ulster-deal-notes.md").decode())
    heads = [u for u in units if u.kind == "heading" and u.page_label.isdigit() and u.page_label != "0"]
    assert [h.page_label for h in heads if h.page_label][:3] == ["1", "2", "3"]
    assert len({u.page for u in units}) >= 4


# --- sheets --------------------------------------------------------------------------------


def test_csv_rows_are_table_rows_and_a_single_cell_row_is_a_sentence():
    data = "Item,Response,Notes\nUptime,,\nCompleted by the vendor,,\n,,\nSupport,24/7,yes\n".encode()
    units = cutters.cut_sheet(data, "t.csv")
    assert [(u.kind, u.text, u.page, u.page_label) for u in units] == [
        ("sentence", "Uptime", 1, "1"), ("sentence", "Completed by the vendor", 1, "1"),
        ("table_row", "Item: Support | Response: 24/7 | Notes: yes", 1, "1"),
    ]
    assert [u.key for u in units] == ["s1r2", "s1r3", "s1r5"]


def test_xlsx_one_sheet_is_one_page():
    from openpyxl import Workbook

    wb = Workbook()
    a = wb.active
    a.title = "Pricing"
    a.append(["Year", "Fee"])
    a.append([2027, 36000.0])
    b = wb.create_sheet("Terms")
    b.append(["Clause", "Text"])
    b.append(["Term", "Three years"])
    buf = io.BytesIO()
    wb.save(buf)
    units = cutters.cut_sheet(buf.getvalue(), "t.xlsx")
    assert [(u.text, u.page, u.page_label) for u in units] == [
        ("Year: 2027 | Fee: 36000", 1, "Pricing"), ("Clause: Term | Text: Three years", 2, "Terms")]


# --- stored units ----------------------------------------------------------------------------


def test_stored_units_rebuild_the_tagged_document_exactly(tmp_path):
    units = cutters.cut_notes(NOTES) + cutters.read(read("ulster-call-2026-08-12.txt"), "c.txt")[12:15]
    units = [u.__class__(f"k{n}", u.text, u.kind, u.page + (n > 12) * 10, u.page_label, u.section, "Ann" if n > 12 else "",
                         "buyer" if n > 12 else "") for n, u in enumerate(units)]
    doc, _ = document_from_units("notes-1", units)
    (tmp_path / "units.json").write_text(json.dumps(results.unit_rows(doc)), encoding="utf-8")
    back = results.load_document(tmp_path, "notes-1")
    assert back.tagged_text == doc.tagged_text and back.page_count == doc.page_count
    assert back.anchors == doc.anchors and list(back.anchors) == list(doc.anchors)
    assert any(a.speaker and a.side == "buyer" for a in back.anchors.values())
    assert results.load_document(tmp_path / "nope", "x") is None


def test_citation_carries_document_and_speaker_when_set():
    plain = Anchor("d", "p1.1", 1, "1", "S", "t", (1.0, 2.0, 3.0, 4.0), "sentence")
    assert plain.citation() == {
        "doc_id": "d", "id": "p1.1", "page": 1, "page_label": "1", "section": "S", "text": "t", "bbox": [1.0, 2.0, 3.0, 4.0]}
    said = Anchor("d", "p1.1", 1, "00:00:04", "", "t", None, "sentence", "Ann", "buyer")
    assert said.citation()["speaker"] == "Ann" and said.citation()["side"] == "buyer"

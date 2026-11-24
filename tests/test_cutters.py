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


# --- transcripts -------------------------------------------------------------------------


@pytest.mark.parametrize("call", ["ulster-call-2026-08-12", "durham-call-2024-07-24"])
def test_gong_and_text_forms_of_one_call_give_the_same_speakers_and_turns(call):
    g_units, g_info = cutters.cut_transcript(read(f"{call}.gong.json"), f"{call}.gong.json")
    t_units, t_info = cutters.cut_transcript(read(f"{call}.txt"), f"{call}.txt")
    assert [s["name"] for s in g_info["speakers"]] == [s["name"] for s in t_info["speakers"]]
    assert g_info["date"] == t_info["date"] and g_info["date"]
    assert len({u.page for u in g_units}) == len({u.page for u in t_units})
    assert [(u.page, u.page_label, u.speaker) for u in g_units] == [(u.page, u.page_label, u.speaker) for u in t_units]
    assert len(g_units) == len(t_units)


def test_gong_speakers_come_from_the_parties_and_silent_invitees_are_left_out():
    units, info = cutters.cut_transcript(read("ulster-call-2026-08-12.gong.json"), "x.json")
    names = [s["name"] for s in info["speakers"]]
    assert "Sam Lee" not in names and "+1 845-555-0142" in names  # no speakerId: never spoke; a dial-in has a number
    assert {s["affiliation"] for s in info["speakers"]} == {"Internal", "External", "Unknown"}
    assert len({u.key for u in units}) == len(units)
    assert units[0].page == 1 and units[0].page_label == "00:00:04" and units[0].section == "Small Talk"


def test_a_party_with_no_name_or_number_is_speaker_id():
    gong = {
        "extensive": {"calls": [{"metaData": {"started": "2026-01-02T10:00:00Z"}, "parties": []}]},
        "transcript": {"callTranscripts": [{"transcript": [
            {"speakerId": "77", "sentences": [{"start": 61000, "end": 62000, "text": "Hello. Yes."}]}]}]},
    }
    units, info = cutters.cut_transcript(json.dumps(gong).encode(), "c.json")
    assert [(u.speaker, u.page_label, u.text) for u in units] == [
        ("Speaker 77", "00:01:01", "Hello."), ("Speaker 77", "00:01:01", "Yes.")]
    assert info["date"] == "2026-01-02"


def test_text_transcript_merges_consecutive_lines_of_one_speaker():
    text = ("Meeting: Kick-off\nDate: March 3, 2027\n\n"
            "[00:00:01] Ann: First. Second.\n[00:00:09] Ann: Still Ann.\n[00:00:12] Bo: Reply here.\n")
    units, info = cutters.cut_transcript(text.encode(), "c.txt")
    assert [(u.page, u.speaker, u.text) for u in units] == [
        (1, "Ann", "First."), (1, "Ann", "Second."), (1, "Ann", "Still Ann."), (2, "Bo", "Reply here.")]
    assert info["title"] == "Kick-off" and info["date"] == "2027-03-03"


def test_not_a_gong_export_is_refused():
    with pytest.raises(ValueError, match="Gong"):
        cutters.cut_transcript(b'{"a": 1}', "x.json")


def test_form_of_guesses_from_name_and_content():
    assert cutters.form_of("a.PDF", b"") == "pdf" and cutters.form_of("a.bin", b"%PDF-1.7") == "pdf"
    assert cutters.form_of("a.csv", b"") == "sheet" and cutters.form_of("a.xlsx", b"") == "sheet"
    assert cutters.form_of("a.md", b"# t") == "notes" and cutters.form_of("a.txt", b"plain words") == "notes"
    assert cutters.form_of("a.txt", b"[00:00:01] A: x\n[00:00:02] B: y\n[00:00:03] A: z\n") == "transcript"
    assert cutters.form_of("a.json", read("ulster-call-2026-08-12.gong.json")) == "transcript"
    assert cutters.form_of("a.json", b'{"k": 1}') == "notes"
    with pytest.raises(ValueError, match="tag_pdf"):
        cutters.cut("pdf", b"", "a.pdf")


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


def test_the_file_decides_how_it_is_read_and_the_playbook_only_how_text_is_read():
    assert cutters.reader("notes", "deal.pdf", b"%PDF-1.7") == "pdf"
    assert cutters.reader("notes", "crm.xlsx", b"PK") == "sheet"
    assert cutters.reader("pdf", "requirements.xlsx", b"PK") == "sheet"
    assert cutters.reader("pdf", "notes.md", b"# notes") == "notes"
    assert cutters.reader("notes", "notes.md", b"# notes") == "notes"
    assert cutters.reader("transcript", "call.txt", b"Dana: hi") == "transcript"
    assert cutters.reader("sheet", "x.txt", b"hello") == "notes"


# --- stored units ----------------------------------------------------------------------------


def test_stored_units_rebuild_the_tagged_document_exactly(tmp_path):
    units = cutters.cut_notes(NOTES) + cutters.cut_transcript(read("ulster-call-2026-08-12.txt"), "c.txt")[0][:3]
    units = [u.__class__(f"k{n}", u.text, u.kind, u.page + (n > 12) * 10, u.page_label, u.section, u.speaker, "buyer" if u.speaker else "")
             for n, u in enumerate(units)]
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

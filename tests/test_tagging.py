import pymupdf

from fact_extractor.pdf import read_pdf
from fact_extractor.tagging import Page, Paragraph, split_sentences, tag_pages


def test_ids_sections_and_text(doc):
    a = doc.anchors
    assert list(a)[:6] == ["p1.h1", "p1.1", "p1.2", "p1.h2", "p1.3", "p1.4"]
    assert a["p1.3"].text == "Proposals are due March 3, 2027 at 5:00 PM Eastern."
    assert a["p1.3"].section == "2. Schedule"
    assert a["p1.3"].page_label == "i"
    assert a["p2.t1r1"].text == "Item: Support hours | Requirement: 24/7 | Mandatory: Yes"
    assert a["p2.t1r1"].kind == "table_row"
    assert "[p1.3] Proposals are due March 3, 2027 at 5:00 PM Eastern.\n" in doc.tagged_text
    # Table cells use ";" in the model text so "|" never appears in the input.
    assert "[p2.t1r1] Item: Support hours ; Requirement: 24/7 ; Mandatory: Yes" in doc.tagged_text


def test_numbering_restarts_per_page(doc):
    assert "p2.1" in doc.anchors and "p3.1" in doc.anchors
    assert doc.anchors["p3.2"].section == "4. Submission"


def test_brackets_in_source_are_escaped():
    d = tag_pages("x", [Page(1, "1", [Paragraph.of("See [p9.9] and [Note].")])])
    assert "[p9.9]" not in d.tagged_text
    assert d.anchors["p1.1"].text == "See [p9.9] and [Note]."


def test_sentence_split_keeps_abbreviations_and_numbers():
    t = "Send to Mr. Smith at 4.2 Main St. by Jan. 5. Late bids, e.g. after 5 p.m. ET, are rejected. Done."
    parts = [t[s:e] for s, e in split_sentences(t)]
    assert parts == [
        "Send to Mr. Smith at 4.2 Main St. by Jan. 5.",
        "Late bids, e.g. after 5 p.m. ET, are rejected.",
        "Done.",
    ]


def test_long_sentence_split_at_semicolons():
    long = "; ".join(["the vendor shall do item number %d now" % i for i in range(10)]) + "."
    d = tag_pages("x", [Page(1, "1", [Paragraph.of(long)])])
    assert len(d.anchors) == 10
    short = "A shall do x; B shall do y."
    assert len(tag_pages("x", [Page(1, "1", [Paragraph.of(short)])]).anchors) == 1


def test_read_pdf(tmp_path):
    path = tmp_path / "rfp.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 90), "4.2 Submission Deadline", fontsize=16)
    page.insert_text((72, 130), "Questions must be sent by email to the contracting officer.", fontsize=10)
    page.insert_text((72, 145), "All proposals must be received no later than 5:00 PM Eastern.", fontsize=10)
    page.insert_text((300, page.rect.height - 20), "11", fontsize=9)
    pdf.save(path)

    d = tag_pages("rfp", read_pdf(str(path)))
    a = d.anchors
    assert a["p1.h1"].text == "4.2 Submission Deadline"
    assert a["p1.2"].text == "All proposals must be received no later than 5:00 PM Eastern."
    assert a["p1.2"].section == "4.2 Submission Deadline"
    assert a["p1.2"].page_label == "11"
    assert a["p1.2"].bbox is not None
    assert "11" not in [x.text for x in a.values()]


def test_list_item_sentences_and_hyphen_joins():
    from fact_extractor.tagging import Span

    d = tag_pages("x", [Page(1, "1", [
        Paragraph([Span("•Optional services. Provide your hourly rates.")], list_item=True),
        Paragraph([Span("The Self-"), Span("Insurance Plan needs manage-"), Span("ment.")]),
    ])])
    a = d.anchors
    assert a["p1.1"].kind == "list_item" and a["p1.2"].kind == "sentence"
    assert a["p1.2"].text == "Provide your hourly rates."
    assert a["p1.3"].text == "The Self-Insurance Plan needs management."

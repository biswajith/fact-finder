from fact_extractor import xref
from fact_extractor.tagging import Heading, Page, Paragraph, tag_pages


def _doc():
    return tag_pages("c", [
        Page(1, "1", [
            Heading("ARTICLE 1 - SCOPE OF SERVICES"),
            Heading("ARTICLE 2 – INTENTIONALLY LEFT BLANK"),
            Heading("ARTICLE 3 - CONFIDENTIALITY"),
            Heading("SCHEDULE A"),
        ]),
        Page(2, "2", [
            Paragraph.of(
                "Obligations under Article 1 (Scope of Services), Article 2 (Intellectual Property) and "
                "Article 3 (Publicity) survive. Article 15 of the Executive Law applies. "
                "See Article 3 of this Agreement and Schedule A. Article 9 governs disputes. "
                "Attachment F lists claims."
            ),
        ]),
    ])


def test_blank_wrong_title_and_missing_targets():
    lines = sorted(f.text for f in xref.check(_doc()))
    assert lines == [
        "Cross-reference to Article 2 (Intellectual Property), but Article 2 is intentionally left blank",
        "Cross-reference to Article 3 (Publicity), but Article 3 is titled Confidentiality",
        "Cross-reference to Article 9, but the document has no Article 9",
    ]
    blank = next(f for f in xref.check(_doc()) if "blank" in f.text)
    assert blank.ids == ["p2.1", "p1.h2"] and blank.category == "Q" and blank.source_call == "XREF"


def test_no_headings_of_a_kind_means_no_check(doc):
    assert xref.check(doc) == []


async def test_xref_reaches_the_store():
    from conftest import ScriptedClient, task_name

    from fact_extractor.pipeline import Config, extract

    def h(req):
        if task_name(req) == "K1":
            return "C|Article 2 obligations survive termination|p2.1|risk\nEND|1\n"
        return "END|0\n"

    res = await extract(_doc(), ScriptedClient(h), deal_id="d", cfg=Config(backoff_base=0, passes=1, sweep_all=False))
    q = [f for f in res.facts if f["category"] == "Q" and f["source_call"] == "XREF"]
    assert len(q) == 3 and res.report["xref_conflicts"] == 3
    survive = next(f for f in res.facts if f["category"] == "C")
    # The Article 9 reference is its own sentence (p2.3), so only two Q facts touch p2.1.
    assert survive["status"] == "conflict" and len(survive["conflicts"]) == 2
    assert q[0]["citations"][0]["text"].startswith("Obligations under Article 1")

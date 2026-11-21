"""Cross-reference check: the model finds references, code verifies them (xref.py)."""

import pytest
from conftest import task_name
from test_units import scripted

from fact_extractor import units, xref
from fact_extractor.tagging import Heading, Page, Paragraph, tag_pages

# p1.h1 1. Scope            p1.1 ... Section 3 below.      p1.2 ... Section 5 above.
# p1.h2 2. Insurance Req.   p1.3 Carry the coverage.       p1.4 See Section 2 (Publicity) for details.
# p1.h3 3. INTENTIONALLY LEFT BLANK
# p2.h1 4. Submission       p2.1 Return Attachment A - EBOP Form with the bid.  p2.2 Refer to
# p2.3 Complete the Workforce Form, Attachment D.   p2.4 Pricing Sheet is Attachment B and Attachment C.
# p2.5 See Appendix B - Pricing Sheet.   p2.6 See "4. Submission" and Article 15 of the Executive Law.
# p2.7 Insurance is described in Schedule 9.   p2.8 Use clause 4(b) as written.


def _doc():
    return tag_pages("c", [
        Page(1, "1", [
            Heading("1. Scope"),
            Paragraph.of("Follow the rules in Section 3 below. Return the forms listed in Section 5 above."),
            Heading("2. Insurance Requirements"),
            Paragraph.of("Carry the coverage. See Section 2 (Publicity) for details."),
            Heading("3. INTENTIONALLY LEFT BLANK"),
        ]),
        Page(2, "2", [
            Heading("4. Submission"),
            Paragraph.of("Return Attachment A - EBOP Form with the bid."),
            Paragraph.of("Refer to"),
            Paragraph.of("Complete the Workforce Form, Attachment D."),
            Paragraph.of("The Pricing Sheet is Attachment B and Attachment C."),
            Paragraph.of("See Appendix B - Pricing Sheet."),
            Paragraph.of("See \u201cSubmission\u201d and Article 15 of the Executive Law."),
            Paragraph.of("Insurance is described in Schedule 9."),
            Paragraph.of("Use clause 4(b) as written."),
        ]),
    ])


def _ref(unit, text, target, kind="section"):
    return xref.Ref(unit, text, target, kind)


def _problems(refs, doc=None):
    return xref.verify(doc or _doc(), refs).problems


# --- parser -------------------------------------------------------------------------------


def test_parse_good_lines_and_end_count():
    p = xref.parse(
        "REF|p1.1|Section 3 below|p1.h3|section\n"
        "ref|[p1.2]|Section 5 above|NONE|Section\n"
        "REF|p2.1|Attachment A|none|attachment\n"
        "REF|p2.6|Article 15 of the Executive Law||external\n"
        "END|4\n"
    )
    assert [(r.unit, r.text, r.target, r.kind) for r in p.refs] == [
        ("p1.1", "Section 3 below", "p1.h3", "section"),
        ("p1.2", "Section 5 above", None, "section"),
        ("p2.1", "Attachment A", None, "attachment"),
        ("p2.6", "Article 15 of the Executive Law", None, "external"),
    ]
    assert p.declared == 4 and p.malformed == 0 and p.usable


def test_parse_malformed_lines_are_counted_not_used():
    p = xref.parse(
        "REF|p1.1|only four fields|section\n"
        "REF|p1.1|text|p1.h3|chapter\n"      # unknown kind
        "REF||text|none|section\n"           # no unit
        "REF|p1.1||none|section\n"           # no text
        "Some chatter\n"
        "REF|p1.1|a | b|none|section\n"      # a | inside the text is kept
        "END|x\n"
    )
    assert p.malformed == 4 and [r.text for r in p.refs] == ["a|b"] and p.declared is None


def test_parse_nothing_usable():
    assert not xref.parse("I could not find any references.").usable
    assert xref.parse("END|0").usable and xref.parse("END|0").refs == []


# --- drop rules ---------------------------------------------------------------------------


def test_lines_with_unknown_unit_or_text_not_in_unit_are_dropped():
    refs = [
        _ref("p9.9", "Section 3 below", "p1.h3"),            # no such unit
        _ref("p1.1", "Section 7 below", "p1.h3"),            # text is not in that unit
        _ref("p1.1", "  SECTION 3  BELOW ", "p1.h3"),   # case and whitespace do not matter
        _ref("p2.6", "\"Submission\"", "p2.h1"),          # curly quotes in the unit, straight in the line
    ]
    res = xref.verify(_doc(), refs)
    assert res.found == 4 and res.dropped == 2 and res.checked == 2


# --- rules a to f -------------------------------------------------------------------------


def test_a_target_given_but_not_in_the_document():
    (p,) = _problems([_ref("p1.1", "Section 3 below", "p7.7")])
    assert p.rule == "missing" and p.ids == ("p1.1",) and "no such part" in p.text


def test_b_target_is_blank():
    (p,) = _problems([_ref("p1.1", "Section 3 below", "p1.h3")])
    assert p.rule == "blank" and p.ids == ("p1.1", "p1.h3") and "INTENTIONALLY LEFT BLANK" in p.text


def test_c_target_none_for_something_specific():
    (p,) = _problems([_ref("p2.7", "Schedule 9", None, "section")])
    assert p.rule == "absent" and "not in the document" in p.text
    (p,) = _problems([_ref("p2.8", "clause 4(b)", None)])
    assert p.rule == "absent"
    (p,) = _problems([_ref("p2.6", '"Submission"', None)])  # a quoted title
    assert p.rule == "absent"


def test_c_a_vague_reference_or_an_absent_attachment_is_not_an_error():
    assert _problems([_ref("p2.1", "Attachment A", None, "attachment")]) == []  # often supplied separately
    assert _problems([_ref("p2.5", "Appendix B", None, "attachment")]) == []
    assert _problems([_ref("p2.2", "the form", None, "attachment")]) == []
    assert _problems([_ref("p1.1", "the rules", None)]) == []  # nothing specific is named
    # An attachment said to be in this document, and not there, is an error.
    d = tag_pages("c", [Page(1, "1", [Paragraph.of("The Pricing Sheet is Attachment B below.")])])
    (p,) = xref.verify(d, [_ref("p1.1", "Attachment B below", None, "attachment")]).problems
    assert p.rule == "absent"


def test_c_blank_placeholder():
    (p,) = _problems([_ref("p2.2", "Refer to", None)])
    assert p.rule == "placeholder" and "left blank" in p.text and p.ids == ("p2.2",)
    d = tag_pages("c", [Page(1, "1", [Paragraph.of("For the list, see ____ below."), Paragraph.of("Details: Attachment [insert].")])])
    for unit, text in (("p1.1", "see ____"), ("p1.2", "Attachment [insert]")):
        (p,) = xref.verify(d, [_ref(unit, text, None, "attachment")]).problems
        assert p.rule == "placeholder"
    assert xref.is_placeholder("refer to [ ]") and xref.is_placeholder("Refer to") and xref.is_placeholder("see Section ___")
    assert not xref.is_placeholder("the form") and not xref.is_placeholder("see Section 4") and not xref.is_placeholder("Attachment C")


def test_d_title_mismatch():
    (p,) = _problems([_ref("p1.4", "Section 2 (Publicity)", "p1.h2")])
    assert p.rule == "title" and p.ids == ("p1.4", "p1.h2") and "Insurance Requirements" in p.text
    # The same title, in another case, with an outline number in front, is fine.
    assert _problems([_ref("p1.4", "Section 2 (INSURANCE requirements)", "p1.h2")]) == []
    assert _problems([_ref("p2.6", "“4. Submission”", "p2.h1")]) == []
    assert _problems([_ref("p1.4", "Section 2", "p1.h2")]) == []  # no title in the reference


def test_title_overlap_threshold():
    a, b = xref.tokens("Receipt Confirmation Form"), xref.tokens("Return Confirmation Form")
    assert xref.overlap(a, b) >= xref.TITLE_OVERLAP  # one word of three apart: tolerated
    assert xref.overlap(xref.tokens("Intellectual Property Rights"), xref.tokens("Confidentiality")) < xref.TITLE_OVERLAP


def test_e_direction():
    (p,) = _problems([_ref("p1.2", "Section 5 above", "p2.h1")])  # target is below
    assert p.rule == "direction" and "above" in p.text and "below" in p.text
    (p,) = _problems([_ref("p1.1", "Section 3 below", "p1.h1")])  # target is above
    assert p.rule == "direction"
    assert _problems([_ref("p1.2", "Section 5 above", "p1.h1")]) == []
    assert _problems([_ref("p1.1", "Section 4 below", "p2.h1")]) == []


def test_f_same_identifier_with_two_names():
    d = tag_pages("c", [Page(1, "1", [
        Paragraph.of("Submit Attachment A - EBOP Form."),
        Paragraph.of("Also complete Attachment A - Workforce Diversity Questionnaire."),
        Paragraph.of("Attachment B - EBOP Form is also due."),
    ])])
    refs = [
        xref.Ref("p1.1", "Attachment A - EBOP Form", None, "attachment"),
        xref.Ref("p1.2", "Attachment A - Workforce Diversity Questionnaire", None, "attachment"),
        xref.Ref("p1.3", "Attachment B - EBOP Form", None, "attachment"),
    ]
    res = xref.verify(d, refs)
    # A has two names (p1.1, p1.2); the EBOP Form has two identifiers (p1.1, p1.3).
    assert sorted((p.rule, p.ids) for p in res.problems) == [("naming", ("p1.1", "p1.2")), ("naming", ("p1.1", "p1.3"))]


def d_paragraphs(d):
    return [Paragraph.of(a.text) for a in list(d.anchors.values())]


def test_f_one_problem_lists_every_place_and_no_problem_when_names_agree():
    d = tag_pages("c", [Page(1, "1", [
        Paragraph.of("Complete Attachment A - EBOP Form."),
        Paragraph.of("The EBOP Form (Attachment A) is attached."),
        Paragraph.of("Attachment A, the Workforce Questionnaire, is due."),
        Paragraph.of("Attachment A: Workforce Questionnaire Template."),
    ])])
    agree = tag_pages("c", [Page(1, "1", d_paragraphs(d)[:2])])
    ok = xref.verify(agree, [
        xref.Ref("p1.1", "Attachment A - EBOP Form", None, "attachment"),
        xref.Ref("p1.2", "The EBOP Form (Attachment A)", None, "attachment"),
    ])
    assert ok.problems == [] and ok.verified == 2
    bad = xref.verify(d, [
        xref.Ref("p1.1", "Attachment A - EBOP Form", None, "attachment"),
        xref.Ref("p1.2", "The EBOP Form (Attachment A)", None, "attachment"),
        xref.Ref("p1.3", "Attachment A, the Workforce Questionnaire", None, "attachment"),
        xref.Ref("p1.4", "Attachment A: Workforce Questionnaire Template", None, "attachment"),
    ])
    (p,) = bad.problems
    assert p.rule == "naming" and p.ids == ("p1.1", "p1.2", "p1.3", "p1.4")
    assert p.text == "Attachment A is used for two different things: the EBOP Form (p.1) and the Workforce Questionnaire (p.1)."


def test_f_same_name_two_identifiers():
    d = tag_pages("c", [Page(1, "1", [
        Paragraph.of("Return Attachment A - Pricing Sheet."),
        Paragraph.of("Return Attachment B - Pricing Sheet."),
        Paragraph.of("Return Attachment C - Insurance Certificate."),
    ])])
    res = xref.verify(d, [
        xref.Ref("p1.1", "Attachment A - Pricing Sheet", None, "attachment"),
        xref.Ref("p1.2", "Attachment B - Pricing Sheet", None, "attachment"),
        xref.Ref("p1.3", "Attachment C - Insurance Certificate", None, "attachment"),
    ])
    (p,) = res.problems
    assert p.rule == "naming" and p.ids == ("p1.1", "p1.2")
    assert p.text == "The Pricing Sheet is called Attachment A (p.1) but Attachment B (p.1)."


# --- external, dedupe, one problem per unit pair ------------------------------------------


def test_external_references_are_never_errors():
    refs = [
        _ref("p2.6", "Article 15 of the Executive Law", None, "external"),
        _ref("p2.6", "Article 15 of the Executive Law", "p7.7", "external"),  # even with a bad target
        _ref("p2.2", "Refer to", None, "external"),
    ]
    res = xref.verify(_doc(), refs)
    assert res.problems == [] and res.external == 2 and res.checked == 0


def test_the_same_reference_twice_is_one_problem():
    r = _ref("p1.1", "Section 3 below", "p1.h3")
    res = xref.verify(_doc(), [r, r, _ref("p1.1", "section 3  BELOW", "p1.h3")])
    assert len(res.problems) == 1 and res.checked == 1
    # Two rules on the same two units give one Q fact, not two.
    res = xref.verify(_doc(), [_ref("p1.1", "Section 3 below", "p1.h3"), _ref("p1.1", "Section 3", "p1.h3")])
    assert len(res.problems) == 1


def test_counts():
    res = xref.verify(_doc(), [
        _ref("p1.1", "Section 3 below", "p1.h3"),         # problem
        _ref("p1.4", "Section 2", "p1.h2"),               # fine
        _ref("p2.6", "Article 15 of the Executive Law", None, "external"),
        _ref("p9.9", "x", None),                          # dropped
    ])
    assert (res.found, res.dropped, res.external, res.checked, res.verified, len(res.problems)) == (4, 1, 1, 2, 1, 1)


def test_analyse_failure_and_garbage():
    d = _doc()
    assert xref.analyse(d, "").status == "failed"
    assert xref.analyse(d, "sorry, no").status == "unparseable"
    ok = xref.analyse(d, "REF|p1.1|Section 3 below|p1.h3|section\nREF|p1|bad\nEND|1\n")
    assert ok.status == "ok" and ok.malformed == 1 and ok.declared == 1 and len(ok.problems) == 1
    assert xref.analyse(d, "END|0").status == "ok"


def test_prompt_has_no_document_specific_examples():
    low = xref.TASK.lower()
    for word in ("durham", "ulster", "oracle", "ebop", "actuarial"):
        assert word not in low


# --- pipeline -----------------------------------------------------------------------------

XREF_LINES = (
    "REF|p1.1|Section 3 below|p1.h3|section\n"
    "REF|p1.4|Section 2 (Publicity)|p1.h2|section\n"
    "REF|p2.2|Refer to|none|section\n"
    "REF|p2.6|Article 15 of the Executive Law|none|external\n"
    "REF|p9.9|Section 1|p1.h1|section\n"
    "END|5\n"
)
FAST = units.Config(backoff_base=0, warmup_timeout=1, votes=1, statements=False, check=False, grouping=False, brief=False)


async def test_xref_facts_reach_the_result():
    client = scripted(labels={}, xref=XREF_LINES)
    res = await units.extract(_doc(), client, deal_id="d", cfg=units.Config(backoff_base=0, warmup_timeout=1, votes=1))
    q = [f for f in res.facts if f["category"] == "Q" and f["source_call"] == "XREF"]
    assert len(q) == 3 and all(f["status"] == "valid" for f in q)
    blank = next(f for f in q if "blank" in f["text"] and "INTENTIONALLY" in f["text"])
    assert [c["id"] for c in blank["citations"]] == ["p1.1", "p1.h3"]
    r = res.report["xref"]
    assert (r["status"], r["found"], r["dropped"], r["external"], r["checked"], r["verified"], r["problems"]) == ("ok", 5, 1, 1, 3, 0, 3)
    assert res.report["xref_conflicts"] == 3
    call = next(c for c in res.report["calls"] if c["name"] == "XREF")
    assert call["kind"] == "xref" and call["status"] == "ok"
    sent = [q for q in client.requests if task_name(q) == "XREF"]
    assert len(sent) == 1 and sent[0].system == units.SYSTEM and sent[0].document == _doc().tagged_text


@pytest.mark.parametrize("answer", ["fail", "garbage"])
async def test_a_bad_xref_call_leaves_the_run_intact(answer):
    from fact_extractor.llm import CallFailed

    base = scripted(labels={"p2.1": "S"}, xref="x")

    def handler(req):
        if task_name(req) == "XREF":
            return CallFailed("boom") if answer == "fail" else "I found some references but will not list them."
        return base.handler(req)

    from conftest import ScriptedClient

    res = await units.extract(_doc(), ScriptedClient(handler), deal_id="d", cfg=units.Config(backoff_base=0, warmup_timeout=1, votes=1))
    assert [f for f in res.facts if f["source_call"] == "XREF"] == []
    assert any(f["category"] == "S" for f in res.facts)  # the rest of the run is there
    assert res.report["xref"]["status"] == ("failed" if answer == "fail" else "unparseable")
    assert res.report["xref"]["problems"] == 0 and res.report["xref_conflicts"] == 0
    if answer == "fail":
        assert "XREF" in res.report["failed_calls"]


async def test_no_xref_skips_the_call():
    from dataclasses import replace

    client = scripted(labels={}, xref=XREF_LINES)
    res = await units.extract(_doc(), client, deal_id="d", cfg=replace(FAST, xref=False))
    assert not [q for q in client.requests if task_name(q) == "XREF"]
    assert res.report["xref"]["status"] == "off" and not [c for c in res.report["calls"] if c["name"] == "XREF"]


async def test_xref_and_check_on_the_same_units_make_one_fact():
    client = scripted(labels={}, xref="REF|p1.1|Section 3 below|p1.h3|section\nEND|1\n", check="Q|Section 3 is blank|p1.1,p1.h3|\nEND|1\n")
    res = await units.extract(_doc(), client, deal_id="d", cfg=units.Config(backoff_base=0, warmup_timeout=1, votes=1))
    (q,) = [f for f in res.facts if f["category"] == "Q"]
    assert q["source_call"] == "CHECK,XREF"


# --- rule f reads the names from the units, not from the copied reference text ------------------


def test_parse_name_field_and_old_format_together():
    p = xref.parse(
        "REF|p1.1|Attachment A|none|attachment|Pricing Sheet\n"
        "REF|p1.2|Attachment B|none|attachment|\n"
        "REF|p1.3|Section 4|p1.h4|section\n"
        "REF|p1.4|a | b|none|attachment|Odd Name\n"
        "REF|p1.5|a | b|none|attachment\n"
    )
    assert [(r.text, r.kind, r.name) for r in p.refs] == [
        ("Attachment A", "attachment", "Pricing Sheet"), ("Attachment B", "attachment", ""),
        ("Section 4", "section", ""), ("a|b", "attachment", "Odd Name"), ("a|b", "attachment", ""),
    ]
    assert p.malformed == 0


def test_identifier_names_before_after_and_list():
    got = {k: n for k, n, _ in xref.identifier_names(
        "Return Attachment A - Pricing Sheet. Staff Roster Form: completed Attachment B. "
        "The form is included in Attachment C. Attachments D, E and F are listed."
    )}
    assert got[("attachment", "A")] == "Pricing Sheet"
    assert got[("attachment", "B")].startswith("Staff Roster Form")
    assert ("attachment", "C") not in got  # only generic words beside it
    assert ("attachment", "D") not in got and ("attachment", "E") not in got  # a list has no one name


def test_abbreviation_matches_its_long_form():
    assert xref.name_overlap(["ebop"], ["equal", "business", "opportunity", "program", "procurement"]) == 1.0
    assert xref.name_overlap(["ebop"], ["workforce", "diversity"]) == 0.0
    assert xref.name_overlap(["pricing", "sheet"], ["pricing", "narrative"]) == 0.5


def test_f_names_are_read_from_the_unit_when_the_reference_text_is_bare():
    """The model copies only "Attachment A"; the name is in the unit, before or after the identifier,
    and one list entry that names the attachment was not listed by the model at all."""
    d = tag_pages("c", [Page(1, "1", [
        Heading("5. Submission"),
        Paragraph.of("Return the statement in Attachment A - EBOP Instruction and Fillable Form, which lists what to fill in."),
        Paragraph.of("The form is included in attachment A."),
        Paragraph.of("Submit these items:"),
        Paragraph.of("4. completed RFP 12 Attachment A - EBOP Instruction and Fillable Form"),
        Paragraph.of("9. Workforce Diversity form: completed Attachment A"),
        Paragraph.of("10. Equal Business Opportunity Program Procurement Forms: completed Attachment B"),
    ])])
    reply = (
        "REF|p1.1|Attachment A|none|attachment\n"
        "REF|p1.2|attachment A|p1.1|attachment\n"
        "REF|p1.5|Attachment A|p1.1|attachment\n"
        "REF|p1.6|Attachment B|none|attachment\n"
        "END|4\n"
    )
    res = xref.analyse(d, reply)
    rules = sorted((p.rule, p.ids) for p in res.problems)
    assert rules == [("naming", ("p1.1", "p1.4", "p1.5")), ("naming", ("p1.1", "p1.4", "p1.6"))]
    assert any("different things" in p.text for p in res.problems)
    assert any(" is called Attachment A " in p.text and " but Attachment B " in p.text for p in res.problems)


def test_f_no_problem_when_unit_names_agree_and_a_model_name_is_used():
    d = tag_pages("c", [Page(1, "1", [
        Paragraph.of("Return Attachment A - Pricing Sheet."),
        Paragraph.of("Attachment A: completed."),
        Paragraph.of("Complete the Pricing Sheet (Attachment A) in full."),
    ])])
    assert xref.analyse(d, "REF|p1.2|Attachment A|none|attachment|Pricing Sheet\nEND|1\n").problems == []
    # a name the model gives for a bare reference counts as that unit's name
    bad = xref.analyse(d, "REF|p1.2|Attachment A|none|attachment|Insurance Certificate\nEND|1\n")
    assert [p.rule for p in bad.problems] == ["naming"]


# --- problem texts: short, plain, with page labels --------------------------------------------


def _paged():
    return tag_pages("c", [
        Page(8, "8", [Heading("5. Payment Terms"), Paragraph.of("Dates are listed here.")]),
        Page(11, "11", [Paragraph.of("Attachment A is the Pricing Sheet. Attachment B is the Pricing Sheet."), Paragraph.of("Attachment A is the Insurance Form.")]),
        Page(17, "17", [
            Paragraph.of("Refer to"),
            Paragraph.of("See the schedule below for dates."),
            Paragraph.of("Follow Section 9 of the full and very long description of everything the bidder must do before award."),
            Paragraph.of("See Section 2 (Publicity) for the rules."),
        ]),
    ])


def test_text_blank_reference():
    (p,) = _problems([_ref("p17.1", "Refer to", None, "attachment")], _paged())
    assert p.text == 'A reference is left blank: "Refer to" on p.17 names nothing.'


def test_text_missing_absent_blank_title_direction():
    d = _paged()
    (p,) = _problems([_ref("p17.3", "Section 9", "p99.1")], d)
    assert p.text == 'p.17 refers to "Section 9", but the document has no such part.'
    (p,) = _problems([_ref("p17.3", "Section 9 of the full and very long description of everything the bidder must do", None)], d)
    assert p.text == 'p.17 refers to "Section 9 of the full and very long ...", which is not in the document.'
    (p,) = _problems([_ref("p17.4", "Section 2 (Publicity)", "p8.h1")], d)
    assert p.text == 'p.17 refers to "Section 2 (Publicity)", but the part it points to (p.8) is titled "5. Payment Terms".'
    (p,) = _problems([_ref("p17.2", "the schedule below", "p8.h1")], d)
    assert p.text == 'p.17 says "the schedule" is below, but it is on p.8 (above).'


def test_text_blank_target_names_the_page():
    d = tag_pages("c", [Page(3, "iii", [Paragraph.of("See Section 3."), Heading("3. Reserved")]),])
    (p,) = _problems([_ref("p3.1", "Section 3", "p3.h1")], d)
    assert p.text == 'p.iii refers to "Section 3", but that part (p.iii) is blank: it reads "3. Reserved".'


def test_text_naming_two_texts():
    d = _paged()
    res = xref.verify(d, [
        xref.Ref("p11.1", "Attachment A is the Pricing Sheet", None, "attachment", "completed Pricing Sheet (fillable)"),
        xref.Ref("p11.3", "Attachment A is the Insurance Form", None, "attachment", "Insurance Form"),
    ])
    (p,) = res.problems
    assert p.text == "Attachment A is used for two different things: the Pricing Sheet (p.11) and the Insurance Form (p.11)."
    assert "Attachment A" in p.terms and "Pricing Sheet" in p.terms


def test_short_name():
    assert xref.short_name("completed Pricing Sheet (fillable)") == "Pricing Sheet"
    assert xref.short_name("EBOP Instruction and Fillable Form") == "EBOP Form"
    assert xref.short_name("RFP #24-0031 Attachment A - Proponent Response Template") == "Proponent Response Template"
    assert xref.short_name("EBOP professional Services for Equal Business Opportunity Program (EBOP)") == "EBOP professional Services"
    assert len(xref.short_name("one two three four five six seven eight nine").split()) <= 6


# --- merging a problem into a CHECK fact -------------------------------------------------------


def _p(ids, terms=()):
    return xref.Problem("naming", "x", tuple(ids), tuple(terms))


def test_merge_when_the_smaller_set_shares_half():
    assert xref.merge_score(["a", "b"], "text", _p(["a", "b", "c"])) is not None  # all of the smaller
    assert xref.merge_score(["a", "b"], "text", _p(["a", "x", "y"])) is not None  # half of the smaller
    assert xref.merge_score(["a", "b", "c"], "text", _p(["a"])) is not None  # a single unit inside


def test_no_merge_when_unrelated():
    assert xref.merge_score(["a", "b"], "text", _p(["c", "d"])) is None
    assert xref.merge_score(["a", "b", "c", "d"], "Attachment A", _p(["a", "x", "y"], [])) is None  # a quarter, no term
    assert xref.merge_score(["a", "b", "c", "d"], "text", _p(["a", "x", "y"], ["Attachment A"])) is None  # term not in the text
    assert xref.merge_score(["a"], "Attachment A", _p(["x"], ["Attachment A"])) is None  # term but no shared unit


def test_merge_on_one_shared_unit_when_the_check_names_the_subject():
    p = _p(["a", "x", "y", "z"], ["Attachment A"])
    assert xref.merge_score(["a", "b", "c", "d"], "Attachment A is the form vs the sheet", p) is not None


def test_best_match_wins():
    checks = [(["a", "b"], "one"), (["a", "b"], "Attachment A and Attachment B")]
    p = _p(["a", "b", "c"], ["Attachment A", "Attachment B"])
    assert xref.match_problems(checks, [p]) == {0: 1}  # the CHECK that mentions both identifiers
    checks = [(["a", "x", "y"], "t"), (["a", "b", "c"], "t")]
    assert xref.match_problems(checks, [_p(["a", "b"])]) == {0: 1}  # more of the smaller set shared


def test_each_problem_merges_into_at_most_one_check():
    checks = [(["a", "b"], "t"), (["a", "b"], "t")]
    assert xref.match_problems(checks, [_p(["a", "b"])]) == {0: 0}


def _q(ids, text="t"):
    return {"text": text, "ids": ids, "problems": [], "source_call": "CHECK"}


def test_q_records_merge_union_in_document_order_and_keep_check_wording():
    d = _paged()
    ids = ["p11.1", "p11.2"]
    res = xref.Result(status="ok", problems=[
        xref.Problem("naming", "xref words", ("p8.h1", "p11.2"), ("Attachment A",)),
        xref.Problem("placeholder", "blank words", ("p17.1",), ("Refer to",)),
    ])
    out = units._q_records([_q(ids, "check words")], res, d, "deal", "run")
    assert [(r["text"], r["source_call"], [c["id"] for c in r["citations"]]) for r in out] == [
        ("check words", "CHECK,XREF", ["p8.h1", "p11.1", "p11.2"]),
        ("blank words", "XREF", ["p17.1"]),
    ]


def test_q_records_one_check_absorbs_several_problems():
    d = _paged()
    res = xref.Result(status="ok", problems=[
        xref.Problem("naming", "a", ("p11.1", "p11.2")), xref.Problem("title", "b", ("p11.1", "p17.1")),
    ])
    out = units._q_records([_q(["p11.1", "p11.2"])], res, d, "deal", "run")
    assert len(out) == 1 and out[0]["source_call"] == "CHECK,XREF"
    assert [c["id"] for c in out[0]["citations"]] == ["p11.1", "p11.2", "p17.1"]

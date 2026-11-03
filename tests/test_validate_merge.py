from fact_extractor.merge import dedupe
from fact_extractor.models import CallSpec, Fact
from fact_extractor.validate import LineBuffer, check_output

SPEC = CallSpec("C", ("D", "S", "Q"), "TASK C")


def test_line_buffer_streams_lines():
    b = LineBuffer()
    assert b.feed("D|a|p1") == []
    assert b.feed(".3|\nD|b|p1.4|\n\nEN") == ["D|a|p1.3|", "D|b|p1.4|"]
    assert b.close() == ["EN"]


def test_checks(doc):
    out = check_output(
        [
            "D|Proposals due 2027-03-03 17:00 ET|p1.3|",
            "D|Pre-bid meeting 2027-02-11|p1.4|",
            "D|Thing|p9.1|",
            "D|a|b|c|d|e",
            "R|500 concurrent users|p2.1|",
            "Q|Due date differs|p1.3,p3.2",
            "END|6",
        ],
        SPEC, doc,
    )
    ok = [c.ok for c in out.checked]
    assert ok == [True, False, False, False, True, True]
    assert "2027-02-11" in out.checked[1].reasons[0]
    assert "p9.1" in out.checked[2].reasons[0]
    assert out.checked[4].log  # wrong code for the call is kept and logged
    assert out.end_count == 6


def test_missing_end_means_cut(doc):
    assert check_output(["D|Proposals due 2027-03-03|p1.3|"], SPEC, doc).end_count is None


def F(code, text, ids, status="valid"):
    return Fact(code, text, ids, "", status, "R1")


def test_dedupe_keeps_split_requirements_from_one_sentence():
    facts = [
        F("R", "Vendor must provide 24/7 phone support", ["p2.2"]),
        F("R", "Vendor must provide an online ticket portal", ["p2.2"]),
        F("R", "Vendor must provide 24/7 phone support.", ["p2.2"]),
    ]
    out = dedupe(facts)
    assert [f.text for f in out] == ["Vendor must provide 24/7 phone support.", "Vendor must provide an online ticket portal"]


def test_dedupe_merges_overlapping_ids_and_prefers_valid():
    facts = [
        F("R", "Vendor must provide 24/7 support", ["p2.2", "p2.t1r1"], "needs_review"),
        F("R", "Vendor must provide 24/7 support", ["p2.2"]),
        F("D", "Vendor must provide 24/7 support", ["p2.2"]),
    ]
    out = dedupe(facts)
    assert len(out) == 2
    assert out[0].status == "valid" and out[0].ids == ["p2.2", "p2.t1r1"]


def test_parse_fixes_end_with_code_and_pipe_in_fact(doc):
    from fact_extractor.validate import parse_line

    out = check_output(["D|Proposals due|2027-03-03 17:00 ET|p1.3|", "S|END|1"], SPEC, doc)
    assert out.end_count == 1
    assert out.checked[0].ok and out.checked[0].line.fact == "Proposals due: 2027-03-03 17:00 ET"
    assert parse_line("R|a|p1.2,p1.3|unclear").ids == ["p1.2", "p1.3"]


def test_note_flags_split_and_merge():
    from fact_extractor.store import split_note

    assert split_note("mandatory, unclear") == (["mandatory", "unclear"], "")
    assert split_note("Risk, see sample contract") == (["risk"], "see sample contract")
    a = Fact("C", "Unlimited liability for the vendor", ["p2.2"], "risk", "valid", "A")
    b = Fact("C", "Unlimited liability for the vendor.", ["p2.2"], "unclear", "valid", "SWEEP1")
    (m,) = dedupe([a, b])
    assert split_note(m.note)[0] == ["unclear", "risk"] or split_note(m.note)[0] == ["risk", "unclear"]


def test_flags_in_ids_field_move_to_note(doc):
    from fact_extractor.validate import parse_line

    line = parse_line("C|Vendor must provide 24/7 support|p2.2,risk|")
    assert line.ids == ["p2.2"] and line.note == "risk"
    assert check_output(["C|Vendor must provide 24/7 support|p2.2,Mandatory|unclear", "END|1"], SPEC, doc).checked[0].ok


def test_compare_matches_across_codes():
    from fact_extractor.compare import Item, compare

    gold = [
        Item("D", "Proposals due: 2027-03-03 17:00", ["p1.3"], []),
        Item("G", "Firm licensed in NY for 4 years", ["p5.1"], ["mandatory"]),
        Item("R", "Provide hourly rates", ["p6.2"], ["mandatory"]),
    ]
    found = [
        Item("D", "Proposal deadline 2027-03-03 at 17:00", ["p1.3", "p8.1"], []),
        Item("R", "Firm must be licensed in NY for at least 4 years", ["p5.1"], ["mandatory"]),
        Item("S", "Use the forms in order", ["p6.2"], []),
    ]
    cmp = compare(gold, found)
    assert [bool(m.found) for m in cmp.matches] == [True, True, False]
    assert cmp.by_category["G"]["found_under_other_code"] == 1
    assert cmp.by_category["D"]["recall_same_code"] == 1.0


def test_q_lines_on_same_ids_merge():
    facts = [
        F("Q", "Subcontract provisions required but subcontracting prohibited", ["p20.4", "p20.13"]),
        F("Q", "The sample agreement both regulates and bans subcontracting", ["p20.13", "p20.4"]),
        F("Q", "Insurance due dates differ", ["p12.4", "p44.1"]),
    ]
    assert len(dedupe(facts)) == 2

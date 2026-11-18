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
        F("D", "Support desk opens 2027-03-03", ["p2.2"]),
    ]
    out = dedupe(facts)
    assert len(out) == 2
    assert out[0].status == "valid" and out[0].ids == ["p2.2", "p2.t1r1"]


def test_dedupe_merges_one_statement_filed_under_two_codes():
    # Two calls restate one sentence under two codes: one fact, under the code that comes
    # first in prompts.PRECEDENCE, with the flags of both.
    r = Fact("R", "Submit the proposal unbound and unstapled", ["p3.1"], "mandatory", "valid", "R1")
    s = Fact("S", "Submit proposal unbound and unstapled.", ["p3.1", "p3.2"], "", "valid", "C")
    (m,) = dedupe([r, s])
    assert m.category == "S" and m.note == "mandatory" and m.source_call == "C,R1"
    # A second view of the sentence is kept: the due date (D) next to the rejection rule (X).
    d = F("D", "Proposals due: 2027-03-05", ["p3.2"])
    x = F("X", "Proposals received after 2027-03-05 will not be opened", ["p3.2"])
    assert len(dedupe([d, x])) == 2
    # So is a fact with a number the other lacks, and a Q line citing the same sentence.
    c = F("C", "Proposals shall not exceed 50 pages", ["p3.1"])
    assert len(dedupe([F("S", "Proposals shall not exceed the page limit", ["p3.1"]), c])) == 2
    assert len(dedupe([c, F("Q", "Proposals shall not exceed 50 pages", ["p3.1"])])) == 2


def test_fact_ids_ignore_wording():
    from fact_extractor.store import fact_ids

    a = [F("R", "Provide 24/7 phone support", ["p2.2", "p2.t1r1"]), F("R", "Provide a ticket portal", ["p2.2"]),
         F("Q", "Due dates differ", ["p1.3", "p3.2"]), F("R", "No source given", [], "needs_review")]
    b = [F("R", "Vendor must staff a 24/7 phone line", ["p2.2"]), F("R", "Offer an online portal for tickets", ["p2.2"]),
         F("Q", "March 3 vs March 5", ["p3.2", "p1.3"]), F("S", "Provide 24/7 phone support", ["p2.2"])]
    ia, ib = fact_ids("d", a), fact_ids("d", b)
    assert ia[:3] == ib[:3]  # same code and main ID, in the same order; Q by its sorted IDs
    assert len(set(ia)) == 4 and ib[3] not in ia  # another code is another fact
    assert fact_ids("other", a)[0] != ia[0]


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


def test_compare_uses_each_extracted_fact_once():
    from fact_extractor.compare import Item, compare

    gold = [
        Item("R", "Mark the envelope with the company name and address", ["p3.7"], []),
        Item("R", "Mark the envelope with the RFP name, number and closing date", ["p3.8"], []),
    ]
    # one broad fact citing both passages, but stating only the first in full
    found = [Item("R", "Mark the envelope with the company name and address and RFP details", ["p3.7", "p3.8"], [])]
    cmp = compare(gold, found)
    assert sum(1 for m in cmp.matches if m.found) == 1
    assert len(cmp.merged) == 1
    assert cmp.by_category["R"]["missed_merged"] == 1
    assert cmp.extras == []


def test_compare_credits_gold_stated_inside_a_combined_fact():
    from fact_extractor.compare import Item, compare

    gold = [
        Item("R", "Mark the envelope with the company name and address", ["p3.7"], []),
        Item("R", "Mark the envelope with the RFP name and number", ["p3.8"], []),
    ]
    found = [Item("R", "Mark the envelope with the company name, address, RFP name and number", ["p3.7", "p3.8"], [])]
    cmp = compare(gold, found)
    assert all(m.found is found[0] for m in cmp.matches)
    assert [m.combined for m in cmp.matches].count(True) == 1
    assert cmp.merged == []
    assert cmp.by_category["R"]["combined"] == 1
    assert cmp.by_category["R"]["recall_same_code"] == 1.0


def test_combined_credit_needs_matching_values():
    from fact_extractor.compare import Item, compare

    gold = [
        Item("E", "Ulster County vendors receive five points", ["p36.1"], []),
        Item("E", "Contiguous county vendors receive three points", ["p36.1"], []),
    ]
    # the second tier is stated with the wrong value
    found = [Item("E", "Ulster County vendors receive five points; contiguous county vendors receive two points", ["p36.1"], [])]
    cmp = compare(gold, found)
    assert cmp.matches[1].found is None
    assert len(cmp.merged) == 1


def test_gold_alternate_codes_count_as_same_code(tmp_path):
    from fact_extractor.compare import Item, compare, confusion, read_lines

    p = tmp_path / "gold.txt"
    p.write_text("G/C/R|Bidder must not be on the Iran Prohibited Entities List|p42.1|mandatory\n")
    gold = read_lines(str(p))
    assert gold[0].category == "G" and gold[0].alt == ["C", "R"]
    found = [Item("R", "Certify the bidder is not on the Iran Prohibited Entities List", ["p42.1"], [])]
    cmp = compare(gold, found)
    assert cmp.by_category["G"]["recall_same_code"] == 1.0
    assert cmp.by_category["G"]["found_under_other_code"] == 0
    assert not confusion(cmp)


def test_compare_best_pairs_win_regardless_of_gold_order():
    from fact_extractor.compare import Item, compare

    gold = [
        Item("R", "Submit the proposal in a sealed envelope", ["p3.6"], []),
        Item("R", "Submit the proposal sealed in an opaque envelope or package", ["p3.6"], []),
    ]
    found = [
        Item("R", "Submit the proposal sealed in an opaque envelope or package", ["p3.6"], []),
        Item("R", "Proposal must arrive in a sealed envelope", ["p3.6"], []),
    ]
    cmp = compare(gold, found)
    # the exact restatement goes to the second gold fact, not to whichever came first
    assert cmp.matches[1].found is found[0]
    assert cmp.matches[0].found is found[1]


def test_compare_short_vague_fact_does_not_match_specific_gold():
    from fact_extractor.compare import Item, compare

    gold = [Item("D", "Proposals due 4:00 P.M. Friday, August 28, 2026", ["p6.16"], [])]
    found = [Item("D", "Proposals due by email", ["p6.16"], [])]
    assert compare(gold, found).matches[0].found is None


def test_compare_category_bonus_does_not_rescue_weak_text():
    from fact_extractor.compare import Item, compare

    gold = [Item("R", "Provide a table of contents by section and page", ["p9.1"], [])]
    found = [Item("R", "Use twelve point font throughout", ["p9.1"], [])]
    assert compare(gold, found).matches[0].found is None


def test_value_check_flags_wrong_deadline():
    from fact_extractor.compare import Item, compare

    gold = [Item("D", "Proposals due 4:00 P.M. Friday, August 28, 2026", ["p6.16"], [])]
    found = [Item("D", "Proposals due 2:00 P.M. Monday, August 31, 2026", ["p6.16"], [])]
    cmp = compare(gold, found)
    m = cmp.matches[0]
    assert m.found is not None  # still matched on wording
    assert m.values.verdict == "wrong"
    assert set(m.values.missing) == {"date:2026-08-28", "time:16:00"}
    assert cmp.by_category["D"]["values_wrong"] == 1
    assert cmp.by_category["D"]["recall_values_ok"] == 0.0


def test_value_check_accepts_other_formats():
    from fact_extractor.compare import check_values

    assert check_values("Proposals due 4:00 P.M. on August 28, 2026", "Due 2026-08-28 at 16:00").verdict == "ok"
    assert check_values("Contract term is three years", "Contract term: 3 years").verdict == "ok"
    assert check_values("Retain records for six (6) years", "Keep records six years").verdict == "ok"
    assert check_values("Umbrella minimum $2,000,000", "Umbrella minimum $2 million").verdict == "ok"
    assert check_values("Firm must hold a NY license", "Firm licensed in NY") is None


def test_value_check_wrong_vs_incomplete():
    from fact_extractor.compare import check_values

    assert check_values("Respond within five working days", "Respond within 10 working days").verdict == "wrong"
    v = check_values("Umbrella minimum $2,000,000, follow-form", "Umbrella must be follow-form")
    assert v.verdict == "incomplete" and v.missing == ["2000000"]


def test_q_lines_on_same_ids_merge():
    facts = [
        F("Q", "Subcontract provisions required but subcontracting prohibited", ["p20.4", "p20.13"]),
        F("Q", "The sample agreement both regulates and bans subcontracting", ["p20.13", "p20.4"]),
        F("Q", "Insurance due dates differ", ["p12.4", "p44.1"]),
    ]
    assert len(dedupe(facts)) == 2


def test_post_award_flag_is_kept(doc):
    from fact_extractor.store import split_note

    out = check_output(["C|Vendor must provide 24/7 support|p2.2|mandatory, post-award", "END|1"], SPEC, doc)
    assert out.checked[0].ok and split_note(out.checked[0].line.note) == (["mandatory", "post-award"], "")

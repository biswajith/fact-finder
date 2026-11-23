"""The priority ladder (ladder.py): what a relation may do to a fact. Pure, no model."""

import copy

from fact_extractor import bid as B
from fact_extractor import ladder as L


def doc(doc_id, playbook="rfp", date=None, number=None, no=1):
    return {"no": no, "doc_id": doc_id, "playbook": playbook, "issue_date": date, "issue_number": number}


def fact(doc_id, unit, text, level=1, cat="D", also=()):
    return {
        "fact_id": f"f_{doc_id}_{unit}", "doc_id": doc_id, "category": cat, "text": text, "source_text": text,
        "level": level, "flags": [], "relations": [], "replaced_by": "", "stale": "",
        "citations": [{"id": u, "doc_id": doc_id} for u in (unit, *also)],
    }


def units(*rows):
    return [{"id": i, "kind": k, "side": "", "text": ""} for i, k in rows]


def row(unit, kind, *targets):
    return {"unit": unit, "kind": kind, "targets": [{"doc_id": d, "unit": u} for d, u in targets]}


def run(docs, facts, rels, **kw):
    return L.apply(docs, facts, {d: {"units": r} for d, r in rels.items()}, **kw)


def by_id(applied):
    return {f["fact_id"]: f for f in applied.facts}


RFP = doc("RFP", date="2026-07-01")
ADD1 = doc("ADD1", "change-addendum", "2026-08-01", 1, no=2)


def test_outcome_follows_the_ladder():
    assert L.outcome(1, 1, True) == "replace"
    assert L.outcome(1, 1, False) == "keep-old"
    assert L.outcome(1, 1, True, precedence_says_old=True) == "keep-old"
    assert L.outcome(1, 1, False, precedence_says_old=False) == "replace"
    assert L.outcome(1, 1, True, together=True) == "q-fact"
    assert L.outcome(2, 1, True) == L.outcome(3, 1, True) == L.outcome(4, 2, True) == "conflict"
    assert L.outcome(1, 2, True) == "replace" and L.outcome(1, 4, False) == "keep-old"


def test_a_changed_due_date_replaces_the_base_fact_and_is_recorded_on_both_ends():
    old, new = fact("RFP", "p1.1", "Proposals are due June 10, 2:00 pm."), fact("ADD1", "p1.4", "Proposals are due June 24, 2:00 pm.")
    other = fact("RFP", "p2.1", "Questions are due May 20.")
    got = run([RFP, ADD1], {"RFP": [old, other], "ADD1": [new]}, {"ADD1": [row("p1.4", "REPLACES", ("RFP", "p1.1"))]})
    facts = by_id(got)
    o, n = facts[old["fact_id"]], facts[new["fact_id"]]
    assert o["flags"] == ["replaced"] and o["replaced_by"] == new["fact_id"] and o["text"] == old["text"]
    assert n["flags"] == [] and n["replaced_by"] == "" and facts[other["fact_id"]]["flags"] == []
    [r] = o["relations"]
    assert r == n["relations"][0] and r["kind"] == "REPLACES" and r["rejected"] is False
    assert r["from"] == {"doc_id": "ADD1", "unit": "p1.4", "fact_id": new["fact_id"]}
    assert r["to"] == {"doc_id": "RFP", "unit": "p1.1", "fact_id": old["fact_id"]}
    assert r["id"] == L.relation_id("ADD1", "p1.4", "REPLACES", "RFP", "p1.1") and r["id"].startswith("r_") and len(r["id"]) == 12
    assert got.conflicts == [] and old["flags"] == []  # the input is not changed


def test_a_section_replaced_by_its_heading_replaces_every_fact_in_it():
    rfp_units = units(("p3.1", "heading"), ("p3.2", "sentence"), ("p3.3", "sentence"), ("p3.4", "sentence"), ("p4.1", "heading"), ("p4.2", "sentence"))
    a, b, c = fact("RFP", "p3.2", "Limit 30 pages", cat="S"), fact("RFP", "p3.3", "Font 11 point", cat="S"), fact("RFP", "p4.2", "Insurance of 1 million")
    new = fact("ADD1", "p2.2", "Limit 40 pages", cat="S")
    got = run(
        [RFP, ADD1], {"RFP": [a, b, c], "ADD1": [new]}, {"ADD1": [row("p2.1", "REPLACES", ("RFP", "p3.1")), row("p2.2", "ADDS")]},
        units_by_doc={"RFP": rfp_units, "ADD1": units(("p2.1", "sentence"), ("p2.2", "sentence"))},
    )
    facts = by_id(got)
    assert [facts[f["fact_id"]]["flags"] for f in (a, b, c)] == [["replaced"], ["replaced"], []]
    assert facts[a["fact_id"]]["replaced_by"] == ""  # the instruction unit is no fact: nothing to point at
    assert facts[a["fact_id"]]["relations"][0]["to"]["fact_id"] == a["fact_id"] and facts[a["fact_id"]]["relations"][0]["to"]["unit"] == "p3.1"
    assert all(f["stale"] == "" for f in got.facts) and got.conflicts == []


def test_some_units_of_a_section_replaced_leave_the_rest_stale():
    rfp_units = units(("p3.1", "heading"), ("p3.2", "sentence"), ("p3.3", "sentence"), ("p4.1", "heading"), ("p4.2", "sentence"))
    a, b, c = fact("RFP", "p3.2", "Limit 30 pages", cat="S"), fact("RFP", "p3.3", "Font 11 point", cat="S"), fact("RFP", "p4.2", "Insurance")
    new = fact("ADD1", "p2.1", "Limit 40 pages", cat="S")
    got = run([RFP, ADD1], {"RFP": [a, b, c], "ADD1": [new]}, {"ADD1": [row("p2.1", "REPLACES", ("RFP", "p3.2"))]},
              units_by_doc={"RFP": rfp_units, "ADD1": units(("p2.1", "sentence"))})
    facts = by_id(got)
    assert facts[a["fact_id"]]["flags"] == ["replaced"] and facts[a["fact_id"]]["replaced_by"] == new["fact_id"]
    assert (facts[b["fact_id"]]["stale"], facts[c["fact_id"]]["stale"]) == ("section partly replaced", "")
    assert facts[a["fact_id"]]["stale"] == ""


def test_removes_marks_replaced_with_nothing_in_its_place():
    old, instr = fact("RFP", "p1.1", "Site visit June 3"), fact("ADD1", "p1.1", "Site visit is cancelled", cat="D")
    got = run([RFP, ADD1], {"RFP": [old], "ADD1": [instr]}, {"ADD1": [row("p1.1", "REMOVES", ("RFP", "p1.1"))]})
    o = by_id(got)[old["fact_id"]]
    assert o["flags"] == ["replaced"] and o["replaced_by"] == ""


def test_a_target_that_is_a_unit_of_no_fact_marks_nothing_but_is_kept_by_the_caller():
    old, new = fact("RFP", "p1.1", "Due June 10"), fact("ADD1", "p1.1", "Due June 24")
    got = run([RFP, ADD1], {"RFP": [old], "ADD1": [new]}, {"ADD1": [row("p1.1", "REPLACES", ("RFP", "p9.9"))]})
    assert all(f["flags"] == [] for f in got.facts)
    assert [len(f["relations"]) for f in got.facts] == [0, 1]  # the relating fact still shows what it points at
    assert got.facts[1]["relations"][0]["to"]["fact_id"] == ""


def test_confirms_clarifies_adds_and_none_mark_nothing():
    old, new = fact("RFP", "p1.1", "Due June 10"), fact("ADD1", "p1.1", "Due June 10", cat="D")
    for kind in ("CONFIRMS", "CLARIFIES", "ADDS", "NONE"):
        got = run([RFP, ADD1], {"RFP": [copy.deepcopy(old)], "ADD1": [copy.deepcopy(new)]}, {"ADD1": [row("p1.1", kind, ("RFP", "p1.1"))]})
        assert all(f["flags"] == [] and f["replaced_by"] == "" for f in got.facts)
        assert len(got.facts[0]["relations"]) == (0 if kind == "NONE" else 1)


def test_addendum_3_loaded_before_addendum_2_still_applies_after_it():
    m = {"documents": [
        {**RFP, "no": 1}, {**doc("ADD3", "change-addendum", "2026-08-05", 3, no=2)}, {**doc("ADD2", "change-addendum", "2026-08-09", 2, no=3)},
    ]}
    order = B.issue_order(m)
    assert [d["doc_id"] for d in order] == ["RFP", "ADD2", "ADD3"]  # number wins over date
    old = fact("RFP", "p1.1", "Due June 10")
    a2, a3 = fact("ADD2", "p1.1", "Due June 24"), fact("ADD3", "p1.1", "Due June 30")
    facts = {"RFP": [old], "ADD3": [a3], "ADD2": [a2]}  # the order they were loaded in
    rels = {"ADD3": [row("p1.1", "REPLACES", ("RFP", "p1.1"))], "ADD2": [row("p1.1", "REPLACES", ("RFP", "p1.1"))]}
    got = by_id(run(order, facts, rels))
    assert got[old["fact_id"]]["replaced_by"] == a3["fact_id"] and got[old["fact_id"]]["flags"] == ["replaced"]
    assert [r["from"]["doc_id"] for r in got[old["fact_id"]]["relations"]] == ["ADD2", "ADD3"]  # applied in issue order


def test_a_buyer_statement_on_a_call_disagreeing_with_the_rfp_raises_a_conflict_and_replaces_nothing():
    call = doc("CALL", "call-transcript", "2026-07-15", no=2)
    old = fact("RFP", "p1.1", "Due June 10")
    said = fact("CALL", "t1", "Buyer says the due date is June 24", level=2)
    got = run([RFP, call], {"RFP": [old], "CALL": [said]}, {"CALL": [row("t1", "DISAGREES", ("RFP", "p1.1"))]})
    assert all("replaced" not in f["flags"] for f in got.facts)
    [c] = got.conflicts
    assert c["kind"] == "document" and c["reason"] == "levels disagree" and c["status"] == "open" and c["closed_by"] == ""
    assert c["id"] == L.conflict_id([old["fact_id"], said["fact_id"]], "levels disagree") and c["id"].startswith("d:")
    assert set(c["fact_ids"]) == {old["fact_id"], said["fact_id"]}
    keep, rely, ask = c["options"]
    assert keep["changes"] == [] and ask == {"label": "Ask the buyer", "text": "", "citation": None, "changes": [], "question": True}
    [ch] = rely["changes"]
    assert (ch["op"], ch["fact_id"], ch["fields"]["flags"]) == ("edit", old["fact_id"], ["replaced"])
    assert len(got.facts[0]["relations"]) == 1  # the relation is still recorded
    # a level-3 and a level-4 source do the same
    for pb, level in (("deal-notes", 4),):
        notes = doc("N", pb, "2026-07-16", no=3)
        got = run([RFP, notes], {"RFP": [old], "N": [fact("N", "n1", "x", level=level)]}, {"N": [row("n1", "REPLACES", ("RFP", "p1.1"))]})
        assert [c["reason"] for c in got.conflicts] == ["levels disagree"] and all("replaced" not in f["flags"] for f in got.facts)


def test_a_later_buyer_document_closes_the_conflict_it_settles():
    call = doc("CALL", "call-transcript", "2026-07-15", no=2)
    add = doc("ADD1", "change-addendum", "2026-08-01", 1, no=3)
    old, said, new = fact("RFP", "p1.1", "Due June 10"), fact("CALL", "t1", "June 24", level=2), fact("ADD1", "p1.1", "Due June 24")
    rels = {"CALL": [row("t1", "DISAGREES", ("RFP", "p1.1"))], "ADD1": [row("p1.1", "REPLACES", ("RFP", "p1.1"))]}
    got = run([RFP, call, add], {"RFP": [old], "CALL": [said], "ADD1": [new]}, rels)
    [c] = got.conflicts
    assert c["closed_by"] == "ADD1" and by_id(got)[old["fact_id"]]["flags"] == ["replaced"]
    # an addendum issued before the call does not settle it
    early = doc("ADD1", "change-addendum", "2026-07-10", 1, no=3)
    got = run([RFP, early, call], {"RFP": [old], "ADD1": [new], "CALL": [said]}, rels)
    assert [c["closed_by"] for c in got.conflicts] == [""]


def test_a_rejected_relation_is_skipped_everywhere():
    old, new = fact("RFP", "p1.1", "Due June 10"), fact("ADD1", "p1.4", "Due June 24")
    rid = L.relation_id("ADD1", "p1.4", "REPLACES", "RFP", "p1.1")
    got = run([RFP, ADD1], {"RFP": [old], "ADD1": [new]}, {"ADD1": [row("p1.4", "REPLACES", ("RFP", "p1.1"))]}, rejected={rid})
    assert all(f["flags"] == [] and f["relations"] == [] for f in got.facts)


def test_a_replaced_fact_the_user_edited_is_not_replaced_silently():
    old, new = fact("RFP", "p1.1", "Due June 11 (my fix)"), fact("ADD1", "p1.4", "Due June 24")
    got = run([RFP, ADD1], {"RFP": [old], "ADD1": [new]}, {"ADD1": [row("p1.4", "REPLACES", ("RFP", "p1.1"))]}, edited={old["fact_id"]})
    assert all("replaced" not in f["flags"] for f in got.facts)
    [c] = got.conflicts
    assert c["reason"] == "user-edited fact replaced"
    mine, keep = c["options"]
    assert mine["label"].startswith("Use the new document's fact") and mine["changes"][0]["fact_id"] == old["fact_id"]
    assert keep["label"] == "Keep my edit" and keep["changes"] == []


def test_the_order_of_precedence_decides_between_level_1_documents():
    old, new = fact("RFP", "p1.1", "Due June 10"), fact("ADD1", "p1.4", "Due June 24")
    args = ([RFP, ADD1], {"RFP": [old], "ADD1": [new]}, {"ADD1": [row("p1.4", "DISAGREES", ("RFP", "p1.1"))]})
    later_wins = by_id(run(*args))
    assert later_wins[old["fact_id"]]["flags"] == ["replaced"] and later_wins[new["fact_id"]]["flags"] == []
    rfp_governs = by_id(run(*args, precedence=["RFP", "ADD1"]))
    assert rfp_governs[old["fact_id"]]["flags"] == [] and rfp_governs[new["fact_id"]]["flags"] == ["replaced"]
    assert rfp_governs[new["fact_id"]]["replaced_by"] == old["fact_id"]
    assert by_id(run(*args, precedence=["ADD1", "RFP"]))[old["fact_id"]]["flags"] == ["replaced"]


def test_two_documents_issued_together_that_disagree_are_a_conflict_not_a_replacement():
    contract = doc("CONTRACT", date="2026-07-01", no=2)
    a, b = fact("RFP", "p1.1", "Payment in 30 days"), fact("CONTRACT", "p1.1", "Payment in 45 days")
    got = run([RFP, contract], {"RFP": [a], "CONTRACT": [b]}, {"CONTRACT": [row("p1.1", "DISAGREES", ("RFP", "p1.1"))]})
    assert all("replaced" not in f["flags"] for f in got.facts)
    [c] = got.conflicts
    assert c["reason"] == "issued together" and len(c["options"]) == 3 and c["options"][2]["question"] is True


def test_a_change_with_no_target_is_not_applied_and_asks():
    new = fact("ADD1", "p1.1", "Section 9 is deleted")
    got = run([RFP, ADD1], {"RFP": [], "ADD1": [new]}, {"ADD1": [row("p1.1", "REMOVES")]})
    [c] = got.conflicts
    assert c["reason"] == "unfound target" and c["fact_ids"] == [new["fact_id"]] and c["options"][1]["question"] is True
    held = {"units": [row("p1.1", "REMOVES")], "held_refs": [{"unit": "p1.1", "text": "Section 9", "rule": "absent"}]}
    assert L.apply([RFP, ADD1], {"RFP": [], "ADD1": [new]}, {"ADD1": held}).conflicts == []  # a held reference becomes a Q fact instead


def test_apply_is_pure():
    old, new = fact("RFP", "p1.1", "Due June 10"), fact("ADD1", "p1.4", "Due June 24")
    args = ([RFP, ADD1], {"RFP": [old], "ADD1": [new]}, {"ADD1": {"units": [row("p1.4", "REPLACES", ("RFP", "p1.1"))]}})
    snapshot = copy.deepcopy(args)
    assert L.apply(*args) == L.apply(*args) and args == snapshot

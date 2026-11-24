"""bideval.py and `fact-extractor bid eval`: a bid folder made by hand, scored against a key. No model."""

import json

import pytest

import fact_extractor.cli as cli
from fact_extractor import bid as B
from fact_extractor import bideval


def fact(doc, unit, text, cat="D"):
    return {
        "fact_id": f"f_{doc}_{unit}", "category": cat, "text": text, "source_text": text, "status": "valid", "flags": [],
        "group_id": "", "group_kind": "", "group_title": "", "citations": [{"id": unit, "page": 1, "page_label": "1", "text": text}],
    }


UNITS = {
    "RFP": [("p1.h1", "heading", "1.0 Schedule"), ("p1.1", "sentence", "Proposals are due June 10, 2027."),
            ("p1.2", "sentence", "Site visit on June 3, 2027."), ("p2.h1", "heading", "2.1 Format"),
            ("p2.1", "sentence", "Limit of 30 pages."), ("p2.2", "sentence", "Use 11 point type.")],
    "ADD1": [("p1.1", "sentence", "Proposals are now due June 24, 2027."), ("p1.2", "sentence", "Section 2.1 is replaced."),
             ("p2.1", "sentence", "Use 11 point type."), ("p2.2", "sentence", "Add a cover letter.")],
    "call": [("p1.1", "sentence", "Hello."), ("p1.2", "sentence", "Hi.")],
}
FACTS = {
    "RFP": [fact("RFP", "p1.1", "Proposals are due June 10, 2027."), fact("RFP", "p1.2", "Site visit on June 3, 2027."),
            fact("RFP", "p2.1", "Limit of 30 pages.", "S"), fact("RFP", "p2.2", "Use 11 point type.", "S")],
    "ADD1": [fact("ADD1", "p1.1", "Proposals are now due June 24, 2027."), fact("ADD1", "p1.2", "Section 2.1 is replaced.", "S"),
             fact("ADD1", "p2.1", "Use 11 point type.", "S")],
    "call": [],
}


def tgt(doc, unit):
    return {"doc_id": doc, "unit": unit}


def row(unit, kind, *targets):
    return {"unit": unit, "kind": kind, "targets": [tgt(*t) for t in targets], "candidates": [], "votes": [kind]}


RELATIONS = {  # what RELATE answered for the addendum: the section one is wrong (a unit instead of the heading)
    "ADD1": {"units": [row("p1.1", "REPLACES", ("RFP", "p1.1")), row("p1.2", "REPLACES", ("RFP", "p2.1")),
                       row("p2.1", "CONFIRMS", ("RFP", "p2.2")), row("p2.2", "ADDS"), row("p3.1", "REMOVES", ("RFP", "p1.2"))]},
}


@pytest.fixture
def bid(tmp_path):
    bid = B.create(tmp_path, "Ulster", "deal-1")
    m = bid.manifest()
    rows = [(1, "RFP", "rfp", "2027-05-01", None), (2, "ADD1", "change-addendum", "2027-05-20", 1), (3, "call", "call-transcript", "2027-05-27", None)]
    m["documents"] = [
        {"no": no, "doc_id": doc, "playbook": pb, "issue_date": date, "issue_number": n, "run": f"{doc}/run1", "status": "extracted",
         "speakers": [{"id": "1", "name": "Dana Pike", "side": "buyer", "proposed": "buyer", "why": "B fact"},
                      {"id": "2", "name": "Tom Okafor", "side": "buyer", "proposed": "ours", "why": "team list"}] if doc == "call" else []}
        for no, doc, pb, date, n in rows
    ]
    bid.save(m)
    for no, doc, *_ in rows:
        folder = tmp_path / doc / "run1"
        folder.mkdir(parents=True)
        (folder / "facts.json").write_text(json.dumps(FACTS[doc]))
        (folder / "units.json").write_text(json.dumps([{"id": i, "kind": k, "text": t, "side": ""} for i, k, t in UNITS[doc]]))
        if doc in RELATIONS:
            (folder / "relations.json").write_text(json.dumps(RELATIONS[doc]))
    groups = {"categories": {"S": {"groups": [{"kind": "same", "title": "", "fact_ids": ["f_RFP_p2.2", "f_ADD1_p2.1"]}]}}}
    (bid.folder / "groups.json").write_text(json.dumps(groups))
    B.build(bid)
    return bid


KEY = {
    "relations": [
        {"from": {"doc": "ADD1", "unit": "p1.1"}, "kind": "REPLACES", "to": [{"doc": "RFP", "unit": "p1.1"}]},  # right
        {"from": {"doc": 2, "unit": "p1.2"}, "kind": "REPLACES", "to": [{"doc": "RFP", "unit": "p2.h1"}]},  # a heading, and a number for the doc
        {"from": {"doc": "ADD1", "unit": "p2.1"}, "kind": "CLARIFIES", "to": [{"doc": "RFP", "unit": "p2.2"}]},  # another kind
        {"from": {"doc": "ADD1", "unit": "p2.2"}, "kind": "ADDS"},  # right: no targets
        {"from": {"doc": "ADD1", "unit": "p9.9"}, "kind": "REPLACES", "to": [{"doc": "RFP", "unit": "p1.2"}]},  # no answer for it
    ],
    "sides": {"Dana Pike": "buyer", "Tom Okafor": "ours", "Ghost": "ours"},
    "groups": [[{"doc": "RFP", "text": "11 point"}, {"doc": "ADD1", "text": "11 point"}], ["Add a cover", "June 24"]],
}


def test_relations_applied_groups_and_sides_are_counted(bid):
    got = bideval.score(bid, KEY)
    r = got["relations"]
    assert (r["expected"], r["right"], r["wrong_kind"], r["wrong_targets"], r["missing"]) == (5, 2, 1, 1, 1)
    assert r["extra"] == 1  # the REMOVES on p3.1 is not in the key
    assert any("p1.2 REPLACES: targets RFP:p2.1" in m for m in r["misses"])
    a = got["applied"]  # the key's targets reach the due date, the two facts under the heading and the site visit
    assert a["expected"] == 4 and a["replaced"] == 3 and a["not_replaced"] == 1  # the 11 point rule was missed
    assert a["replaced_but_not_in_key"] == 0
    g = got["groups"]
    assert (g["expected"], g["found"], g["missed"], g["wrong"]) == (2, 1, 1, 0) and g["misses"] == ["Add a cover + June 24"]
    assert got["sides"] == {"expected": 3, "right": 1, "wrong": 1, "not_in_bid": 1, "proposed_right": 2}
    text = bideval.report(got)
    assert "relations: 2 of 5 right" in text and "groups: 1 of 2" in text and "sides: 1 of 3" in text


def test_a_wrong_same_group_and_a_replaced_fact_the_key_does_not_name_are_counted(bid):
    got = bideval.score(bid, {"relations": [{"from": {"doc": "ADD1", "unit": "p1.1"}, "kind": "NONE"}], "groups": []})
    assert got["groups"] == {"expected": 0, "found": 0, "missed": 0, "wrong": 1, "misses": []}
    assert got["applied"]["replaced_but_not_in_key"] == 3  # due date, 2.1 limit, site visit are replaced by relations
    assert set(got) == {"relations", "applied", "groups"}  # no sides in the key: not scored


def test_an_unknown_document_and_a_bid_with_no_facts_are_refused(bid, tmp_path):
    with pytest.raises(ValueError, match="does not have"):
        bideval.score(bid, {"relations": [{"from": {"doc": "ghost", "unit": "p1.1"}, "kind": "NONE"}]})
    with pytest.raises(FileNotFoundError):
        bideval.score(B.create(tmp_path, "Empty"), {"sides": {}})
    assert bideval.report({}) == "the key scores nothing: it has no relations, groups or sides"


def test_the_eval_command_prints_the_counts(bid, tmp_path, capsys):
    key = tmp_path / "key.json"
    key.write_text(json.dumps(KEY))
    assert cli.main(["bid", "eval", bid.bid_id, str(key), "--store", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "relations: 2 of 5 right" in out and "applied:" in out and "sides: 1 of 3" in out
    key.write_text("{")
    assert cli.main(["bid", "eval", bid.bid_id, str(key), "--store", str(tmp_path)]) == 1
    assert cli.main(["bid", "eval", "nope", str(key), "--store", str(tmp_path)]) == 1


def test_bid_add_says_who_suggested_the_type(tmp_path, capsys, monkeypatch):
    root = tmp_path / "runs"
    assert cli.main(["bid", "create", "Ulster", "--store", str(root)]) == 0
    notes = tmp_path / "deal.md"
    notes.write_text("# Deal notes\n\nExported 2027-06-01.\n")
    assert cli.main(["bid", "add", "ulster", str(notes), "--store", str(root)]) == 0
    out = capsys.readouterr().out
    assert "(suggested by rules: rfp)" in out and "rules's" not in out and "not confirmed; use --yes" in out
    from fact_extractor import classify

    real = classify.by_rules
    monkeypatch.setattr(classify, "by_rules", lambda name, data: {**real(name, data), "by": "model"})
    other = tmp_path / "other.md"
    other.write_text("# Other\n\nExported 2027-06-02.\n")
    cli.main(["bid", "add", "ulster", str(other), "--yes", "--store", str(root)])
    assert "(suggested by the model: rfp)" in capsys.readouterr().out

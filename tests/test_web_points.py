"""points.py: a fact with its list, its linked facts and its conflicts. Plain data, no model."""

import pytest

from fact_extractor.web import points as PT

DOCS = {
    1: {"file_name": "rfp.pdf", "playbook": "rfp"},
    2: {"file_name": "add.pdf", "playbook": "change-addendum"},
    3: {"file_name": "notes.md", "playbook": "deal-notes"},
    4: {"file_name": "call.json", "playbook": "call-transcript"},
    5: {"file_name": "qa.pdf", "playbook": "qa-addendum"},
    6: {"file_name": "re.pdf", "playbook": "reissued-rfp"},
    7: {"file_name": "form.pdf", "playbook": "fill-in-template"},
}


def fact(fid, doc_no=1, level=1, text="", page=1, sides=(), **kw):
    cites = [{"id": f"p{page}.{i}", "page": page, "page_label": str(page), "section": "S", "text": text, "side": s}
             for i, s in enumerate(sides or [""], 1)]
    return {"fact_id": fid, "doc_no": doc_no, "level": level, "category": "R", "text": text or fid, "citations": cites,
            "flags": [], "status": "valid", "edited": False, "deleted": False, "relations": [], "group_id": "",
            "group_kind": "", "group_title": "", **kw}


def rel(rid, kind, frm, to, rejected=False):
    return {"id": rid, "kind": kind, "from": {"doc_id": "x", "unit": "u", "fact_id": frm},
            "to": {"doc_id": "y", "unit": "v", "fact_id": to}, "rejected": rejected}


def link(facts, *relations):
    """Put each relation on both of its facts, as the ladder does."""
    by_id = {f["fact_id"]: f for f in facts}
    for r in relations:
        for end in (r["from"]["fact_id"], r["to"]["fact_id"]):
            by_id[end]["relations"].append(dict(r))
    return by_id


# --- source_label ---------------------------------------------------------------------------


@pytest.mark.parametrize("doc_no,level,text", [
    (1, 1, "d1 RFP (buyer document, level 1)"),
    (2, 1, "d2 change addendum (buyer document, level 1)"),
    (5, 1, "d5 Q&A addendum (buyer document, level 1)"),
    (6, 1, "d6 reissued RFP (buyer document, level 1)"),
    (7, 1, "d7 fill-in template (buyer document, level 1)"),
    (3, 4, "d3 deal notes (our own notes, level 4)"),
])
def test_source_label_of_a_document_by_playbook(doc_no, level, text):
    assert PT.source_label(fact("f", doc_no, level), DOCS) == text


@pytest.mark.parametrize("sides,level,text", [
    (["buyer"], 2, "d4 call transcript, buyer speaking (level 2)"),
    (["other-buyer"], 2, "d4 call transcript, the buyer's adviser speaking (level 2)"),
    (["ours"], 3, "d4 call transcript, our side speaking (level 3)"),
    (["other"], 3, "d4 call transcript, another party speaking (level 3)"),
    (["unknown"], 3, "d4 call transcript, speaker's side not known (level 3)"),
    ([""], 3, "d4 call transcript, speaker's side not known (level 3)"),
    (["buyer", "ours"], 2, "d4 call transcript, buyer and our side speaking (level 2)"),
])
def test_source_label_of_a_call_names_the_side(sides, level, text):
    assert PT.source_label(fact("f", 4, level, sides=sides), DOCS) == text


def test_source_label_is_empty_without_documents_or_for_an_unknown_one():
    assert PT.source_label(fact("f", 1), {}) == "" and PT.source_label(fact("f", 9), DOCS) == ""
    assert PT.source_label({**fact("f"), "doc_no": None}, DOCS) == ""


def test_brief_adds_source_replaced_and_stale_only_when_they_apply():
    plain = PT.brief(fact("f"))
    assert list(plain) == ["fact_id", "category", "flags", "status", "text", "page", "edited", "deleted"]
    full = PT.brief(fact("f", flags=["replaced"], stale="section partly replaced"), DOCS)
    assert full["source"] == "d1 RFP (buyer document, level 1)" and full["replaced"] is True
    assert full["stale"] == "section partly replaced"


# --- point ----------------------------------------------------------------------------------


def table():
    rows = [fact(f"r{i}", text=f"Row {i}", group_id="g1", group_kind="list", group_title="Support hours", page=i) for i in (1, 2, 3)]
    rows.append(fact("r4", text="Deleted row", group_id="g1", group_kind="list", group_title="Support hours", deleted=True))
    return rows


def test_a_list_group_returns_every_live_member_in_document_order():
    rows = table()
    by_id = {f["fact_id"]: f for f in reversed(rows)}  # the dict order does not decide
    p = PT.point(by_id["r2"], by_id, [], DOCS)
    assert p["kind"] == "list" and p["title"] == "Support hours"
    assert [m["fact_id"] for m in p["members"]] == ["r1", "r2", "r3"]
    assert p["linked"] == [] and p["conflicts"] == []


def test_a_same_group_and_a_lone_fact():
    a = fact("a", group_id="g", group_kind="same", group_title="Due date")
    b = fact("b", doc_no=2, group_id="g", group_kind="same", group_title="Due date")
    by_id = {"a": a, "b": b}
    assert PT.point(a, by_id, [], DOCS)["kind"] == "same"
    lone = fact("c")
    p = PT.point(lone, {"c": lone}, [], DOCS)
    assert (p["kind"], p["title"], [m["fact_id"] for m in p["members"]]) == ("fact", "", ["c"])
    one = fact("d", group_id="g9", group_kind="list", group_title="T")  # a group with one live member is a fact
    assert PT.point(one, {"d": one}, [], DOCS)["kind"] == "fact"


def test_linked_facts_are_one_hop_and_use_words_from_the_members_side():
    a, b, c, d = fact("a"), fact("b", 2), fact("c", 3, 4), fact("d", 4, 2, sides=["buyer"])
    by_id = link([a, b, c, d], rel("r1", "REPLACES", "b", "a"), rel("r2", "CLARIFIES", "a", "c"), rel("r3", "CONFIRMS", "d", "b"))
    p = PT.point(a, by_id, [], DOCS)
    got = {e["fact"]["fact_id"]: e["relation"] for e in p["linked"]}
    assert got == {"b": "replaced by", "c": "clarifies"}  # d is linked to b, not to a: not pulled in
    assert "of" not in p["linked"][0]
    assert p["linked"][0]["fact"]["source"] == "d2 change addendum (buyer document, level 1)"
    assert PT.point(b, by_id, [], DOCS)["linked"][-1] == {"relation": "confirmed by", "fact": PT.brief(d, DOCS)}


@pytest.mark.parametrize("kind,member_is_to,words", [
    ("REPLACES", True, "replaced by"), ("REMOVES", True, "removed by"), ("CONFIRMS", True, "confirmed by"),
    ("CLARIFIES", True, "clarified by"), ("DISAGREES", True, "disagreed with by"), ("ADDS", True, "added to by"),
    ("REPLACES", False, "replaces"), ("REMOVES", False, "removes"), ("CONFIRMS", False, "confirms"),
    ("CLARIFIES", False, "clarifies"), ("DISAGREES", False, "disagrees with"), ("ADDS", False, "adds to"),
])
def test_relation_words_from_both_ends(kind, member_is_to, words):
    m, o = fact("m"), fact("o", 2)
    by_id = link([m, o], rel("r", kind, "o", "m") if member_is_to else rel("r", kind, "m", "o"))
    assert PT.point(m, by_id, [], DOCS)["linked"][0]["relation"] == words


def test_rejected_relations_and_deleted_facts_are_left_out():
    a, b, c = fact("a"), fact("b", 2), fact("c", 2, deleted=True)
    by_id = link([a, b, c], rel("r1", "REPLACES", "b", "a", rejected=True), rel("r2", "CLARIFIES", "c", "a"))
    assert PT.point(a, by_id, [], DOCS)["linked"] == []


def test_links_of_every_member_are_returned_with_the_member_they_belong_to():
    rows = table()[:3]
    other = fact("o", 4, 2, sides=["buyer"])
    by_id = link([*rows, other], rel("r1", "DISAGREES", "o", "r2"))
    p = PT.point(rows[0], by_id, [], DOCS)
    assert p["linked"] == [{"relation": "disagreed with by", "of": "r2", "fact": PT.brief(other, DOCS)}]


def test_open_conflicts_naming_a_member_are_attached():
    a, b = fact("a"), fact("b", 4, 2)
    conflicts = [{"id": "d:1", "title": "Due date", "status": "open", "fact_ids": ["b", "a"]},
                 {"id": "d:2", "title": "Done", "status": "resolved", "fact_ids": ["a"]},
                 {"id": "d:3", "title": "Other", "status": "open", "fact_ids": ["zz"]}]
    assert PT.point(a, {"a": a, "b": b}, conflicts, DOCS)["conflicts"] == [{"id": "d:1", "title": "Due date", "status": "open"}]


def test_the_cap_puts_disagreements_and_replacements_first_and_counts_the_rest():
    m = fact("m")
    others = [fact(f"o{i}", 2) for i in range(5)]
    rels = [rel(f"c{i}", "CLARIFIES", f"o{i}", "m") for i in range(4)] + [rel("x", "DISAGREES", "o4", "m")]
    by_id = link([m, *others], *rels)
    p = PT.point(m, by_id, [], DOCS, max_linked=3)
    assert [e["fact"]["fact_id"] for e in p["linked"]] == ["o4", "o0", "o1"] and p["more_linked"] == 2
    assert "more_linked" not in PT.point(m, by_id, [], DOCS)


def test_point_parts_leave_out_what_is_empty():
    a = fact("a")
    assert PT.point_parts(PT.point(a, {"a": a}, [], DOCS), "a") == {}
    rows = table()[:3]
    parts = PT.point_parts(PT.point(rows[1], {f["fact_id"]: f for f in rows}, [], DOCS), "r2")
    assert list(parts) == ["list"] and [i["fact_id"] for i in parts["list"]["items"]] == ["r1", "r3"]

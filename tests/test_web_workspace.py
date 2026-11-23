"""Corrections, effective facts and conflicts of the web workspace. Offline, no model."""

import json
from types import SimpleNamespace

import pytest

from fact_extractor.web.workspace import BadRequest, Conflict, NotFound, Workspace, live_entries, replay


def cite(cid, page, text, section="S"):
    return {"id": cid, "page": page, "page_label": str(page), "section": section, "text": text, "bbox": [1, 2, 30, 40]}


def fact(fid, cat, text, cites, **kw):
    return {"fact_id": fid, "doc_id": "doc", "run_id": "run1", "category": cat, "text": text, "citations": cites,
            "flags": kw.get("flags", []), "status": kw.get("status", "valid"), "note": "", "conflicts": kw.get("conflicts", [])}


FACTS = [
    fact("f_b1", "B", "Buyer is the County", [cite("p1.1", 1, "The County seeks bids.")]),
    fact("f_d1", "D", "Bids due March 3", [cite("p1.2", 1, "Bids are due March 3.", "Schedule")],
         status="conflict", conflicts=["f_q1"], flags=["mandatory"]),
    fact("f_d2", "D", "Bids due March 5", [cite("p5.1", 5, "Bids are due March 5.", "Term")]),
    fact("f_q1", "Q", "Due date is given twice",
         [cite("p1.2", 1, "Bids are due March 3.", "Schedule"), cite("p5.1", 5, "Bids are due March 5.", "Term")]),
    fact("f_r1", "R", "Vendor must keep 24/7 support", [cite("p3.1", 3, "Vendor shall give support.")]),
]


def make_run(tmp_path, name="doc/run1", facts=FACTS):
    folder = tmp_path / name
    folder.mkdir(parents=True)
    (folder / "facts.json").write_text(json.dumps(facts))
    return folder


@pytest.fixture
def ws(tmp_path):
    return Workspace(make_run(tmp_path) / "facts.json")


def test_no_log_gives_base_facts_and_source_conflict(ws):
    s = ws.state()
    assert [f["fact_id"] for f in s.facts] == ["f_b1", "f_d1", "f_q1", "f_r1", "f_d2"]  # by page
    assert all(f["origin"] == "extracted" and not f["edited"] and f["original"] is None for f in s.facts)
    [c] = s.conflicts
    assert c["id"] == "q:f_q1" and c["kind"] == "source" and c["status"] == "open"
    assert c["title"] == "Due date is given twice"
    assert c["fact_ids"] == ["f_q1", "f_d1"]
    assert [o["label"] for o in c["options"]] == ["Page 1: Schedule", "Page 5: Term"]
    assert c["options"][1]["citation"] == {"id": "p5.1", "page": 5, "page_label": "5", "section": "Term"}
    assert not ws.dir.exists()  # reading creates nothing


def test_state_is_replayed_only_when_a_file_changes(ws):
    s = ws.state()
    assert ws.state() is s  # nothing changed: no replay
    ws.edit("f_d1", {"text": "Bids due March 4"})
    after_edit = ws.state()
    assert after_edit is not s and after_edit.get("f_d1")["text"] == "Bids due March 4"
    assert ws.state() is after_edit
    # Another process appends to the log: the next read sees it.
    target = ws.log()[-1]["id"]
    with open(ws.corrections_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": "c_x", "at": "t", "source": "ui", "op": "undo", "target": target}) + "\n")
    assert ws.state().get("f_d1")["text"] == "Bids due March 3"
    # The facts file is rewritten: the run is read again.
    rows = json.loads(ws.facts_path.read_text())
    rows[0]["text"] = "Buyer is the City of Durham"
    ws.facts_path.write_text(json.dumps(rows))
    assert ws.state().get("f_b1")["text"] == "Buyer is the City of Durham"


def test_edit_keeps_original_and_later_edit_wins(ws):
    ws.edit("f_d1", {"text": "Bids due March 4"}, "customer said so")
    f = ws.edit("f_d1", {"text": "Bids due March 5", "flags": []})
    assert f["text"] == "Bids due March 5" and f["flags"] == []
    assert f["edited"] and f["original"] == {"text": "Bids due March 3", "flags": ["mandatory"]}
    assert len(f["corrections"]) == 2
    entry = ws.log()[0]
    assert entry["op"] == "edit" and entry["source"] == "ui" and entry["reason"] == "customer said so"
    assert entry["id"].startswith("c_") and entry["at"].endswith("Z")


def test_edit_back_to_extracted_value_is_not_changed(ws):
    ws.edit("f_b1", {"text": "x"})
    f = ws.edit("f_b1", {"text": "Buyer is the County"})
    assert f["original"] is None and not f["edited"]


def test_undo_removes_one_entry_and_undo_of_undo_brings_it_back(ws):
    ws.edit("f_b1", {"text": "one"})
    first = ws.log()[0]["id"]
    ws.edit("f_b1", {"note": "n"})
    ws.undo(first)
    f = ws.state().get("f_b1")
    assert f["text"] == "Buyer is the County" and f["note"] == "n"
    with pytest.raises(Conflict):
        ws.undo(first)
    undo_id = ws.log()[-1]["id"]
    assert [e["id"] for e in live_entries(ws.log())] == [ws.log()[1]["id"]]
    assert undo_id not in {c["id"] for c in ws.corrections()}  # an undo entry is not listed
    # an undo that is itself undone no longer cancels anything
    log = ws.log() + [{"id": "c_x", "op": "undo", "target": undo_id}]
    assert [e["id"] for e in live_entries(log)] == [first, ws.log()[1]["id"]]


def test_corrections_listing(ws):
    ws.edit("f_b1", {"text": "one"})
    ws.delete("f_r1")
    ws.undo(ws.log()[0]["id"])
    rows = ws.corrections()
    assert [r["op"] for r in rows] == ["delete", "edit"]  # newest first
    assert [r["undone"] for r in rows] == [False, True]
    assert rows[0]["fact_text"] == "Vendor must keep 24/7 support"


def test_corrections_before_is_the_value_just_before_each_edit(ws):
    ws.edit("f_d1", {"text": "Bids due March 4"})
    ws.edit("f_d1", {"text": "Bids due March 6", "note": "moved"})
    rows = ws.corrections()
    assert rows[0]["before"] == {"text": "Bids due March 4", "note": ""}  # not the first-extracted text
    assert rows[1]["before"] == {"text": "Bids due March 3"}
    ws.undo(ws.log()[0]["id"])  # with the first edit undone, the second replaced the extracted text
    rows = [r for r in ws.corrections() if r["op"] == "edit"]
    assert rows[0]["before"]["text"] == "Bids due March 3"
    assert rows[1]["undone"] and rows[1]["before"] == {"text": "Bids due March 3"}


def test_corrections_before_on_an_added_fact(ws):
    f = ws.add({"category": "R", "text": "Bring two copies"})
    ws.edit(f["fact_id"], {"text": "Bring three copies"})
    assert ws.corrections()[0]["before"] == {"text": "Bring two copies"}


def test_corrections_name_the_conflict_and_the_choice(ws):
    ws.resolve("q:f_q1", option=1)
    row = ws.corrections()[0]
    assert row["conflict_title"] == "Due date is given twice" and row["choice"] == "Page 5: Term"
    ws.reopen("q:f_q1")
    ws.resolve("q:f_q1", text="March 4")
    assert ws.corrections()[0]["choice"] == "Your own answer: March 4"
    c = raise_it(ws)
    row = ws.corrections()[0]
    assert row["op"] == "raise" and row["conflict_title"] == "Which deadline moves" and "choice" not in row
    assert ws.state().conflict("q:f_q1")["description"]  # kept for the chat agent; the card hides it
    assert c["description"]


def test_delete_and_restore(ws):
    ws.delete("f_r1", "wrong")
    s = ws.state()
    assert s.get("f_r1")["deleted"] and "f_r1" not in [f["fact_id"] for f in s.visible()]
    f = ws.restore("f_r1")
    assert not f["deleted"] and f["corrections"] == []


def test_restore_undoes_every_live_entry_on_the_fact(ws):
    ws.edit("f_b1", {"text": "a"})
    ws.edit("f_b1", {"category": "C"})
    f = ws.restore("f_b1")
    assert f["text"] == "Buyer is the County" and f["category"] == "B" and not f["edited"]


def test_add_user_fact_with_and_without_document(ws):
    anchor = SimpleNamespace(citation=lambda: cite("p9.1", 9, "Source unit"))
    doc = SimpleNamespace(anchors={"p9.1": anchor})
    ws.add({"category": "R", "text": "  Needs ISO cert ", "flags": ["mandatory"], "citation_ids": ["p9.1", "p9.99"]})
    log = ws.log()
    f = replay(ws.run().records, log, doc).get(log[0]["fact_id"])
    assert f["fact_id"].startswith("u_") and len(f["fact_id"]) == 12
    assert f["origin"] == "user" and f["text"] == "Needs ISO cert" and f["flags"] == ["mandatory"]
    assert [c["id"] for c in f["citations"]] == ["p9.1"] and f["unresolved_ids"] == ["p9.99"]
    assert f["doc_id"] == "doc" and f["status"] == "valid"
    bare = replay(ws.run().records, log, None).get(log[0]["fact_id"])
    assert bare["citations"] == [] and bare["unresolved_ids"] == ["p9.1", "p9.99"]
    assert bare["fact_id"] == [x for x in replay(ws.run().records, log).facts if x["origin"] == "user"][0]["fact_id"]


def test_user_fact_can_be_edited_and_deleted(ws):
    f = ws.add({"category": "C", "text": "Cap at 1M"})
    g = ws.edit(f["fact_id"], {"text": "Cap at 2M"})
    assert g["text"] == "Cap at 2M" and g["original"] is None and g["edited"]
    ws.delete(f["fact_id"])
    assert ws.state().get(f["fact_id"])["deleted"]


@pytest.mark.parametrize("fields", [
    {"text": "  "}, {"category": "Z"}, {"flags": ["nope"]}, {"flags": "mandatory"}, {"colour": "red"}, {"note": 3}, {},
])
def test_edit_validation(ws, fields):
    with pytest.raises(BadRequest):
        ws.edit("f_b1", fields)
    assert ws.log() == []


def test_add_validation(ws):
    for bad in ({"category": "R", "text": ""}, {"category": "Q9", "text": "x"}, {"text": "x"},
                {"category": "R", "text": "x", "citation_ids": "p1.1"}):
        with pytest.raises(BadRequest):
            ws.add(bad)


def test_unknown_fact_is_not_found(ws):
    for call in (lambda: ws.edit("nope", {"text": "x"}), lambda: ws.delete("nope"), lambda: ws.restore("nope"),
                 lambda: ws.undo("c_nope")):
        with pytest.raises(NotFound):
            call()


def test_resolve_source_conflict_effects(ws):
    c = ws.resolve("q:f_q1", option=1)
    assert c["status"] == "resolved"
    assert c["resolution"]["option"] == 1 and c["resolution"]["label"] == "Page 5: Term"
    assert c["resolution"]["text"] == "Bids are due March 5."
    s = ws.state()
    assert s.get("f_d1")["status"] == "valid" and "replaced" in s.get("f_d1")["flags"]
    assert "replaced" not in s.get("f_d2")["flags"]
    q = s.get("f_q1")
    assert q["resolution"]["conflict_id"] == "q:f_q1" and q["resolution"]["text"] == "Bids are due March 5."
    assert not s.get("f_d1")["edited"]  # derived, not an edit
    assert s.conflicts[0]["status"] == "resolved"


def test_resolve_source_choosing_the_cited_unit_does_not_replace(ws):
    ws.resolve("q:f_q1", option=0)
    f = ws.state().get("f_d1")
    assert f["status"] == "valid" and "replaced" not in f["flags"]


def test_resolve_source_custom_answer_adds_no_replaced_flag(ws):
    c = ws.resolve("q:f_q1", text="March 4 by phone call")
    assert c["resolution"]["option"] is None and c["resolution"]["text"] == "March 4 by phone call"
    f = ws.state().get("f_d1")
    assert f["status"] == "valid" and "replaced" not in f["flags"]


def test_resolve_errors_and_reopen(ws):
    with pytest.raises(NotFound):
        ws.resolve("q:nope", option=0)
    with pytest.raises(BadRequest):
        ws.resolve("q:f_q1", option=2)
    with pytest.raises(BadRequest):
        ws.resolve("q:f_q1", option=-1)
    with pytest.raises(BadRequest):
        ws.resolve("q:f_q1")
    with pytest.raises(Conflict):
        ws.reopen("q:f_q1")
    ws.resolve("q:f_q1", option=1)
    with pytest.raises(Conflict):
        ws.resolve("q:f_q1", option=0)
    c = ws.reopen("q:f_q1")
    assert c["status"] == "open" and c["resolution"] is None
    s = ws.state()
    assert s.get("f_d1")["status"] == "conflict" and "replaced" not in s.get("f_d1")["flags"]
    assert s.get("f_q1")["resolution"] is None
    ws.resolve("q:f_q1", option=0)  # can be resolved again after a reopen


def test_open_conflicts_listed_first(ws):
    ws.raise_conflict("Which date", "d", ["f_d1"], [{"label": "A", "text": "a"}, {"label": "B", "text": "b"}])
    ws.resolve("q:f_q1", option=0)
    assert [c["status"] for c in ws.state().conflicts] == ["open", "resolved"]


def raise_it(ws):
    return ws.raise_conflict(
        "Which deadline moves", "The customer said the deadline is 5 March.", ["f_d1", "f_d2"],
        [{"label": "Change the first", "text": "edit f_d1",
          "changes": [{"op": "edit", "fact_id": "f_d1", "fields": {"text": "Bids due March 5"}}]},
         {"label": "Drop the second", "text": "delete f_d2",
          "changes": [{"op": "delete", "fact_id": "f_d2"}]}])


def test_raised_conflict_applies_chosen_changes_and_reopen_takes_them_back(ws):
    c = raise_it(ws)
    assert c["id"].startswith("k_") and len(c["id"]) == 10 and c["kind"] == "raised" and c["status"] == "open"
    assert ws.state().get("f_d1")["text"] == "Bids due March 3"  # nothing applied before the choice
    r = ws.resolve(c["id"], option=0)
    assert r["status"] == "resolved" and r["resolution"]["label"] == "Change the first"
    f = ws.state().get("f_d1")
    assert f["text"] == "Bids due March 5" and f["edited"]
    edit = [e for e in ws.log() if e["op"] == "edit"][0]
    assert edit["conflict_id"] == c["id"] and edit["source"] == "ui"
    ws.reopen(c["id"])
    assert ws.state().get("f_d1")["text"] == "Bids due March 3"
    ws.resolve(c["id"], option=1)
    assert ws.state().get("f_d2")["deleted"] and ws.state().get("f_d1")["text"] == "Bids due March 3"


def test_raised_conflict_custom_answer_applies_nothing(ws):
    c = raise_it(ws)
    ws.resolve(c["id"], text="Ask the buyer")
    s = ws.state()
    assert s.conflict(c["id"])["resolution"]["text"] == "Ask the buyer"
    assert not s.get("f_d2")["deleted"] and s.get("f_d1")["text"] == "Bids due March 3"


def test_undoing_the_raise_removes_the_conflict(ws):
    c = raise_it(ws)
    raise_entry = ws.log()[0]["id"]
    ws.undo(raise_entry)
    assert ws.state().conflict(c["id"]) is None


def test_raise_validation(ws):
    two = [{"label": "A"}, {"label": "B"}]
    for args in (("", "d", ["f_d1"], two), ("t", "d", [], two), ("t", "d", ["f_d1"], two[:1]),
                 ("t", "d", ["f_d1"], [{"label": ""}, {"label": "B"}]),
                 ("t", "d", ["f_d1"], [{"label": "A", "changes": [{"op": "add", "fact_id": "f_d1"}]}, {"label": "B"}]),
                 ("t", "d", ["f_d1"], [{"label": "A", "changes": [{"op": "edit", "fact_id": "f_d1", "fields": {"category": "Z"}}]}, {"label": "B"}])):
        with pytest.raises(BadRequest):
            ws.raise_conflict(*args)
    with pytest.raises(NotFound):
        ws.raise_conflict("t", "d", ["f_none"], two)


def test_deleting_the_q_fact_hides_its_conflict(ws):
    ws.delete("f_q1")
    assert ws.state().conflicts == []


def test_run_files_never_change_and_files_are_created_lazily(tmp_path):
    folder = make_run(tmp_path)
    before = (folder / "facts.json").read_bytes()
    ws = Workspace(folder / "facts.json")
    ws.state(), ws.corrections()
    assert not (folder / "workspace").exists()
    ws.edit("f_b1", {"text": "x"})
    ws.resolve("q:f_q1", option=0)
    ws.write_summaries({"sections": {}, "pinned": ["f_b1"]})
    ws.append_chat({"id": "m_1", "role": "user"})
    assert (folder / "facts.json").read_bytes() == before
    assert sorted(p.name for p in (folder / "workspace").iterdir()) == ["chat.jsonl", "corrections.jsonl", "summaries.json"]
    lines = (folder / "workspace" / "corrections.jsonl").read_text().splitlines()
    assert len(lines) == 2 and all(json.loads(x) for x in lines)
    assert Workspace(folder / "facts.json").read_summaries()["pinned"] == ["f_b1"]
    ws.clear_chat()
    assert ws.chat() == []


def test_damaged_log_lines_are_skipped(ws):
    ws.edit("f_b1", {"text": "one"})
    with open(ws.corrections_path, "a") as f:
        f.write("not json\n\n[1]\n")
    assert ws.state().get("f_b1")["text"] == "one"


# --- a bid: conflicts derived for documents, ungrouping ----------------------------------------


def bid_folder(tmp_path, conflicts, facts=None):
    folder = make_run(tmp_path, "_bids/b1", facts or FACTS)
    (folder / "bid.json").write_text(json.dumps({"bid_id": "b1", "documents": []}))
    (folder / "conflicts.json").write_text(json.dumps(conflicts))
    return folder


def doc_conflict(**kw):
    return {
        "id": "d:abc1234567", "kind": "document", "title": "CALL disagrees with RFP", "description": "d",
        "fact_ids": ["f_d1", "f_d2"], "reason": "levels disagree", "doc_id": "CALL", "closed_by": "", "status": "open",
        "options": [
            {"label": "Keep the RFP fact", "text": "", "citation": None, "changes": []},
            {"label": "Rely on CALL", "text": "", "citation": None,
             "changes": [{"op": "edit", "fact_id": "f_d1", "fields": {"flags": ["mandatory", "replaced"]}, "add_flag": "replaced"}]},
            {"label": "Ask the buyer", "text": "", "citation": None, "changes": [], "question": True},
        ],
        **kw,
    }


def test_an_ordinary_run_has_no_document_conflicts_and_no_bid(ws):
    assert not ws.is_bid() and {c["kind"] for c in ws.state().conflicts} == {"source"}
    assert ws._entry("edit", "document")["source"] == "document"
    with pytest.raises(BadRequest):
        ws._entry("edit", "robot")


def test_a_document_conflict_is_shown_and_resolved_like_a_raised_one(tmp_path):
    ws = Workspace(bid_folder(tmp_path, [doc_conflict()]) / "facts.json")
    assert ws.is_bid() and ws.document() is None
    c = ws.state().conflict("d:abc1234567")
    assert (c["kind"], c["status"], c["reason"], c["closed_by"]) == ("document", "open", "levels disagree", "")
    assert c["options"][2]["question"] is True
    ws.edit("f_d1", {"flags": ["risk"]})  # the user changed the flags before choosing
    got = ws.resolve("d:abc1234567", option=1)
    assert got["status"] == "resolved" and got["resolution"]["label"] == "Rely on CALL"
    log = ws.log()
    assert [e["op"] for e in log[-2:]] == ["resolve", "edit"] and log[-1]["conflict_id"] == "d:abc1234567"
    assert ws.state().get("f_d1")["flags"] == ["risk", "replaced"]  # added to the flags it has now
    row = [r for r in ws.corrections() if r["op"] == "resolve"][0]
    assert row["choice"] == "Rely on CALL" and row["conflict_title"] == "CALL disagrees with RFP"
    ws.reopen("d:abc1234567")  # takes the change back with it
    assert ws.state().get("f_d1")["flags"] == ["risk"] and ws.state().conflict("d:abc1234567")["status"] == "open"
    ws.resolve("d:abc1234567", option=2)  # asking the buyer changes no fact
    assert ws.state().conflict("d:abc1234567")["resolution"]["label"] == "Ask the buyer" and ws.state().get("f_d1")["flags"] == ["risk"]


def test_a_conflict_a_later_document_settled_shows_as_settled(tmp_path):
    ws = Workspace(bid_folder(tmp_path, [doc_conflict(closed_by="ADD1")]) / "facts.json")
    c = ws.state().conflict("d:abc1234567")
    assert c["status"] == "resolved" and c["resolution"]["label"] == "Settled by ADD1"
    with pytest.raises(Conflict):
        ws.resolve("d:abc1234567", option=0)
    with pytest.raises(Conflict):
        ws.reopen("d:abc1234567")  # no choice of the user's to take back


def test_a_conflict_the_user_resolved_is_shown_again_when_a_later_document_changes_it(tmp_path):
    folder = bid_folder(tmp_path, [doc_conflict()])
    ws = Workspace(folder / "facts.json")
    ws.resolve("d:abc1234567", option=0)
    assert ws.state().conflict("d:abc1234567")["status"] == "resolved"
    (folder / "conflicts.json").write_text(json.dumps([doc_conflict(closed_by="ADD1")]))  # build ran again: the key sees the new stamp
    c = ws.state().conflict("d:abc1234567")
    assert c["status"] == "open" and c["note"] == "A later document changes this" and c["previous_resolution"]["label"] == "Keep the RFP fact"
    assert ws.resolve("d:abc1234567", option=1)["status"] == "resolved"


def test_the_state_key_includes_the_stamp_of_conflicts_json(tmp_path):
    folder = bid_folder(tmp_path, [])
    ws = Workspace(folder / "facts.json")
    s = ws.state()
    assert ws.state() is s and ws.state().conflict("d:abc1234567") is None
    (folder / "conflicts.json").write_text(json.dumps([doc_conflict()]))
    assert ws.state().conflict("d:abc1234567") is not None
    (folder / "conflicts.json").write_text(json.dumps([doc_conflict(fact_ids=["f_nowhere"])]))  # about no fact here: not shown
    assert ws.state().conflict("d:abc1234567") is None


def grouped():
    rows = [dict(f) for f in FACTS]
    for r in rows[:2]:
        r.update(group_id="g_1", group_kind="same", group_title="Related statements")
    return rows


def test_ungroup_clears_the_group_and_regroup_undoes_it(tmp_path):
    ws = Workspace(make_run(tmp_path, "d/r", grouped()) / "facts.json")
    assert {f["fact_id"] for f in ws.state().facts if f["group_id"] == "g_1"} == {"f_b1", "f_d1"}
    entry = ws.ungroup("g_1")
    assert entry["op"] == "ungroup" and entry["fields"]["group_id"] == "g_1"
    assert all(not f["group_id"] and not f["group_title"] for f in ws.state().facts)
    row = ws.corrections()[0]
    assert row["description"] == "Ungrouped: Related statements" and not row["undone"]
    with pytest.raises(Conflict):
        ws.ungroup("g_1")
    ws.regroup("g_1")
    assert {f["fact_id"] for f in ws.state().facts if f["group_id"] == "g_1"} == {"f_b1", "f_d1"} and ws.corrections()[0]["undone"]
    ws.ungroup("g_1")
    ws.undo(ws.log()[-1]["id"])  # the generic undo takes it back too
    assert any(f["group_id"] == "g_1" for f in ws.state().facts)
    with pytest.raises(NotFound):
        ws.ungroup("g_none")
    with pytest.raises(NotFound):
        ws.regroup("g_1")  # not ungrouped any more

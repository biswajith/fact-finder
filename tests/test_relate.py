"""RELATE (relate.py), the hold-back of section references, and relations in the bid's fact list."""

import json

import pymupdf
import pytest
from conftest import ScriptedClient, task_name

from fact_extractor import bid as B
from fact_extractor import playbooks, relate, results, units
from fact_extractor.models import Anchor, TaggedDocument
from fact_extractor.web.workspace import NotFound, Workspace

FAST = units.Config(backoff_base=0, warmup_timeout=1, brief=False, grouping=False)


def tagged(doc_id, *rows) -> TaggedDocument:
    """A document from (unit id, kind, text) rows."""
    anchors = {i: Anchor(doc_id, i, 1, "1", "", t, None, k) for i, k, t in rows}
    return TaggedDocument(doc_id, anchors, "".join(f"[{i}] {t}\n" for i, _, t in rows), 1)


def fact(doc_id, unit, text, cat="D"):
    return {"fact_id": f"f_{doc_id}_{unit}", "doc_id": doc_id, "category": cat, "text": text, "citations": [{"id": unit}]}


# --- parse ---------------------------------------------------------------------------------


def batch():
    return [
        {"unit": "p1.1", "token": "d2:p1.1", "text": "Due date is changed.", "candidates": [
            {"token": "d1:p2.31", "doc_no": 1, "unit": "p2.31", "text": "Due June 10.", "heading": False},
            {"token": "d1:p9.h4", "doc_no": 1, "unit": "p9.h4", "text": "3.17 Format", "heading": True}]},
        {"unit": "p1.2", "token": "d2:p1.2", "text": "Add a form.", "candidates": []},
        {"unit": "p1.3", "token": "d2:p1.3", "text": "No change.", "candidates": []},
    ]


def test_parse_keeps_good_lines_and_drops_bad_ones():
    kinds = playbooks.load("change-addendum").relations
    text = "\n".join([
        "d2:p1.1|REPLACES|d1:p2.31, d1:p9.h4",  # two targets
        "d2:p1.2|ADDS|",
        "d2:p1.3|DESTROYS|",  # not a kind
        "d9:p1.4|NONE|",  # not a unit of the batch
        "END|4",
    ])
    got = relate.parse(text, batch(), kinds)
    assert got == {"p1.1": ("REPLACES", [(1, "p2.31"), (1, "p9.h4")]), "p1.2": ("ADDS", [])}
    assert relate.parse("d2:p1.1|REPLACES|d1:p7.7", batch(), kinds) == {}  # a target that was not a candidate
    assert relate.parse("d2:p1.1|REPLACES|d1:p2.31", batch(), ("ADDS", "NONE")) == {}  # a kind the playbook does not offer
    assert relate.parse("p1.1|replaces|D1:P2.31\nd2:p1.1|NONE|", batch(), kinds) == {"p1.1": ("REPLACES", [(1, "p2.31")])}
    assert relate.parse("d2:p1.1|CONFIRMS|d1:p2.31", batch(), playbooks.load("call-transcript").relations)["p1.1"][0] == "CONFIRMS"


def test_the_prompt_shows_units_candidates_and_only_the_kinds_of_the_playbook():
    task = relate.relate_task(batch())
    assert "[d2:p1.1] Due date is changed.\n  > [d1:p2.31] Due June 10.\n  > [d1:p9.h4] (heading) 3.17 Format" in task
    assert task.endswith("After the last line write: END|3")
    sys_call = relate.system(playbooks.load("call-transcript").relations)
    assert "- CONFIRMS:" in sys_call and "- REPLACES:" not in sys_call and "- REMOVES:" not in sys_call
    assert "- REPLACES:" in relate.system(playbooks.load("change-addendum").relations)


# --- candidates ----------------------------------------------------------------------------


def test_candidates_include_a_fact_that_shares_a_date_and_a_heading_for_a_reference():
    rfp = tagged(
        "RFP",
        ("p1.1", "sentence", "Proposals are due June 10, 2026."), ("p1.2", "sentence", "Vendors must carry insurance."),
        ("p2.1", "heading", "3.17 Proposal Format"), ("p2.2", "sentence", "Limit of 30 pages."),
        ("p3.1", "heading", "4.1 Insurance"), ("p3.2", "sentence", "Site visit on June 3, 2026."),
    )
    facts = [fact("RFP", "p1.1", "Proposals due June 10, 2026"), fact("RFP", "p1.2", "Vendor carries insurance"),
             fact("RFP", "p2.2", "Limit 30 pages"), fact("RFP", "p3.2", "Site visit June 3, 2026")]
    add = tagged(
        "ADD1", ("p1.1", "sentence", "The date of the opening is June 10, 2026."), ("p1.2", "sentence", "Section 3.17 is deleted."),
        ("p1.3", "sentence", "Nothing else is changed."),
    )
    got = relate.candidates(add, [], [(1, rfp, facts)], refs=["p1.2"])
    assert got["p1.1"][0] == (1, "p1.1")  # shares the date: first, before the facts that only share words
    assert got["p1.2"][0] == (1, "p2.1")  # the heading that carries the section number comes first
    assert (1, "p2.1") not in got["p1.1"]  # headings only for a unit with a reference
    assert all(len(v) <= relate.MAX_CANDIDATES for v in got.values())
    assert set(got) == {"p1.1", "p1.2", "p1.3"}
    # more than 12 earlier facts: still at most 12, the best by rare words first
    many = tagged("BIG", *[(f"p1.{n}", "sentence", f"Requirement {n} concerns widgets of kind {n}.") for n in range(1, 30)])
    cands = relate.candidates(tagged("A", ("p1.1", "sentence", "Widgets of kind 7 change.")), [], [(1, many, [fact("BIG", f"p1.{n}", f"Requirement {n}") for n in range(1, 30)])], [])
    assert 0 < len(cands["p1.1"]) <= 12


# --- the call ------------------------------------------------------------------------------


async def test_relate_asks_in_batches_asks_again_for_missing_units_and_records_the_rest():
    rfp = tagged("RFP", ("p1.1", "sentence", "Proposals are due June 10, 2026."))
    rows = [("p1.%d" % n, "sentence", f"Statement {n} about the due date June 10, 2026.") for n in range(1, 36)]
    add = tagged("ADD1", *rows)
    seen = []

    def handler(req):
        units_in = [ln[1:].partition("] ")[0] for ln in req.task.splitlines() if ln.startswith("[d2:")]
        seen.append(units_in)
        if req.task.startswith("TASK RELATE") and "d2:p1.35" in units_in and len(units_in) == 1:
            return ""  # the second ask for the one unit fails too
        answered = units_in[:-1] if len(units_in) == 5 else units_in  # the first batch of the second part leaves one out
        return "\n".join(f"{u}|CONFIRMS|d1:p1.1" for u in answered) + f"\nEND|{len(answered)}"

    client = ScriptedClient(handler)
    pb = playbooks.load("change-addendum")
    out = await relate.relate(add, 2, pb, [], [(1, rfp, [fact("RFP", "p1.1", "Due June 10, 2026")])], client, FAST)
    assert [len(s) for s in seen] == [30, 5, 1] and out["against"] == ["RFP"]
    assert out["incomplete"] == ["p1.35"] and len(out["units"]) == 35
    row = next(r for r in out["units"] if r["unit"] == "p1.2")
    assert row == {"unit": "p1.2", "kind": "CONFIRMS", "targets": [{"doc_id": "RFP", "unit": "p1.1"}],
                   "candidates": [{"doc_id": "RFP", "unit": "p1.1"}], "votes": ["CONFIRMS"]}
    assert next(r for r in out["units"] if r["unit"] == "p1.35")["kind"] == ""
    assert [c["name"] for c in out["calls"]] == ["RELATE1", "RELATE2", "RELATE1b"] and out["calls"][-1]["status"] == "incomplete"
    assert {r.system for r in client.requests} == {relate.system(pb.relations)} and all(r.document == "" for r in client.requests)


async def test_a_document_with_nothing_earlier_makes_no_call():
    client = ScriptedClient(lambda r: pytest.fail("a model call"))
    out = await relate.relate(tagged("N", ("p1.1", "sentence", "Hello.")), 1, playbooks.load("deal-notes"), [], [], client, FAST)
    assert out == {"playbook": "deal-notes@1", "against": [], "units": [], "incomplete": [], "held_refs": [], "ref_units": [], "calls": []}
    assert client.requests == []


# --- a bid with an addendum -----------------------------------------------------------------


def pdf(*paras: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for n, p in enumerate(paras):
        page.insert_text((72, 72 + 60 * n), p)
    return doc.tobytes()


def handler(req):
    """Label a unit by its first keyword, find one section reference, answer RELATE from the candidates shown."""
    kind = task_name(req)
    if kind in ("LABEL", "STATE"):
        ids = [i.strip() for i in req.task.splitlines()[2].split(",")]
        lines = {ln[1:].partition("] ")[0]: ln.partition("] ")[2] for ln in req.document.splitlines() if ln.startswith("[")}
        out = []
        for i in ids:
            label = "D" if "due" in lines[i] else "R" if "must" in lines[i] else "-"
            out.append(f"{i}|{label if kind == 'LABEL' else (lines[i] if label != '-' else '-')}")
        return "\n".join(out) + f"\nEND|{len(ids)}\n"
    if kind == "XREF":
        for ln in req.document.splitlines():
            if "Section 3.15" in ln:
                return f"REF|{ln[1:].partition('] ')[0]}|Section 3.15|none|section|\nEND|1\n"
        return "END|0\n"
    if kind == "RELATE":
        found, out = [], []
        for ln in req.task.splitlines():
            if ln.startswith("[d"):
                found.append((ln[1:].partition("] ")[0], ln.partition("] ")[2], []))
            elif ln.startswith("  > ["):
                found[-1][2].append((ln[5:].partition("]")[0], ln.partition("] ")[2]))
        for token, text, cands in found:
            hit = next((c for c, t in cands if "June 10" in t), None)
            out.append(f"{token}|REPLACES|{hit}" if "changed to" in text and hit else f"{token}|NONE|")
        return "\n".join(out) + f"\nEND|{len(out)}\n"
    return "END|0\n"


RFP_PDF = pdf("Proposals are due June 10, 2026.", "The vendor must provide 24/7 support.")
ADD_PDF = pdf("The proposal due date is changed to June 24, 2026.", "Section 3.15 of the RFP is deleted.")


async def make_bid(tmp_path):
    bid = B.create(tmp_path, "Ulster", "deal-1")
    store = results.ResultStore(tmp_path)
    rfp = bid.add_document(RFP_PDF, "RFP.pdf")
    bid.update_document(rfp["no"], confirmed=True, issue_date="2026-07-01")
    add = bid.add_document(ADD_PDF, "ADD1.pdf")
    bid.update_document(add["no"], playbook="change-addendum", issue_number=1, issue_date="2026-08-01", confirmed=True)
    client = ScriptedClient(handler)
    await B.extract_document(bid, rfp["no"], client, store=store, cfg=FAST)
    steps = []
    saved = await B.extract_document(bid, add["no"], client, store=store, cfg=FAST, on_step=lambda *a: steps.append(a))
    return bid, store, client, saved, steps, rfp["no"], add["no"]


async def test_an_addendum_is_related_to_the_rfp_and_a_held_reference_becomes_a_q_fact(tmp_path):
    bid, store, client, saved, steps, rfp_no, add_no = await make_bid(tmp_path)
    rel = json.loads((saved.folder / "relations.json").read_text())
    assert rel["against"] == ["RFP"] and rel["playbook"] == "change-addendum@1" and rel["incomplete"] == []
    changed = next(r for r in rel["units"] if r["kind"] == "REPLACES")
    assert changed["targets"] == [{"doc_id": "RFP", "unit": "p1.1"}]
    assert [h["text"] for h in rel["held_refs"]] == ["Section 3.15"] and rel["ref_units"] == [rel["held_refs"][0]["unit"]]
    facts = saved.facts()
    [q] = [f for f in facts if f["category"] == "Q"]
    assert "Section 3.15" in q["text"] and "which was not found in the earlier documents" in q["text"] and q["from_held"] is True
    assert q["level"] == 1 and saved.report()["facts"] == len(facts) and saved.report()["by_category"]["Q"] == 1
    assert saved.report()["xref_conflicts"] == 0  # the reference was held, not written as a contradiction
    calls = saved.report()["relate_calls"]
    assert [c["name"] for c in calls] == ["RELATE1"] and calls[0]["usage"]["input_tokens"] > 0
    assert any(s[1] == "relate" and s[2] == "done" for s in steps)
    assert "calls" not in rel


async def test_the_rfp_itself_has_no_relations_and_the_bid_applies_the_stored_ones(tmp_path):
    bid, store, client, saved, steps, rfp_no, add_no = await make_bid(tmp_path)
    assert not (bid.root / bid.document(rfp_no)["run"] / "relations.json").exists()
    facts = B.build(bid)
    old = next(f for f in facts if f["doc_no"] == rfp_no and f["category"] == "D")
    new = next(f for f in facts if f["doc_no"] == add_no and f["category"] == "D")
    assert "replaced" in old["flags"] and old["replaced_by"] == new["fact_id"] and old["text"].startswith("Proposals are due June 10")
    assert old["relations"][0] == new["relations"][0] and old["relations"][0]["from"]["fact_id"] == new["fact_id"]
    assert json.loads((bid.folder / "conflicts.json").read_text()) == []
    assert bid.needs_relate() == []


async def test_a_notes_file_with_no_earlier_buyer_document_stores_empty_relations(tmp_path):
    bid = B.create(tmp_path, "Solo")
    d = bid.add_document(b"# Notes\n\nThe budget is fixed.\n", "n.md")
    bid.update_document(d["no"], confirmed=True, issue_date="2026-08-14")
    client = ScriptedClient(lambda r: "END|0\n" if task_name(r) != "RELATE" else pytest.fail("RELATE called"))
    saved = await B.extract_document(bid, d["no"], client, store=results.ResultStore(tmp_path), cfg=FAST)
    rel = json.loads((saved.folder / "relations.json").read_text())
    assert rel["against"] == [] and rel["units"] == [] and "RELATE" not in {task_name(r) for r in client.requests}
    assert saved.report()["relate_calls"] == []


async def test_a_document_added_before_an_extracted_addendum_makes_its_relations_stale(tmp_path):
    bid, store, client, saved, steps, rfp_no, add_no = await make_bid(tmp_path)
    contract = bid.add_document(pdf("Payment is due in 30 days.", "The vendor must insure."), "CONTRACT.pdf")
    bid.update_document(contract["no"], confirmed=True, issue_date="2026-06-01")  # sorts before the RFP
    await B.extract_document(bid, contract["no"], client, store=store, cfg=FAST)
    assert bid.needs_relate() == [add_no]
    assert len(B.build(bid)) > 0  # applies what is stored; does not crash
    n = len(client.requests)
    again = await B.extract_document(bid, add_no, client, store=store, cfg=FAST, relate_only=True)
    assert {task_name(r) for r in client.requests[n:]} == {"RELATE"}  # only RELATE ran
    rel = json.loads((again.folder / "relations.json").read_text())
    assert rel["against"] == ["CONTRACT", "RFP"] and bid.needs_relate() == []
    assert len([f for f in again.facts() if f.get("from_held")]) == 1  # the Q fact was replaced, not doubled
    assert len(again.report()["relate_calls"]) == 1 and bid.document(add_no)["status"] == "extracted"
    with pytest.raises(ValueError):
        await B.extract_document(bid, rfp_no, client, store=store, cfg=FAST, relate_only=True)  # the RFP has no RELATE


async def test_rejecting_a_relation_makes_the_fact_current_again_and_undo_restores_it(tmp_path):
    bid, store, client, saved, steps, rfp_no, add_no = await make_bid(tmp_path)
    B.build(bid)
    ws = Workspace(bid.folder / "facts.json")
    old = next(f for f in ws.state().facts if f["doc_no"] == rfp_no and f["category"] == "D")
    rid = old["relations"][0]["id"]
    assert "replaced" in old["flags"] and ws.is_bid() and ws.document() is None
    entry = ws.reject_relation(rid)
    assert entry["op"] == "reject_relation" and entry["fields"]["relation_id"] == rid
    after = ws.state().get(old["fact_id"])
    assert "replaced" not in after["flags"] and after["relations"] == [] and after["replaced_by"] == ""
    assert ws.corrections()[0]["description"].startswith("Rejected the relation REPLACES")
    with pytest.raises(NotFound):
        ws.reject_relation(rid)  # it is no longer on any fact
    ws.undo(entry["id"])
    assert "replaced" in ws.state().get(old["fact_id"])["flags"]
    ws.reject_relation(rid)
    ws.restore_relation(rid)
    assert "replaced" in ws.state().get(old["fact_id"])["flags"]
    with pytest.raises(NotFound):
        ws.restore_relation(rid)
    # a rebuild keeps the rejection while it is live
    ws.reject_relation(rid)
    B.build(bid)
    assert "replaced" not in ws.state().get(old["fact_id"])["flags"]


async def test_a_fact_added_to_a_bid_can_cite_a_unit_of_a_document(tmp_path):
    bid, store, client, saved, steps, rfp_no, add_no = await make_bid(tmp_path)
    B.build(bid)
    ws = Workspace(bid.folder / "facts.json")
    f = ws.add({"category": "D", "text": "Proposals are due June 24", "citation_ids": [f"d{add_no}:p1.1", "d9:p1.1", "p1.1"]})
    assert [(c["doc_id"], c["doc_no"], c["id"], c["level"]) for c in f["citations"]] == [("ADD1", add_no, "p1.1", 1)]
    assert f["unresolved_ids"] == ["d9:p1.1", "p1.1"] and f["doc_no"] == add_no and f["citations"][0]["visibility"] == "external"
    assert f["fact_id"] in {x["fact_id"] for x in ws.state().facts}


# --- asking again for the units left unanswered ---------------------------------------------


async def test_relate_only_asks_the_units_it_is_given_and_merges_with_the_stored_answers():
    rfp = tagged("RFP", ("p1.1", "sentence", "Proposals are due June 10, 2026."))
    add = tagged("ADD1", *[("p1.%d" % n, "sentence", f"Statement {n} about the due date June 10, 2026.") for n in range(1, 6)])
    pb = playbooks.load("change-addendum")
    earlier = [(1, rfp, [fact("RFP", "p1.1", "Due June 10, 2026")])]
    first = await relate.relate(add, 2, pb, [], earlier, ScriptedClient(lambda r: ""), FAST)  # nothing answered
    assert first["incomplete"] == ["p1.1", "p1.2", "p1.3", "p1.4", "p1.5"]
    seen = []

    def handler(req):
        units_in = [ln[1:].partition("] ")[0] for ln in req.task.splitlines() if ln.startswith("[d2:")]
        seen.append(units_in)
        return "\n".join(f"{u}|CONFIRMS|d1:p1.1" for u in units_in if u != "d2:p1.4") + f"\nEND|{len(units_in)}"

    second = await relate.relate(add, 2, pb, [], earlier, ScriptedClient(handler), FAST, only=first["incomplete"][:3], stored=first)
    assert seen[0] == ["d2:p1.1", "d2:p1.2", "d2:p1.3"] and len(seen) == 1
    assert [u["kind"] for u in second["units"]] == ["CONFIRMS"] * 3 + ["", ""] and second["incomplete"] == ["p1.4", "p1.5"]
    seen.clear()
    third = await relate.relate(add, 2, pb, [], earlier, ScriptedClient(handler), FAST, only=second["incomplete"], stored=second)
    assert seen == [["d2:p1.4", "d2:p1.5"], ["d2:p1.4"]]  # one re-ask for the unit the answer left out
    assert [u["kind"] for u in third["units"]] == ["CONFIRMS", "CONFIRMS", "CONFIRMS", "", "CONFIRMS"] and third["incomplete"] == ["p1.4"]
    assert third["units"][0] == second["units"][0] and [c["name"] for c in third["calls"]] == ["RELATE1", "RELATE1b"]


async def unanswered_bid(tmp_path):
    bid, store, client, saved, steps, rfp_no, add_no = await make_bid(tmp_path)
    path = saved.folder / "relations.json"
    rel = json.loads(path.read_text())
    changed = next(r for r in rel["units"] if r["kind"] == "REPLACES")
    changed.update(kind="", targets=[], votes=[])
    rel["incomplete"] = [changed["unit"]]
    path.write_text(json.dumps(rel))
    return bid, store, saved, add_no, changed["unit"]


async def test_a_document_asks_again_only_for_its_incomplete_units(tmp_path):
    bid, store, saved, add_no, unit = await unanswered_bid(tmp_path)
    assert bid.incomplete_relations() == {add_no: [unit]}
    client = ScriptedClient(handler)
    steps = []
    again = await B.extract_document(bid, add_no, client, store=store, cfg=FAST, relate_only=True, only_incomplete=True,
                                     on_step=lambda *a: steps.append(a))
    asked = [ln for r in client.requests for ln in r.task.splitlines() if ln.startswith("[d2:")]
    assert len(asked) == 1 and asked[0].startswith(f"[d{add_no}:{unit}]")
    rel = json.loads((again.folder / "relations.json").read_text())
    assert rel["incomplete"] == [] and next(r for r in rel["units"] if r["unit"] == unit)["kind"] == "REPLACES"
    assert bid.incomplete_relations() == {}
    assert [c["name"] for c in again.report()["relate_calls"]] == ["RELATE1", "RELATE1"]  # the new call is added
    assert steps[-1][1:] == ("relate", "done", "1 units asked again")


def test_bid_relate_asks_again_then_builds(tmp_path, monkeypatch, capsys):
    import asyncio

    from fact_extractor import cli
    from fact_extractor import llm as L
    from fact_extractor.web import consistency

    bid, store, saved, add_no, unit = asyncio.run(unanswered_bid(tmp_path))

    class Checker:
        async def _ask(self, new_text, related, instructions=None):
            return {f["fact_id"]: 0.05 for f in related}, None

    client = ScriptedClient(handler)
    monkeypatch.setattr(cli, "load_env", lambda *a: None)  # the repo's .env must not supply a key
    monkeypatch.setattr(L, "OpenAIClient", lambda model=None: client)
    monkeypatch.setattr(consistency, "ConsistencyChecker", Checker)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli.main(["bid", "relate", bid.bid_id, "--store", str(tmp_path)]) == 1  # no key: nothing is asked
    assert "OPENAI_API_KEY is not set" in capsys.readouterr().err and client.requests == []
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    assert cli.main(["bid", "relate", bid.bid_id, "--no", "99", "--store", str(tmp_path)]) == 1
    assert cli.main(["bid", "relate", bid.bid_id, "--store", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"d{add_no}: 1 units asked, 0 still unanswered" in out and "facts in the bid's list" in out
    assert bid.incomplete_relations() == {}
    assert (bid.folder / "facts.json").is_file()
    assert cli.main(["bid", "relate", bid.bid_id, "--store", str(tmp_path)]) == 0
    assert "no unit is waiting for an answer" in capsys.readouterr().out

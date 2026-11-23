"""The bid (bid.py): its manifest, issue order, speakers, readiness, extraction and fact list."""

import json

import pymupdf
import pytest
from conftest import ScriptedClient, task_name

from fact_extractor import bid as B
from fact_extractor import playbooks, results, units
from fact_extractor.web import runs

FAST = units.Config(backoff_base=0, warmup_timeout=1, brief=False, grouping=False)


def pdf(*lines: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for n, line in enumerate(lines):
        page.insert_text((72, 72 + 20 * n), line)
    return doc.tobytes()


@pytest.fixture
def bid(tmp_path):
    return B.create(tmp_path, "Ulster County actuarial", "deal-1")


def add(bid, name="x.pdf", data=None, **fields):
    doc = bid.add_document(data if data is not None else pdf(name, "text"), name)
    return bid.update_document(doc["no"], confirmed=True, **fields) if fields or True else doc


# --- the manifest ------------------------------------------------------------------------


def test_create_makes_a_unique_slug_and_an_atomic_manifest(tmp_path):
    a = B.create(tmp_path, "Ulster County actuarial", "d")
    b = B.create(tmp_path, "Ulster County actuarial")
    assert (a.bid_id, b.bid_id) == ("ulster-county-actuarial", "ulster-county-actuarial-2")
    m = a.manifest()
    assert m["deal_id"] == "d" and m["documents"] == [] and m["precedence"] is None and m["team"] == []
    assert b.manifest()["deal_id"] == b.bid_id
    assert not list(a.folder.glob(".*tmp"))
    assert B.create(tmp_path, "***").bid_id == "bid"


def test_add_stores_the_file_and_proposes(bid):
    data = pdf("ADDENDUM NO. 2", "Issued 2026-08-01")
    d = bid.add_document(data, "Addendum 2.pdf")
    assert (d["no"], d["doc_id"], d["pages"], d["status"], d["confirmed"]) == (1, "Addendum 2", 1, "uploaded", False)
    assert (bid.folder / d["file"]).read_bytes() == data and d["file"] == "files/1_Addendum_2.pdf"
    assert d["proposed"]["playbook"] == "change-addendum" and d["playbook"] == "change-addendum"
    assert (d["issue_number"], d["issue_date"], d["sha256"]) == (2, "2026-08-01", results.content_hash(data))
    assert d["speakers"] == [] and d["run"] == "" and d["previous"] is None


def test_doc_ids_are_unique_and_the_same_file_twice_is_refused(bid):
    a = bid.add_document(b"# One\n\nText.\n", "notes.md")
    b = bid.add_document(b"# Two\n\nText.\n", "notes.md")
    c = bid.add_document(b"# Three\n\nText.\n", "notes.txt")
    assert [a["doc_id"], b["doc_id"], c["doc_id"]] == ["notes", "notes-2", "notes-3"] and (b["no"], c["no"]) == (2, 3)
    with pytest.raises(ValueError, match="this file is already in the bid"):
        bid.add_document(b"# One\n\nText.\n", "other.md")
    assert len(bid.manifest()["documents"]) == 3


def test_update_validates(bid):
    a = bid.add_document(b"# One\n\nText.\n", "a.md")
    b = bid.add_document(b"# Two\n\nText.\n", "b.md")
    for bad in ({"playbook": "nope"}, {"issue_date": "08/01/2026"}, {"issue_date": "2026-13-01"}, {"issue_number": "x"},
                {"issue_number": True}, {"doc_id": "b"}, {"doc_id": " "}, {"previous": "ghost"}, {"colour": 1}):
        with pytest.raises(ValueError):
            bid.update_document(a["no"], **bad)
    d = bid.update_document(a["no"], issue_date="2026-08-01", issue_number="3", doc_id="first", confirmed=True)
    assert (d["issue_date"], d["issue_number"], d["doc_id"], d["status"]) == ("2026-08-01", 3, "first", "confirmed")
    assert bid.update_document(a["no"], issue_date=None)["issue_date"] is None
    assert bid.update_document(b["no"], previous="first")["previous"] == "first"


def test_remove_only_before_extraction(bid):
    d = bid.add_document(b"# One\n\nText.\n", "a.md")
    bid.remove_document(d["no"])
    assert bid.manifest()["documents"] == [] and not (bid.folder / d["file"]).exists()
    d = bid.add_document(b"# One\n\nText.\n", "a.md")
    bid._change(d["no"], lambda m, x: x.update(status="extracted", run="a/run_1"))
    with pytest.raises(ValueError):
        bid.remove_document(d["no"])
    with pytest.raises(ValueError):
        bid.update_document(d["no"], playbook="rfp")
    with pytest.raises(ValueError):
        bid.update_document(d["no"], doc_id="z")


# --- issue order -------------------------------------------------------------------------


def doc(no, playbook, date=None, number=None):
    return {"no": no, "doc_id": f"d{no}", "playbook": playbook, "issue_date": date, "issue_number": number}


def test_an_addendum_uploaded_first_still_sorts_after_the_rfp():
    m = {"documents": [doc(1, "change-addendum", "2026-08-01", 1), doc(2, "rfp", "2026-07-20")]}
    assert [d["no"] for d in B.issue_order(m)] == [2, 1]


def test_addendum_3_dated_before_addendum_2_still_applies_after_it():
    m = {"documents": [
        doc(1, "rfp", "2026-07-01"), doc(2, "change-addendum", "2026-08-10", 3), doc(3, "change-addendum", "2026-08-15", 2),
        doc(4, "call-transcript", "2026-08-12"),
    ]}
    assert [d["no"] for d in B.issue_order(m)] == [1, 3, 4, 2]  # the call keeps its place between the two slots
    assert B.doc_numbers(m) == {"d1": 1, "d2": 2, "d3": 3, "d4": 4}


def test_undated_documents():
    m = {"documents": [doc(1, "deal-notes"), doc(2, "rfp"), doc(3, "rfp", "2026-07-01")]}
    assert [d["no"] for d in B.issue_order(m)] == [2, 3, 1]


# --- speakers and readiness --------------------------------------------------------------


def test_speaker_proposals_team_list_beats_b_fact_beats_affiliation():
    info = {"speakers": [
        {"id": "1", "name": "Tom Okafor", "affiliation": "External"},
        {"id": "2", "name": "Dana Pike", "affiliation": "Internal"},
        {"id": "3", "name": "Raj Mehta", "affiliation": "Internal"},
        {"id": "4", "name": "Lee Ward", "affiliation": "External"},
        {"id": "5", "name": "+1 845-555-0142", "affiliation": "Unknown"},
    ]}
    got = B.propose_speakers(info, [{"name": "Tom Okafor"}, {"name": "Dana Pike"}], ["Questions go to Dana Pike, Purchasing."])
    assert [(s["id"], s["proposed"], s["why"]) for s in got] == [
        ("1", "ours", "team list"), ("2", "ours", "team list"), ("3", "ours", "Gong affiliation"),
        ("4", "buyer", "Gong affiliation"), ("5", "unknown", "none")]
    got = B.propose_speakers(info, [], ["Contact: Raj Mehta, Purchasing"])
    assert (got[2]["proposed"], got[2]["why"]) == ("buyer", "B fact")


def test_ready_lists_what_is_missing():
    assert B.ready({"confirmed": False, "playbook": "rfp"}) == ["type not confirmed"]
    assert B.ready({"confirmed": True, "playbook": "rfp"}) == []
    assert B.ready({"confirmed": True, "playbook": "change-addendum"}) == ["issue date missing", "issue number missing"]
    assert B.ready({"confirmed": True, "playbook": "reissued-rfp"}) == ["previous version not chosen"]
    assert B.ready({"confirmed": True, "playbook": "deal-notes"}) == ["issue date missing"]
    call = {"confirmed": True, "playbook": "call-transcript", "issue_date": "2026-08-01",
            "speakers": [{"side": ""}, {"side": "unknown"}], "speakers_confirmed": False}
    assert B.ready(call) == ["speakers not confirmed", "a speaker has no side"]
    call.update(speakers=[{"side": "buyer"}, {"side": "unknown"}], speakers_confirmed=True)
    assert B.ready(call) == []


# --- extracting one document -------------------------------------------------------------


def label_handler(rules: dict[str, str]):
    """Label a unit by the first keyword its line holds; state it in its own words."""

    def handler(req):
        kind = task_name(req)
        if kind not in ("LABEL", "STATE"):
            return "END|0\n"
        ids = [i.strip() for i in req.task.splitlines()[2].split(",")]
        lines = {ln[1:].partition("] ")[0]: ln.partition("] ")[2] for ln in req.document.splitlines() if ln.startswith("[")}
        out = []
        for i in ids:
            label = next((v for k, v in rules.items() if k in lines[i]), "-")
            out.append(f"{i}|{label if kind == 'LABEL' else (lines[i] if label != '-' else '-')}")
        return "\n".join(out) + f"\nEND|{len(ids)}\n"

    return handler


NOTES = b"# Deal notes\n\nExported 2026-08-14.\n\n## Money\n\nTheir budget is 90,000 dollars.\n\n- Chase the reference.\n"
CALL = (
    b"Meeting: Kickoff\nDate: 2026-08-12\n"
    b"[00:00:04] Dana Pike: The budget is fixed at 90,000 dollars.\n"
    b"[00:00:20] Tom Okafor: We plan a discount on the budget.\n"
    b"[00:00:31] Dana Pike: That would work for us.\n"
    b"[00:00:40] +1 845-555-0142: Maybe the budget grows.\n"
    b"[00:00:50] Tom Okafor: Noted.\n"
)
RULES = {"budget": "BUDGET", "work for us": "=", "Chase": "ACTION"}


async def test_notes_are_level_4(bid, tmp_path):
    d = add(bid, "deal.md", NOTES, issue_date="2026-08-14")
    steps = []
    client = ScriptedClient(label_handler(RULES))
    store = results.ResultStore(tmp_path)
    saved = await B.extract_document(bid, d["no"], client, store=store, cfg=FAST, on_step=lambda *a: steps.append(a))
    facts = saved.facts()
    assert {f["category"]: f["level"] for f in facts} == {"BUDGET": 4, "ACTION": 4}
    assert all(f["playbook"] == "deal-notes" for f in facts)
    assert saved.meta["playbook"] == "deal-notes@1" and saved.meta["source_name"] == "deal.md"
    assert results.load_document(saved.folder, "deal") is not None
    got = bid.document(d["no"])
    assert got["status"] == "extracted" and got["run"] == f"deal/{saved.folder.name}"
    assert [s[:3] for s in steps if s[1] == "extract"][-1] == (1, "extract", "done")
    assert FAST.votes == 3 and {r.system for r in client.requests if task_name(r) == "LABEL"} == {playbooks.load("deal-notes").system()}


async def test_a_stored_result_is_reused_without_a_model_call(bid, tmp_path):
    d = add(bid, "deal.md", NOTES, issue_date="2026-08-14")
    store = results.ResultStore(tmp_path)
    first = await B.extract_document(bid, d["no"], ScriptedClient(label_handler(RULES)), store=store, cfg=FAST)
    again = ScriptedClient(lambda r: pytest.fail("a model call"))
    second = await B.extract_document(bid, d["no"], again, store=store, cfg=FAST)
    assert second.folder == first.folder and again.requests == []


async def test_not_ready_and_failures(bid, tmp_path):
    d = bid.add_document(NOTES, "deal.md")
    store = results.ResultStore(tmp_path)
    with pytest.raises(ValueError, match="type not confirmed"):
        await B.extract_document(bid, d["no"], ScriptedClient(lambda r: "x"), store=store)
    bid.update_document(d["no"], confirmed=True, issue_date="2026-08-14")
    with pytest.raises(RuntimeError):
        await B.extract_document(bid, d["no"], ScriptedClient(lambda r: (_ for _ in ()).throw(RuntimeError("boom"))),
                                 store=store, cfg=FAST)
    got = bid.document(d["no"])
    assert got["status"] == "failed" and "boom" in got["error"] and got["run"] == ""


async def test_a_call_gets_levels_from_the_side_of_its_units(bid, tmp_path):
    d = bid.add_document(CALL, "call.txt")
    assert d["playbook"] == "call-transcript" and d["issue_date"] == "2026-08-12"
    names = [s["name"] for s in d["speakers"]]
    assert names == ["Dana Pike", "Tom Okafor", "+1 845-555-0142"]
    bid.update_document(d["no"], confirmed=True)
    assert B.ready(bid.document(d["no"])) == ["speakers not confirmed", "a speaker has no side"]
    bid.update_document(d["no"], speakers=[
        {"name": "Dana Pike", "side": "buyer"}, {"id": "Tom Okafor", "side": "ours"}, {"name": "+1 845-555-0142", "side": "unknown"}],
        speakers_confirmed=True)
    with pytest.raises(ValueError):
        bid.update_document(d["no"], speakers=[{"name": "Dana Pike", "side": "them"}])
    saved = await B.extract_document(bid, d["no"], ScriptedClient(label_handler(RULES)), store=results.ResultStore(tmp_path), cfg=FAST)
    by_text = {f["source_text"]: f for f in saved.facts()}
    buyer = by_text["The budget is fixed at 90,000 dollars."]
    ours_with_buyer = next(f for f in saved.facts() if "discount" in f["source_text"])
    unknown = by_text["Maybe the budget grows."]
    assert buyer["level"] == 2 and "both-sides" not in buyer["flags"]
    assert ours_with_buyer["level"] == 2 and "both-sides" in ours_with_buyer["flags"]
    assert ours_with_buyer["text"] == ours_with_buyer["source_text"] and ours_with_buyer["text_from"] == "rfp"
    assert {c["side"] for c in ours_with_buyer["citations"]} == {"ours", "buyer"}
    assert unknown["level"] == 3 and "unclear" in unknown["flags"]
    units_json = json.loads((saved.folder / "units.json").read_text())
    assert {u["side"] for u in units_json} == {"buyer", "ours", "unknown"}


def test_level_of_the_ours_only_fact_is_3():
    pb = playbooks.load("call-transcript")
    assert B.level_of(pb, ["ours"]) == (3, [])
    assert B.level_of(pb, ["unknown", "ours"]) == (3, [])
    assert B.level_of(pb, ["unknown", "buyer"]) == (2, [])
    assert B.level_of(pb, ["unknown"]) == (3, ["unclear"])
    assert B.level_of(playbooks.load("rfp"), []) == (1, [])


# --- the bid's fact list -----------------------------------------------------------------


async def make_bid(tmp_path):
    bid = B.create(tmp_path, "Ulster", "deal-1")
    store = results.ResultStore(tmp_path)
    rfp = bid.add_document(pdf("1. Scope", "The vendor must provide 24/7 support."), "RFP-1.pdf")
    bid.update_document(rfp["no"], confirmed=True, issue_date="2026-07-20")
    notes = add(bid, "deal.md", NOTES, issue_date="2026-08-14")
    call = bid.add_document(CALL, "call.txt")
    bid.update_document(call["no"], confirmed=True, speakers_confirmed=True, speakers=[
        {"name": "Dana Pike", "side": "buyer"}, {"name": "Tom Okafor", "side": "ours"}, {"name": "+1 845-555-0142", "side": "unknown"}])
    client = ScriptedClient(label_handler({**RULES, "must provide": "R"}))
    for no in (notes["no"], call["no"], rfp["no"]):  # not in issue order
        await B.extract_document(bid, no, client, store=store, cfg=FAST)
    return bid


async def test_build_writes_the_fact_list_in_issue_order(tmp_path):
    bid = await make_bid(tmp_path)
    facts = B.build(bid)
    assert [f["doc_no"] for f in facts][0] == 1 and {f["doc_no"] for f in facts} == {1, 2, 3}
    order = [f["doc_no"] for f in facts]
    assert order == sorted(order, key=[1, 3, 2].index)  # rfp (07-20), call (08-12), notes (08-14)
    rfp = next(f for f in facts if f["doc_no"] == 1)
    assert (rfp["level"], rfp["playbook"], rfp["relations"], rfp["replaced_by"], rfp["stale"]) == (1, "rfp", [], "", "")
    assert rfp["citations"][0]["doc_id"] == "RFP-1" and rfp["citations"][0]["visibility"] == "external"
    note = next(f for f in facts if f["doc_no"] == 2)
    assert (note["level"], note["citations"][0]["level"], note["citations"][0]["visibility"]) == (4, 4, "internal")
    call = [f for f in facts if f["doc_no"] == 3]
    assert {c["level"] for f in call for c in f["citations"]} == {2, 3}
    assert all(c["doc_no"] == f["doc_no"] for f in facts for c in f["citations"])
    assert json.loads((bid.folder / "facts.json").read_text()) == facts
    rep = json.loads((bid.folder / "report.json").read_text())
    assert rep["bid_id"] == "ulster" and rep["doc_id"] == "ulster" and rep["run_id"] == "bid" and rep["facts"] == len(facts)
    assert [(d["doc_no"], d["playbook"]) for d in rep["documents"]] == [(1, "rfp"), (3, "call-transcript"), (2, "deal-notes")]
    assert rep["pages"] == 1 and rep["summaries"] == {}
    assert B.build(bid) == facts  # deterministic
    assert not list(bid.folder.glob(".*tmp"))


async def test_a_bid_is_listed_once_as_a_bid_and_never_as_a_stored_result(tmp_path):
    empty = B.create(tmp_path, "Empty")
    assert B.build(empty) == [] and not (empty.folder / "facts.json").exists()
    bid = await make_bid(tmp_path)
    B.build(bid)
    assert not list(tmp_path.glob("_bids/**/meta.json"))
    refs = runs.find_runs(tmp_path)
    kinds = sorted((r.kind, r.label.split("/")[0]) for r in refs)
    assert kinds == [("bid", "_bids"), ("document", "RFP-1"), ("document", "call"), ("document", "deal")]
    ref = next(r for r in refs if r.kind == "bid")
    assert (ref.documents, ref.doc_id, ref.run_id) == (3, "ulster", "bid")
    assert {s.meta["doc_id"] for s in results.ResultStore(tmp_path)._all()} == {"RFP-1", "call", "deal"}
    listed = {b["bid_id"]: b for b in B.list_bids(tmp_path)}
    assert listed["empty"]["facts"] == 0 and listed["empty"]["run"] == "" and listed["empty"]["documents"] == 0
    assert listed["ulster"]["run"] == "_bids/ulster" and listed["ulster"]["documents"] == 3 and listed["ulster"]["facts"] > 0


async def test_the_web_loads_a_bid_as_a_run(tmp_path):
    bid = await make_bid(tmp_path)
    B.build(bid)
    run = runs.load_run(bid.folder / "facts.json")
    assert (run.pdf, run.source, run.doc_id, run.run_id, run.pages) == (None, None, "ulster", "bid", 1)
    shuffled = sorted(run.records, key=lambda r: (r["doc_no"] != 3, r["text"]))  # call first, as it appears here
    got = [r["doc_no"] for r in runs.document_order(shuffled)]
    assert got == sorted(got, key=[3, 1, 2].index)
    nos = [r["doc_no"] for r in runs.document_order(run.records)]
    assert nos == [r["doc_no"] for r in run.records]  # already in issue order and stays there


def test_document_order_without_doc_no_is_unchanged():
    recs = runs.normalize([
        {"category": "B", "text": "b", "citations": [{"id": "p2.1", "page": 2}]},
        {"category": "B", "text": "none", "citations": []},
        {"category": "B", "text": "a", "citations": [{"id": "p1.10", "page": 1}]},
        {"category": "B", "text": "c", "citations": [{"id": "p1.2", "page": 1}]},
    ])
    assert [r["text"] for r in runs.document_order(recs)] == ["c", "a", "b", "none"]
    recs[0]["doc_no"], recs[2]["doc_no"] = 5, 7
    assert [r["text"] for r in runs.document_order(recs)] == ["c", "none", "b", "a"]

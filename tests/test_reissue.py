"""Reissued RFPs (reissue.py): alignment, carried labels, the fact ID map and the bid's fact list."""

import json

import pymupdf
from conftest import ScriptedClient, task_name

from fact_extractor import bid as B
from fact_extractor import reissue, results, units
from fact_extractor.tagging import Heading, Page, Paragraph, tag_pages
from fact_extractor.web.workspace import Workspace

FAST = units.Config(backoff_base=0, warmup_timeout=1, brief=False, grouping=False, votes=1)
RULES = {"must provide": "R", "due": "D", "shall submit": "X"}


def pdf(*lines: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for n, line in enumerate(lines):
        page.insert_text((72, 72 + 20 * n), line)
    return doc.tobytes()


def handler(req):
    kind = task_name(req)
    if kind not in ("LABEL", "STATE"):
        return "END|0\n"
    ids = [i.strip() for i in req.task.splitlines()[2].split(",")]
    lines = {ln[1:].partition("] ")[0]: ln.partition("] ")[2] for ln in req.document.splitlines() if ln.startswith("[")}
    out = []
    for i in ids:
        label = next((v for k, v in RULES.items() if k in lines[i]), "-")
        out.append(f"{i}|{label if kind == 'LABEL' else (lines[i] if label != '-' else '-')}")
    return "\n".join(out) + f"\nEND|{len(ids)}\n"


def asked(client) -> list[str]:
    """The unit IDs of every LABEL request."""
    return [i.strip() for r in client.requests if task_name(r) == "LABEL" for i in r.task.splitlines()[2].split(",")]


def doc_of(*sentences: str):
    return tag_pages("d", [Page(1, "1", [Heading("1. Scope"), *(Paragraph.of(s) for s in sentences)])])


def test_a_repeated_sentence_pairs_in_sequence():
    a, b = "The vendor must provide support.", "Proposals are due March 3."
    old = doc_of(a, b, a)
    new = doc_of(a, "A new sentence is here.", b, a)
    ou, nu = list(old.anchors.values()), list(new.anchors.values())
    got = reissue.align(old, new)
    texts = [x.text for x in nu]
    pairs = {texts.index(a): None}
    first, second = [n for n, x in enumerate(nu) if x.text == a]
    assert got[nu[first].id] == [x.id for x in ou if x.text == a][0]
    assert got[nu[second].id] == [x.id for x in ou if x.text == a][1]
    assert nu[texts.index("A new sentence is here.")].id not in got and len(got) == len(nu) - 1 and pairs


def test_merge_maps_chains_reissues():
    assert reissue.merge_maps([{"A": "B"}, {"B": "C", "X": "Y"}]) == {"A": "C", "B": "C", "X": "Y"}


OLD = ("The vendor must provide 24/7 support.", "Proposals are due March 3, 2027.",
       "Bidders shall submit a bond.", "The vendor must provide training.")
NEW = ("The vendor must provide 24/7 support.", "Proposals are due March 9, 2027.",
       "Bidders shall submit a bond.")


async def two_versions(tmp_path):
    bid = B.create(tmp_path, "Ulster", "deal-1")
    store = results.ResultStore(tmp_path)
    old = bid.add_document(pdf(*OLD), "RFP-1.pdf")
    bid.update_document(old["no"], confirmed=True, issue_date="2026-07-20")
    await B.extract_document(bid, old["no"], ScriptedClient(handler), store=store, cfg=FAST)
    return bid, store, old


async def reissue_it(bid, store, old, lines=NEW, client=None):
    new = bid.add_document(pdf(*lines), "RFP-1-reissued.pdf")
    bid.update_document(new["no"], confirmed=True, playbook="reissued-rfp", previous=old["doc_id"], issue_date="2026-08-20")
    client = client or ScriptedClient(handler)
    saved = await B.extract_document(bid, new["no"], client, store=store, cfg=FAST)
    return new, saved, client


async def test_a_changed_sentence_is_labelled_again_and_its_neighbours_are_not(tmp_path):
    bid, store, old = await two_versions(tmp_path)
    new, saved, client = await reissue_it(bid, store, old)
    a = json.loads((saved.folder / "alignment.json").read_text())
    nu = results.load_document(saved.folder, new["doc_id"])
    changed = [nu.anchors[u].text for u in a["changed"]]
    assert changed == ["Proposals are due March 9, 2027."] and a["new"] == []
    old_doc = results.load_document(bid.root / bid.document(old["no"])["run"], old["doc_id"])
    assert [old_doc.anchors[u].text for u in a["removed"]] == ["The vendor must provide training."]
    assert asked(client) == a["changed"]  # only the changed unit went to LABEL
    assert not [r for r in client.requests if task_name(r) == "RELATE"]
    facts = {f["source_text"]: f for f in saved.facts()}
    assert facts["Proposals are due March 9, 2027."]["category"] == "D"
    assert facts["The vendor must provide 24/7 support."]["text_from"] == "model"
    assert len(a["facts"]) == 2 and saved.report()["reissue"]["changed"] == 1


async def test_nothing_changed_makes_no_label_call(tmp_path):
    bid, store, old = await two_versions(tmp_path)
    client = ScriptedClient(lambda r: "END|0\n")
    _, saved, client = await reissue_it(bid, store, old, lines=OLD, client=client)
    assert asked(client) == [] and not [r for r in client.requests if task_name(r) in ("LABEL", "STATE")]
    assert len(saved.facts()) == 4 and len(json.loads((saved.folder / "alignment.json").read_text())["facts"]) == 4


async def test_the_bid_drops_carried_facts_and_flags_the_rest(tmp_path):
    bid, store, old = await two_versions(tmp_path)
    new, saved, _ = await reissue_it(bid, store, old)
    facts = B.build(bid)
    by_text = {f["source_text"]: f for f in facts}
    assert [f["doc_id"] for f in facts].count(old["doc_id"]) == 2
    mine = [f for f in facts if f["doc_id"] == old["doc_id"]]
    assert {f["source_text"] for f in mine} == {"Proposals are due March 3, 2027.", "The vendor must provide training."}
    assert all("replaced" in f["flags"] and f["replaced_by"] == "" and f["stale"] == "not in the reissued RFP" for f in mine)
    assert by_text["Bidders shall submit a bond."]["doc_id"] == new["doc_id"]
    rep = json.loads((bid.folder / "report.json").read_text())
    assert rep["reissues"][0]["changed"] == 1 and rep["reissues"][0]["removed"] == 1


async def test_a_user_edit_on_an_old_fact_shows_on_the_new_fact(tmp_path):
    bid, store, old = await two_versions(tmp_path)
    B.build(bid)
    ws = Workspace(bid.folder / "facts.json")
    before = next(f for f in ws.state().facts if f["source_text"] == "Bidders shall submit a bond.")
    ws.edit(before["fact_id"], {"text": "A bid bond is required."})
    log_before = (ws.dir / "corrections.jsonl").read_text()
    new, saved, _ = await reissue_it(bid, store, old)
    B.build(bid)
    ws = Workspace(bid.folder / "facts.json")
    got = next(f for f in ws.state().facts if f["source_text"] == "Bidders shall submit a bond.")
    assert got["doc_id"] == new["doc_id"] and got["fact_id"] != before["fact_id"]
    assert got["text"] == "A bid bond is required." and got["edited"]
    assert (ws.dir / "corrections.jsonl").read_text() == log_before  # the log file is not rewritten
    assert reissue.bid_map(bid.folder)[before["fact_id"]] == got["fact_id"]


def test_map_entry_follows_raise_fields_and_option_changes():
    e = {"op": "raise", "fact_id": None, "fields": {"fact_ids": ["a", "z"], "options": [{"changes": [{"fact_id": "a"}]}]}}
    got = reissue.map_entry(e, {"a": "b"})
    assert got["fields"]["fact_ids"] == ["b", "z"] and got["fields"]["options"][0]["changes"][0]["fact_id"] == "b"
    assert e["fields"]["fact_ids"] == ["a", "z"]


async def test_a_continuation_whose_coded_unit_changed_is_labelled_again(tmp_path):
    RULES["Further"] = "="
    try:
        bid = B.create(tmp_path, "Ulster", "deal-1")
        store = results.ResultStore(tmp_path)
        old = bid.add_document(pdf("The vendor must provide support.", "Further, the support is remote.", "Bidders shall submit a bond."), "A.pdf")
        bid.update_document(old["no"], confirmed=True, issue_date="2026-07-20")
        await B.extract_document(bid, old["no"], ScriptedClient(handler), store=store, cfg=FAST)
        new, saved, client = await reissue_it(
            bid, store, old, lines=("The vendor must provide onsite support.", "Further, the support is remote.", "Bidders shall submit a bond."))
        a = json.loads((saved.folder / "alignment.json").read_text())
        assert asked(client) == ["p1.1", "p1.2"] and list(a["facts"]) and len(a["facts"]) == 1  # only the bond fact is carried
    finally:
        RULES.pop("Further")

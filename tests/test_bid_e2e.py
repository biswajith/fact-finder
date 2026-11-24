"""A whole bid, end to end, in the order a user does it. No real model: one ScriptedClient answers
every call kind and a fake checker answers the pair check.

The documents are made up here: an RFP and a change addendum (real PDFs built with pymupdf), a
call transcript in the Gong shape and deal notes. `build_bid` is also what the demo script of a
developer imports to look at the same bid in the web UI."""

import csv
import io
import json

import pymupdf
import pytest
from conftest import ScriptedClient, task_name

from fact_extractor import bid as B
from fact_extractor import classify, cutters, playbooks, results, speakers, units
from fact_extractor.web import runs
from fact_extractor.web.workspace import Workspace

CFG = units.Config(backoff_base=0, warmup_timeout=1)

# --- the made-up documents ----------------------------------------------------------------


def make_pdf(*pages: list[tuple[str, str]]) -> bytes:
    """A PDF from pages of ("h" heading | "p" paragraph, text) blocks: headings bold and larger."""
    doc = pymupdf.open()
    for blocks in pages:
        page = doc.new_page()
        y = 72.0
        for kind, text in blocks:
            height = 30.0 if kind == "h" else 16.0 * (len(text) // 80 + 1) + 8
            page.insert_textbox(
                pymupdf.Rect(72, y, 540, y + height), text,
                fontsize=15 if kind == "h" else 11, fontname="hebo" if kind == "h" else "helv",
            )
            y += height + 6
    return doc.tobytes()


RFP_PDF = make_pdf(
    [("h", "1.0 Schedule"),
     ("p", "Proposals are due June 10, 2027 at 2:00 PM Eastern. A site visit will be held on June 10, 2027 at 9:00 AM.")],
    [("h", "2.0 Submission"),
     ("p", "Proposals must be delivered to the Purchasing Office by June 10, 2027. Submit one signed original and five copies."),
     ("h", "2.1 Format of Proposals"),
     ("p", "Proposals shall not exceed 30 pages. Proposals must use 11 point type or larger.")],
    [("h", "3.0 Late Proposals"),
     ("p", "Proposals received after June 10, 2027 will not be opened.")],
)
ADDENDUM_PDF = make_pdf(
    [("h", "Addendum No. 1"),
     ("p", "Issued May 20, 2027."),
     ("p", "The proposal due date is changed to June 24, 2027 at 2:00 PM Eastern. "
           "Section 2.1, Format of Proposals, is replaced in full by the following.")],
    [("h", "2.1 Format of Proposals"),
     ("p", "Proposals shall not exceed 40 pages. Proposals must use 11 point type or larger.")],
)


def gong(*turns: tuple[str, str]) -> bytes:
    """A Gong export of one call; each turn is (speaker ID, text)."""
    parties = [
        ("s1", "Dana Pike", "External"), ("s2", "Raj Mehta", "External"),
        ("s3", "Tom Okafor", "Internal"), ("s4", "Lena Voss", "Internal"),
    ]
    return json.dumps({
        "extensive": {"calls": [{"metaData": {"title": "Capture call", "started": "2027-05-27T14:00:00Z"}, "parties": [
            {"speakerId": sid, "name": name, "affiliation": aff} for sid, name, aff in parties]}]},
        "transcript": {"callTranscripts": [{"transcript": [
            {"speakerId": sid, "topic": "", "sentences": [{"start": 6000 * n, "text": text}]}
            for n, (sid, text) in enumerate(turns, 1)]}]},
    }).encode()


CALL = gong(
    ("s3", "Thanks for making the time today."),
    ("s1", "Just to confirm, proposals are now due June 24, 2027 at 2:00 PM Eastern."),
    ("s3", "Is the contract budget capped at 90,000 dollars?"),
    ("s2", "Yes."),
    ("s1", "I think hand delivery to the clerk's office would probably be fine as well, but do not hold me to that."),
    ("s4", "We will send the list of questions on Friday."),
)
NOTES = (
    b"# Deal notes\n\nExported 2027-06-01.\n\n## Money\n\nTheir budget is probably around 85,000 dollars, my guess.\n\n"
    b"## To do\n\n- Send the reference list to Dana by Friday.\n"
)

# --- the scripted model --------------------------------------------------------------------

# the first key found in a unit is its label (and flags); a unit with none states no point
LABELS = [
    ("are due June 10", "D"), ("site visit", "D"), ("delivered to the Purchasing", "S"), ("signed original", "S"),
    ("shall not exceed", "S"), ("11 point", "S"), ("after June 10", "X"), ("changed to June 24", "D"),
    ("is replaced in full", "S"), ("now due June 24", "D"), ("budget capped", "BUDGET"), ("Yes.", "="),
    ("hand delivery", "S|tentative"), ("budget is probably", "BUDGET|tentative"), ("Send the reference list", "ACTION"),
]


def unit_lines(req) -> dict[str, str]:
    return {ln[1:].partition("] ")[0]: ln.partition("] ")[2] for ln in req.document.splitlines() if ln.startswith("[")}


def label_or_state(req) -> str:
    kind = task_name(req)
    ids = [i.strip() for i in req.task.splitlines()[2].split(",")]
    lines = unit_lines(req)
    out = []
    for i in ids:
        label, _, flags = next((v for k, v in LABELS if k in lines[i]), "-").partition("|")
        out.append(f"{i}|{label}|{flags}" if kind == "LABEL" else f"{i}|{lines[i] if label != '-' else '-'}")
    return "\n".join(out) + f"\nEND|{len(ids)}\n"


def xref(req) -> str:
    """The addendum names a section; its own heading is the target."""
    lines = unit_lines(req)
    heading = next((i for i, t in lines.items() if t == "2.1 Format of Proposals"), "none")
    for i, t in lines.items():
        if "Section 2.1" in t:
            return f"REF|{i}|Section 2.1|{heading}|section|\nEND|1\n"
    return "END|0\n"


def relate(req) -> str:
    """Answer from the candidates shown under each unit, as a model reading them would."""
    found: list[tuple[str, str, list[tuple[str, str]]]] = []
    for ln in req.task.splitlines():
        if ln.startswith("[d"):
            found.append((ln[1:].partition("] ")[0], ln.partition("] ")[2], []))
        elif ln.startswith("  > ["):
            found[-1][2].append((ln[5:].partition("]")[0], ln.partition("] ")[2]))

    def pick(cands, fragment: str) -> str:
        return next((tok for tok, text in cands if fragment in text), "")

    out = []
    for token, text, cands in found:
        if "changed to June 24" in text:
            out.append(f"{token}|REPLACES|{pick(cands, 'are due June 10')}")
        elif "is replaced in full" in text:
            out.append(f"{token}|REPLACES|{pick(cands, '(heading) 2.1 Format')}")
        elif text.startswith("Proposals must use 11 point"):
            out.append(f"{token}|CONFIRMS|{pick(cands, '11 point')}")
        elif "shall not exceed 40" in text:
            out.append(f"{token}|ADDS|")
        elif "now due June 24" in text:
            out.append(f"{token}|CONFIRMS|{pick(cands, 'changed to June 24')}")
        elif "hand delivery" in text:
            out.append(f"{token}|DISAGREES|{pick(cands, 'delivered to the Purchasing')}")
        else:
            out.append(f"{token}|NONE|")
    return "\n".join(out) + f"\nEND|{len(out)}\n"


def group(req) -> str:
    """The restated rule is one point; nothing else is."""
    same = [ln.split("|")[0] for ln in req.task.splitlines() if "|" in ln and "11 point" in ln]
    return f"SAME|{','.join(same)}\nEND|1" if len(same) == 2 else "END|0"


def classify_answer(req) -> str:
    if "Addendum No. 1" in req.document:
        return "change-addendum|1|2027-05-20"
    if "Exported" in req.document:
        return "deal-notes|-|2027-06-01"
    return "call-transcript|-|2027-05-27" if "Dana Pike" in req.document else "rfp|-|-"


def who(req) -> str:
    """Who speaks each line of the Gong JSON, read as a model would: a `speakerId: sN` line opens that
    party's turn (the party lines name them); the party lines themselves are no one's."""
    import re

    names = dict(re.findall(r"speakerId: (s\d); name: ([^;\n]+)", req.document))
    lines = req.document.split("\nLINES\n", 1)[1].splitlines()
    before = req.document.split("\nLINES\n", 1)[0]
    last = (re.findall(r"\] speakerId: (s\d)$", before, re.M) or ["-"])[-1]
    out = []
    for ln in lines:
        i, _, text = ln.partition("] ")
        if m := re.fullmatch(r"speakerId: (s\d)", text):
            last = m.group(1)
        out.append(f"{i.lstrip('[')}|{'-' if 'name:' in text or last == '-' else names[last]}")
    return "\n".join(out) + f"\nEND|{len(out)}\n"


def sides(req) -> str:
    """Each party's side from the affiliation the call system wrote next to its name."""
    import re

    aff = dict(re.findall(r"name: ([^;\n]+); affiliation: (\w+)", req.document))
    people = re.findall(r"^([^|\n]+?) \| ", req.document.split("ATTENDEES", 1)[1].split("\n\n")[0], re.M)[1:]
    out = [f"{p}|{'BUYER' if aff.get(p) == 'External' else 'OURS'}|-|-|affiliation" for p in people]
    return "\n".join(out) + f"\nEND|{len(out)}\n"


HANDLERS = {
    "LABEL": label_or_state, "STATE": label_or_state, "CHECK": lambda r: "END|0\n", "XREF": xref, "RELATE": relate,
    "GROUP": group, "BRIEF": lambda r: "END|0\n", "CLASSIFY": classify_answer, "WHO": who, "SPEAKERS": sides,
}


def handler(req):
    return HANDLERS[task_name(req)](req)


class FakeChecker:
    """The pair check: the probability is the first of `answers` whose key is in the existing fact's
    text, 0.05 otherwise. Low for the site visit, which shares the old date but is another event. The
    second question (`instructions` given: does a fact rest on the changed value?) is answered low for all."""

    ANSWERS = {"after June 10": 0.95, "Purchasing Office": 0.93, "site visit": 0.1}

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], str | None]] = []

    async def _ask(self, new_text, related, instructions=None):
        self.calls.append((new_text, [f["fact_id"] for f in related], instructions))
        if instructions is not None:
            return {f["fact_id"]: 0.05 for f in related}, None
        return {f["fact_id"]: next((p for k, p in self.ANSWERS.items() if k in f["text"]), 0.05) for f in related}, None


# --- the user's steps -------------------------------------------------------------------------


async def build_bid(root, client: ScriptedClient, checker, name: str = "Ulster County actuarial") -> tuple[B.Bid, results.ResultStore]:
    """Create the bid and drive the functions in the order a user does: add the files (the addendum
    first), let the model propose each type, confirm, name the team and the speakers, extract each
    document in issue order, then settle the bid."""
    bid = B.create(root, name, "deal-ulster")
    store = results.ResultStore(root)
    files = [("Addendum 1.pdf", ADDENDUM_PDF), ("RFP-2027-04.pdf", RFP_PDF), ("capture call.json", CALL), ("deal notes.md", NOTES)]
    for file_name, data in files:
        doc = bid.add_document(data, file_name)
        start = cutters.plain_text(data, file_name, classify.FIRST_WORDS, 5)
        got = await classify.by_model(file_name, start, client, rules=doc["proposed"])
        if got is not None:
            bid.set_proposal(doc["no"], got)
        if playbooks.load(bid.document(doc["no"])["playbook"]).spoken:  # as the web does at upload
            await speakers.read_voices(bid, doc["no"], client)
    with bid.lock:  # as the web's PATCH does
        m = bid.manifest()
        m["team"] = [{"name": "Tom Okafor"}, {"name": "Lena Voss"}]
        bid.save(m)
    nos = {d["doc_id"]: d["no"] for d in bid.manifest()["documents"]}
    bid.update_document(nos["RFP-2027-04"], confirmed=True, issue_date="2027-05-03")
    bid.update_document(nos["Addendum 1"], confirmed=True)
    bid.update_document(nos["deal notes"], confirmed=True)
    call = await speakers.suggest(bid, nos["capture call"], client)
    bid.update_document(nos["capture call"], confirmed=True, speakers_confirmed=True, speakers=[
        {"id": s["id"], "side": s["proposed"]} for s in call["speakers"]])
    for d in B.issue_order(bid.manifest()):
        await B.extract_document(bid, d["no"], client, store=store, cfg=CFG)
    await B.settle(bid, client, checker, CFG)
    return bid, store


# --- the test --------------------------------------------------------------------------------------


def by_text(facts, fragment: str, doc_no: int | None = None) -> dict:
    [f] = [f for f in facts if fragment in f["text"] and (doc_no is None or f["doc_no"] == doc_no)]
    return f


def the_conflict(state, reason: str, fact_id: str) -> dict:
    [c] = [c for c in state.conflicts if c.get("reason") == reason and c["fact_ids"][0] == fact_id]
    return c


async def test_a_bid_of_four_documents_end_to_end(tmp_path):
    client, checker = ScriptedClient(handler), FakeChecker()
    bid, store = await build_bid(tmp_path, client, checker)
    m = bid.manifest()

    # document numbers are upload numbers; issue order is by date and number
    assert {d["doc_id"]: d["no"] for d in m["documents"]} == {"Addendum 1": 1, "RFP-2027-04": 2, "capture call": 3, "deal notes": 4}
    assert [d["doc_id"] for d in B.issue_order(m)] == ["RFP-2027-04", "Addendum 1", "capture call", "deal notes"]
    by_doc = {d["doc_id"]: d for d in m["documents"]}
    assert by_doc["Addendum 1"]["proposed"]["by"] == "model" and by_doc["Addendum 1"]["playbook"] == "change-addendum"
    assert (by_doc["Addendum 1"]["issue_number"], by_doc["Addendum 1"]["issue_date"]) == (1, "2027-05-20")
    assert all(d["status"] == "extracted" and d["run"] for d in m["documents"])
    assert {s["name"]: s["proposed"] for s in by_doc["capture call"]["speakers"]} == {
        "Tom Okafor": "ours", "Lena Voss": "ours", "Dana Pike": "buyer", "Raj Mehta": "buyer"}

    facts = json.loads((bid.folder / "facts.json").read_text())
    assert [f["doc_no"] for f in facts] == sorted((f["doc_no"] for f in facts), key=[2, 1, 3, 4].index)
    rfp = lambda frag: by_text(facts, frag, 2)  # noqa: E731
    due_old, visit = rfp("are due June 10"), rfp("site visit")
    delivery, late = rfp("delivered to the Purchasing"), rfp("after June 10")
    pages_old, font_old = rfp("shall not exceed 30"), rfp("11 point")
    due_new = by_text(facts, "changed to June 24", 1)
    replace_section = by_text(facts, "is replaced in full", 1)
    pages_new, font_new = by_text(facts, "shall not exceed 40", 1), by_text(facts, "11 point", 1)
    confirmed = by_text(facts, "now due June 24", 3)
    hedged = by_text(facts, "hand delivery", 3)
    asked = next(f for f in facts if f["doc_no"] == 3 and f["category"] == "BUDGET")
    guess = next(f for f in facts if f["doc_no"] == 4 and f["category"] == "BUDGET")
    todo = next(f for f in facts if f["doc_no"] == 4 and f["category"] == "ACTION")

    # levels, and each citation's document and visibility
    assert {f["level"] for f in facts if f["doc_no"] in (1, 2)} == {1}
    assert (confirmed["level"], hedged["level"], asked["level"], guess["level"], todo["level"]) == (2, 2, 2, 4, 4)
    for f in facts:
        for c in f["citations"]:
            assert c["doc_no"] == f["doc_no"] and c["doc_id"] == f["doc_id"]
            assert c["visibility"] == ("external" if f["doc_no"] in (1, 2) else "internal")
    assert {c["level"] for c in asked["citations"]} == {2, 3} and {c["side"] for c in asked["citations"]} == {"buyer", "ours"}
    assert "both-sides" in asked["flags"] and asked["text_from"] == "rfp" and asked["text"] == asked["source_text"]
    assert "Yes." in asked["text"] and "90,000" in asked["text"]
    assert "tentative" in hedged["flags"] and "tentative" in guess["flags"] and "both-sides" not in confirmed["flags"]

    # the new due date replaces the old one, with a relation on both ends
    assert "replaced" in due_old["flags"] and due_old["replaced_by"] == due_new["fact_id"] and "replaced" not in due_new["flags"]
    [rel_old], [rel_new] = [r for r in due_old["relations"] if r["kind"] == "REPLACES"], [r for r in due_new["relations"] if r["kind"] == "REPLACES"]
    assert rel_old == rel_new and rel_old["from"]["fact_id"] == due_new["fact_id"] and rel_old["to"]["fact_id"] == due_old["fact_id"]
    assert (rel_old["from"]["doc_id"], rel_old["to"]["doc_id"], rel_old["rejected"]) == ("Addendum 1", "RFP-2027-04", False)
    assert [r["kind"] for r in confirmed["relations"]] == ["CONFIRMS"] and confirmed["replaced_by"] == ""

    # a section replaced by its heading: every fact under it is replaced; the ones around it are not
    for old in (pages_old, font_old):
        assert "replaced" in old["flags"] and old["replaced_by"] == replace_section["fact_id"]
    for kept in (visit, delivery, late, pages_new, font_new, replace_section):
        assert "replaced" not in kept["flags"]

    # the site visit shares the old date but is another event: the check answered low, so it is untouched
    state = Workspace(bid.folder / "facts.json").state()
    assert not any(visit["fact_id"] in c["fact_ids"] for c in state.conflicts)
    assert visit["replaced_by"] == "" and visit["text"] == "A site visit will be held on June 10, 2027 at 9:00 AM."
    pairs = json.loads((bid.folder / "pairs.json").read_text())
    assert pairs and all(a["skipped"] == "" for a in pairs.values())
    assert any(a["probability"] == 0.1 for a in pairs.values())  # the site visit was asked about, and answered low

    # the delivery deadline and the late-proposals rule still state the old date: a conflict each, the edit first
    for old, new_text in ((delivery, "Proposals must be delivered to the Purchasing Office by June 24, 2027."),
                          (late, "Proposals received after June 24, 2027 will not be opened.")):
        c = the_conflict(state, "old value elsewhere", old["fact_id"])
        assert c["kind"] == "document" and c["status"] == "open" and c["doc_id"] == "Addendum 1"
        assert c["options"][0]["label"] == "Update to June 24, 2027"
        assert c["options"][0]["changes"] == [{"op": "edit", "fact_id": old["fact_id"], "fields": {"text": new_text}}]
    assert not any(c.get("reason") == "old value elsewhere" and c["fact_ids"][0] == visit["fact_id"] for c in state.conflicts)

    # the hedged buyer remark on the call disagrees with the RFP: a conflict, and nothing is replaced
    c = the_conflict(state, "levels disagree", delivery["fact_id"])
    assert c["status"] == "open" and set(c["fact_ids"]) == {delivery["fact_id"], hedged["fact_id"]} and c["options"][-1]["question"] is True
    assert [r["kind"] for r in hedged["relations"]] == ["DISAGREES"] and hedged["replaced_by"] == ""
    assert "replaced" not in delivery["flags"] and "replaced" not in hedged["flags"]
    assert {f["fact_id"] for f in facts if "replaced" in f["flags"]} == {due_old["fact_id"], pages_old["fact_id"], font_old["fact_id"]}

    # resolving the edit option changes the fact's text; reopening takes it back
    ws = Workspace(bid.folder / "facts.json")
    cid = the_conflict(state, "old value elsewhere", delivery["fact_id"])["id"]
    ws.resolve(cid, 0)
    assert ws.state().get(delivery["fact_id"])["text"] == "Proposals must be delivered to the Purchasing Office by June 24, 2027."
    assert ws.state().conflict(cid)["status"] == "resolved" and ws.state().get(delivery["fact_id"])["edited"]
    ws.reopen(cid)
    assert ws.state().get(delivery["fact_id"])["text"] == delivery["text"] and ws.state().conflict(cid)["status"] == "open"

    # rejecting the due-date relation makes the old fact current; undo brings the replacement back
    rid = rel_old["id"]
    entry = ws.reject_relation(rid)
    back = ws.state().get(due_old["fact_id"])
    assert "replaced" not in back["flags"] and back["replaced_by"] == "" and back["relations"] == []
    assert not [c for c in ws.state().conflicts if c.get("reason") == "old value elsewhere"]  # nothing changed the date any more
    assert [r["kind"] for r in ws.state().get(due_new["fact_id"])["relations"]] == ["CONFIRMS"]  # the call still confirms it
    ws.undo(entry["id"])
    again = ws.state().get(due_old["fact_id"])
    assert "replaced" in again["flags"] and again["replaced_by"] == due_new["fact_id"]
    assert len([c for c in ws.state().conflicts if c.get("reason") == "old value elsewhere" and c["status"] == "open"]) == 2
    assert rid in [r["id"] for r in ws.state().get(due_new["fact_id"])["relations"]]

    # the restated rule is one "same" group, shown under the addendum's fact
    assert font_old["group_id"] == font_new["group_id"] != "" and font_new["group_kind"] == "same"
    shown = [it for it in runs.items(ws.state().visible()) if it.kind == "same"]
    assert len(shown) == 1 and shown[0].first["fact_id"] == font_new["fact_id"]
    assert [f["fact_id"] for f in shown[0].facts] == [font_new["fact_id"], font_old["fact_id"]]
    assert {f["doc_no"] for f in facts if f["group_id"] and f["group_kind"] == "same"} == {1, 2}

    # the CSV for the buyer has no citation from the call or the notes, and no internal-only fact
    rows = list(csv.DictReader(io.StringIO(runs.to_csv(runs.external_view(ws.state().visible()), bid=True).decode("utf-8-sig"))))
    assert rows and {r["document"] for r in rows} == {"RFP-2027-04", "Addendum 1"}
    assert {r["visibility"] for r in rows} == {"external"}
    texts = " ".join(r["text"] + r["source_text"] for r in rows)
    for internal in ("Yes.", "capped", "hand delivery", "85,000", "reference list", "now due June 24"):
        assert internal not in texts
    assert len(rows) < len(ws.state().visible())
    full = list(csv.DictReader(io.StringIO(runs.to_csv(ws.state().visible(), bid=True).decode("utf-8-sig"))))
    assert {r["document"] for r in full} == {"RFP-2027-04", "Addendum 1", "capture call", "deal notes"}

    # a second settle asks the model nothing, and changes nothing
    before_requests, before_checks = len(client.requests), len(checker.calls)
    again_facts = await B.settle(bid, client, checker, CFG)
    assert len(client.requests) == before_requests and len(checker.calls) == before_checks
    assert again_facts == json.loads((bid.folder / "facts.json").read_text())

    # every call kind was used, and the playbooks' own prompts went with them
    assert {task_name(r) for r in client.requests} == set(HANDLERS)
    assert {r.system for r in client.requests if task_name(r) == "RELATE"} == {
        relate_system(playbooks.load(p)) for p in ("change-addendum", "call-transcript", "deal-notes")}


def relate_system(pb) -> str:
    from fact_extractor import relate as R

    return R.system(pb.relations)

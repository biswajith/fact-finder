"""The routes for bids (WP7), through FastAPI's ASGI interface. Offline: models are scripted."""

import asyncio
import csv
import io
import json
import threading

import pymupdf
import pytest
from conftest import ScriptedClient, task_name

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import httpx
from test_bid_e2e import sides, who
from test_web_agent import ScriptedChat
from test_web_summaries import Scripted

from fact_extractor import bid as B
from fact_extractor.web import runs as R
from fact_extractor.web import server
from fact_extractor.web.server import create_app


def pdf(*paras: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for n, p in enumerate(paras):
        page.insert_text((72, 72 + 60 * n), p)
    return doc.tobytes()


RFP = pdf("Proposals are due June 10, 2026.", "The vendor must provide 24/7 support.")
ADDENDUM = pdf("The proposal due date is changed to June 24, 2026.")
NOTES = b"# Deal notes\n\nExported 2026-08-14.\n\n## Money\n\nTheir budget is 90,000 dollars.\n\n- Chase the reference.\n"


def gong(*turns: tuple[str, str]) -> bytes:
    return json.dumps({
        "extensive": {"calls": [{"metaData": {"title": "Kickoff", "started": "2026-08-12T10:00:00Z"}, "parties": [
            {"speakerId": "s1", "name": "Dana Pike", "affiliation": "External"},
            {"speakerId": "s2", "name": "Tom Okafor", "affiliation": "Internal"}]}]},
        "transcript": {"callTranscripts": [{"transcript": [
            {"speakerId": sid, "topic": "", "sentences": [{"start": 4000 * n, "text": text}]} for n, (sid, text) in enumerate(turns, 1)]}]},
    }).encode()


CALL = gong(("s1", "The budget is fixed at 90,000 dollars."), ("s2", "We plan a discount on the budget."))


def handler(req):
    """Label a unit by its first keyword; answer RELATE from the candidates shown."""
    kind = task_name(req)
    if kind in ("LABEL", "STATE"):
        ids = [i.strip() for i in req.task.splitlines()[2].split(",")]
        lines = {ln[1:].partition("] ")[0]: ln.partition("] ")[2] for ln in req.document.splitlines() if ln.startswith("[")}
        rules = {"due": "D", "must": "R", "budget": "BUDGET", "Chase": "ACTION"}
        out = []
        for i in ids:
            label = next((v for k, v in rules.items() if k in lines[i]), "-")
            out.append(f"{i}|{label if kind == 'LABEL' else (lines[i] if label != '-' else '-')}")
        return "\n".join(out) + f"\nEND|{len(ids)}\n"
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


def small_model(req):
    """The small model at upload: say what a document is, who speaks each line of a call, and which side
    each person is on, from what the text shows."""
    kind = task_name(req)
    if kind == "CLASSIFY":
        if "Exported" in req.document:
            return "deal-notes|-|2026-08-14"
        return "call-transcript|-|2026-08-12" if "speakerId" in req.document else "rfp|-|-"
    return {"WHO": who, "SPEAKERS": sides}[kind](req)


def speaker_model(answer):
    """A small model whose answer about sides is `answer`; it says who speaks each line as `small_model`."""
    return ScriptedClient(lambda r: answer(r) if task_name(r) == "SPEAKERS" else small_model(r))


class FakeChecker:
    async def _ask(self, new_text, related, instructions=None):
        return {f["fact_id"]: 0.05 for f in related}, None


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "runs"


@pytest.fixture
def model():
    return ScriptedClient(handler)


def make_app(root, **kw):
    kw.setdefault("bid_client", ScriptedClient(handler))
    kw.setdefault("classifier", ScriptedClient(small_model))
    kw.setdefault("checker", FakeChecker())
    return create_app(root, chat_model=ScriptedChat(["hi"]), summary_model=Scripted(), **kw)


@pytest.fixture
async def c(root, model):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(root, bid_client=model)), base_url="http://test") as c:
        yield c


async def upload(c, bid, name, data):
    return await c.post(f"/api/bids/{bid}/documents", params={"name": name}, content=data)


async def wait_job(c, job_id):
    for _ in range(400):
        j = (await c.get(f"/api/extract/{job_id}")).json()
        if j["status"] != "running":
            return j
        await asyncio.sleep(0.05)
    raise AssertionError("job did not finish")


async def process(c, bid, **body):
    r = await c.post(f"/api/bids/{bid}/process", json={"confirm": True, **body})
    assert r.status_code == 200, r.text
    return await wait_job(c, r.json()["job_id"])


async def ready_bid(c, with_addendum=False):
    assert (await c.post("/api/bids", json={"name": "Ulster"})).json()["bid_id"] == "ulster"
    for name, data in (("RFP.pdf", RFP), ("deal.md", NOTES), ("call.json", CALL), *((("ADD1.pdf", ADDENDUM),) if with_addendum else ())):
        assert (await upload(c, "ulster", name, data)).status_code == 200
    await c.patch("/api/bids/ulster", json={"team": [{"name": "Tom Okafor"}]})
    m = (await c.get("/api/bids/ulster")).json()
    nos = {d["doc_id"]: d["no"] for d in m["documents"]}
    for doc_id, no in nos.items():
        fields = {"confirmed": True}
        if doc_id == "RFP":
            fields["issue_date"] = "2026-07-01"
        if doc_id == "ADD1":
            fields.update(playbook="change-addendum", issue_number=1, issue_date="2026-08-01")
        if doc_id == "call":
            speakers = {s["name"]: s["id"] for s in next(d for d in m["documents"] if d["doc_id"] == "call")["speakers"]}
            fields.update(speakers=[{"id": speakers["Dana Pike"], "side": "buyer"}, {"id": speakers["Tom Okafor"], "side": "ours"}],
                          speakers_confirmed=True)
        r = await c.patch(f"/api/bids/ulster/documents/{no}", json=fields)
        assert r.status_code == 200, r.text
    return nos


# --- bids and documents ---------------------------------------------------------------------


async def test_create_list_get_and_patch(c, root):
    made = (await c.post("/api/bids", json={"name": "Ulster County", "deal_id": "d1"})).json()
    assert made["bid_id"] == "ulster-county" and made["deal_id"] == "d1" and made["order"] == [] and made["run"] == ""
    assert {"name", "description", "role", "spoken"} <= set(made["playbooks"][0]) and "rfp" in [p["name"] for p in made["playbooks"]]
    assert (await c.post("/api/bids", json={"name": " "})).status_code == 400
    [row] = (await c.get("/api/bids")).json()
    assert set(row) == {"bid_id", "name", "customer", "due", "run", "documents", "facts", "modified"} and row["documents"] == 0
    got = (await c.patch("/api/bids/ulster-county", json={"name": "Renamed", "team": [{"name": " Tom Okafor "}, {"name": "tom okafor"}]})).json()
    assert got["name"] == "Renamed" and got["team"] == [{"name": "Tom Okafor", "role": ""}]
    assert (await c.patch("/api/bids/ulster-county", json={"name": ""})).status_code == 400
    assert (await c.patch("/api/bids/ulster-county", json={"team": [{"nom": "x"}]})).status_code == 400
    assert (await c.patch("/api/bids/ulster-county", json={"colour": "red"})).status_code == 400
    assert (await c.patch("/api/bids/ulster-county", json={"precedence": ["ghost"]})).status_code == 400


async def test_a_bid_has_a_customer_a_due_date_and_a_team_with_roles(c, root):
    plain = (await c.post("/api/bids", json={"name": "Plain"})).json()
    assert (plain["customer"], plain["due"], plain["team"]) == ("", None, [])
    made = (await c.post("/api/bids", json={"name": "Ulster", "customer": " Ulster County ", "due": "2026-09-02"})).json()
    assert (made["customer"], made["due"]) == ("Ulster County", "2026-09-02")
    rows = {r["bid_id"]: r for r in (await c.get("/api/bids")).json()}
    assert (rows["ulster"]["customer"], rows["ulster"]["due"], rows["plain"]["due"]) == ("Ulster County", "2026-09-02", None)
    for bad in ("09/02/2026", "2026-02-30", "soon"):
        assert (await c.post("/api/bids", json={"name": "Bad", "due": bad})).status_code == 400
        assert (await c.patch("/api/bids/ulster", json={"due": bad})).status_code == 400
    assert (await c.get("/api/bids/ulster")).json()["due"] == "2026-09-02"  # a refused change leaves it
    got = (await c.patch("/api/bids/ulster", json={"customer": "Albany", "due": "2026-10-01"})).json()
    assert (got["customer"], got["due"]) == ("Albany", "2026-10-01")
    assert (await c.patch("/api/bids/ulster", json={"due": None})).json()["due"] is None
    team = [{"name": "Tom Okafor", "role": " Bid manager "}, {"name": "Priya Raman"}]
    got = (await c.patch("/api/bids/ulster", json={"team": team})).json()
    assert got["team"] == [{"name": "Tom Okafor", "role": "Bid manager"}, {"name": "Priya Raman", "role": ""}]
    other = (await c.patch("/api/bids/ulster", json={"name": "Renamed"})).json()  # another field leaves the team as it was
    assert other["team"] == got["team"] and other["customer"] == "Albany"
    assert (await c.patch("/api/bids/ulster", json={"team": [{"name": "x", "role": 3}]})).status_code == 400


async def test_an_old_manifest_without_the_new_fields_still_loads(c, root):
    await c.post("/api/bids", json={"name": "Old"})
    path = root / "_bids" / "old" / "bid.json"
    m = json.loads(path.read_text())
    for key in ("customer", "due"):
        m.pop(key)
    m["team"] = [{"name": "Tom Okafor"}]
    path.write_text(json.dumps(m))
    got = (await c.get("/api/bids/old")).json()
    assert (got["customer"], got["due"], got["team"]) == ("", None, [{"name": "Tom Okafor", "role": ""}])
    [row] = (await c.get("/api/bids")).json()
    assert (row["customer"], row["due"]) == ("", None)


async def test_the_lines_of_a_call_come_with_who_speaks_them(c):
    await c.post("/api/bids", json={"name": "Ulster"})
    await upload(c, "ulster", "call.json", CALL)
    await upload(c, "ulster", "deal.md", NOTES)
    r = await c.get("/api/bids/ulster/documents/1/lines")
    assert r.status_code == 200
    got = r.json()
    # the header lines of the call (its title, its parties) are units no one speaks
    assert got["total"] == 7 and len(got["lines"]) == 7 and all(x["id"] for x in got["lines"])
    assert [(x["speaker"], x["text"]) for x in got["lines"] if x["text"][0] in "TW"] == [
        ("Dana Pike", "The budget is fixed at 90,000 dollars."), ("Tom Okafor", "We plan a discount on the budget.")]
    assert got["lines"][0]["speaker"] == ""
    short = (await c.get("/api/bids/ulster/documents/1/lines", params={"limit": 1})).json()
    assert len(short["lines"]) == 1 and short["total"] == 7
    assert (await c.get("/api/bids/ulster/documents/2/lines")).status_code == 400  # deal notes are not spoken
    assert (await c.get("/api/bids/ulster/documents/9/lines")).status_code == 404
    assert (await c.get("/api/bids/nope/documents/1/lines")).status_code == 404


@pytest.mark.parametrize("bid", ["nope", "../x", "UPPER", "a b", ".hidden", "-x", "x" * 90])
async def test_bid_ids_are_checked_and_unknown_bids_are_404(c, root, bid):
    for r in (await c.get(f"/api/bids/{bid}"), await c.patch(f"/api/bids/{bid}", json={}), await upload(c, bid, "a.md", b"# x\n"),
              await c.post(f"/api/bids/{bid}/plan"), await c.post(f"/api/bids/{bid}/process", json={"confirm": True}),
              await c.delete(f"/api/bids/{bid}/documents/1")):
        assert r.status_code in (404, 405), (bid, r.status_code)
    assert not (root / "_bids" / "x").exists()


async def test_uploads_are_checked(c, root):
    await c.post("/api/bids", json={"name": "Ulster"})
    r = await upload(c, "ulster", "tool.exe", b"MZ")
    assert r.status_code == 400 and r.json()["detail"] == "this file type is not supported"
    assert (await upload(c, "ulster", "", b"x")).status_code == 400
    assert (await upload(c, "ulster", "a.pdf", b"not a pdf")).status_code == 400
    for name, data in (("a.txt", b"\xff\xfe\x00bad"), ("a.md", b" \n"), ("a.xlsx", b"not a workbook"), ("a.docx", b"not a document")):
        r = await upload(c, "ulster", name, data)
        assert r.status_code == 400 and r.json()["detail"] == "the file could not be read", name
    ok = await upload(c, "ulster", "deal.md", NOTES)
    assert ok.status_code == 200
    doc = ok.json()
    assert (doc["no"], doc["doc_id"], doc["playbook"], doc["issue_date"], doc["status"], doc["confirmed"]) == (
        1, "deal", "deal-notes", "2026-08-14", "uploaded", False)
    assert doc["proposed"]["by"] == "model" and doc["missing"] == ["type not confirmed"]
    dup = await upload(c, "ulster", "again.md", NOTES)
    assert dup.status_code == 400 and dup.json()["detail"] == "this file is already in the bid"
    assert (await upload(c, "ulster", "../../evil.md", b"# other\n")).json()["file"] == "files/2_evil.md"
    assert (await c.delete("/api/bids/ulster/documents/2")).json() == {"ok": True}
    assert (await c.delete("/api/bids/ulster/documents/2")).status_code == 404
    assert (await c.patch("/api/bids/ulster/documents/9", json={"confirmed": True})).status_code == 404
    bad = await c.patch("/api/bids/ulster/documents/1", json={"issue_date": "08/01/2026"})
    assert bad.status_code == 400 and "YYYY-MM-DD" in bad.json()["detail"]
    assert (await c.patch("/api/bids/ulster/documents/1", json={"playbook": "nope"})).status_code == 400
    assert (await c.patch("/api/bids/ulster/documents/1", json={"playbook": None})).status_code == 400
    assert (await c.patch("/api/bids/ulster/documents/1", json={"issue_date": None})).json()["issue_date"] is None


async def test_the_model_classifies_at_upload_and_its_failure_leaves_the_rules(root):
    seen = []

    def classify_handler(req):
        seen.append(task_name(req))
        return "deal-notes|-|2026-08-14"

    app = make_app(root, classifier=ScriptedClient(classify_handler))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/bids", json={"name": "Ulster"})
        doc = (await upload(c, "ulster", "x.md", NOTES)).json()
        assert seen == ["CLASSIFY"] and doc["proposed"]["by"] == "model" and doc["playbook"] == "deal-notes"
    boom = ScriptedClient(lambda r: RuntimeError("down"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(root, classifier=boom)), base_url="http://test") as c:
        await c.post("/api/bids", json={"name": "Second"})
        doc = (await upload(c, "second", "x.md", NOTES)).json()
        assert doc["proposed"]["by"] == "rules" and doc["issue_date"] == "2026-08-14"
    assert boom.requests  # it was asked


async def test_the_team_list_proposes_speakers_until_they_are_confirmed(c):
    await c.post("/api/bids", json={"name": "Ulster"})
    doc = (await upload(c, "ulster", "call.json", CALL)).json()
    assert doc["playbook"] == "call-transcript" and [(s["name"], s["proposed"], s["side"]) for s in doc["speakers"]] == [
        ("Dana Pike", "buyer", ""), ("Tom Okafor", "ours", "")]  # the model read the call's own affiliation
    await c.patch("/api/bids/ulster", json={"team": [{"name": "Dana Pike"}]})
    [d] = (await c.get("/api/bids/ulster")).json()["documents"]
    assert {s["name"]: (s["proposed"], s["why"]) for s in d["speakers"]}["Dana Pike"] == ("ours", "team list")
    await c.patch("/api/bids/ulster/documents/1", json={"speakers": [{"name": "Dana Pike", "side": "buyer"}, {"name": "Tom Okafor", "side": "ours"}],
                                                        "speakers_confirmed": True})
    await c.patch("/api/bids/ulster", json={"team": []})
    [d] = (await c.get("/api/bids/ulster")).json()["documents"]
    assert {s["name"]: s["proposed"] for s in d["speakers"]}["Dana Pike"] == "ours" and d["speakers_confirmed"]  # confirmed: not touched


async def test_the_model_places_speakers_at_upload_and_again_on_request(root):
    seen = []

    def answer(req):
        seen.append(task_name(req))
        return "Dana Pike|OTHER|-|BUYER|advisor to the buyer\nTom Okafor|BUYER|-|-|odd\nEND|2\n"

    app = make_app(root, speaker_model=speaker_model(answer))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/bids", json={"name": "Ulster"})
        doc = (await upload(c, "ulster", "call.json", CALL)).json()
        assert seen == ["SPEAKERS"]
        assert {s["name"]: (s["proposed"], s["acts_for"]) for s in doc["speakers"]} == {"Dana Pike": ("other", "buyer"), "Tom Okafor": ("buyer", "")}
        assert doc["speakers"][0]["why"] == "model: advisor to the buyer" and "speakers_model" in doc
        assert (await upload(c, "ulster", "n.md", NOTES)).json()["speakers"] == [] and seen == ["SPEAKERS"]  # notes: no call
        assert doc["voices"] and set(doc["voices"].values()) == {"Dana Pike", "Tom Okafor"}
        again = await c.post("/api/bids/ulster/documents/1/speakers/suggest")
        assert again.status_code == 200 and seen == ["SPEAKERS", "SPEAKERS"]
        assert (await c.post("/api/bids/ulster/documents/2/speakers/suggest")).status_code == 400  # not a transcript
        await c.patch("/api/bids/ulster/documents/1", json={"speakers": [{"name": "Dana Pike", "side": "other"}, {"name": "Tom Okafor", "side": "ours"}],
                                                            "speakers_confirmed": True})
        refused = await c.post("/api/bids/ulster/documents/1/speakers/suggest")
        assert refused.status_code == 400 and seen == ["SPEAKERS", "SPEAKERS"]
        [d, _] = (await c.get("/api/bids/ulster")).json()["documents"]
        assert {s["name"]: s["side"] for s in d["speakers"]} == {"Dana Pike": "other", "Tom Okafor": "ours"}


async def test_a_failed_speaker_call_leaves_the_rules_and_no_key_is_a_clear_error(root):
    boom = ScriptedClient(lambda r: RuntimeError("down"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(root, speaker_model=boom)), base_url="http://test") as c:
        await c.post("/api/bids", json={"name": "Ulster"})
        doc = (await upload(c, "ulster", "call.json", CALL)).json()
        assert boom.requests and "speakers_model" not in doc and doc["voices"] is None and doc["speakers"] == []
        assert doc["missing"] == ["type not confirmed", "speakers not read yet"] or doc["missing"] == ["type not confirmed"]
        assert (await c.post("/api/bids/ulster/documents/1/speakers/suggest")).status_code == 400
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(root, classifier=None)), base_url="http://test") as c:
        await c.post("/api/bids", json={"name": "Third"})
        await upload(c, "third", "call.json", CALL)
        r = await c.post("/api/bids/third/documents/1/speakers/suggest")
        assert r.status_code == 400 and r.json()["detail"] == "OPENAI_API_KEY is not set"


async def test_changing_a_note_to_a_call_places_its_speakers_once(root):
    seen = []
    app = make_app(root, speaker_model=speaker_model(lambda r: seen.append(1) or "Dana Pike|BUYER|-|-|the buyer\nEND|1\n"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/bids", json={"name": "Ulster"})
        await upload(c, "ulster", "call.json", CALL)
        await c.patch("/api/bids/ulster/documents/1", json={"playbook": "deal-notes"})
        r = await c.patch("/api/bids/ulster/documents/1", json={"playbook": "call-transcript"})
        assert len(seen) == 1 and r.json()["speakers_model"]  # the first answer is kept: no second call


# --- plan and process -----------------------------------------------------------------------


async def test_plan_lists_the_calls_of_each_confirmed_document(c):
    nos = await ready_bid(c)
    await upload(c, "ulster", "later.md", b"# Later\n\nOne more point.\n")  # not confirmed
    plan = (await c.post("/api/bids/ulster/plan", json={"votes": 1})).json()
    assert [d["doc_id"] for d in plan["documents"]] == ["RFP", "call", "deal"]
    assert plan["skipped"] == [{"no": 4, "doc_id": "later", "why": "type not confirmed"}]
    by = {d["doc_id"]: d for d in plan["documents"]}
    assert [r["call"] for r in by["RFP"]["calls"]] == ["LABEL1", "STATE1", "CHECK", "XREF"] and by["RFP"]["calls"][0]["times"] == 1
    assert [r["call"] for r in by["deal"]["calls"]] == ["LABEL1", "STATE1", "RELATE1"]
    assert set(by["RFP"]) == {"no", "doc_id", "file_name", "playbook", "missing", "units", "calls", "total_calls", "stored", "error"}
    assert by["RFP"]["units"] == 2 and by["RFP"]["stored"] is None and by["RFP"]["no"] == nos["RFP"]
    assert plan["total_calls"] == sum(d["total_calls"] for d in plan["documents"]) and plan["relate_again"] == []
    assert (await c.post("/api/bids/ulster/plan", json={"votes": 2})).status_code == 400
    assert (await c.post("/api/bids/ulster/plan")).status_code == 200  # no body: each playbook's own votes


async def test_process_is_refused_until_it_may_run(root, monkeypatch):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(root, chat_model=ScriptedChat(["hi"]),
                                                                              summary_model=Scripted())), base_url="http://test") as c:
        await c.post("/api/bids", json={"name": "Ulster"})
        r = await c.post("/api/bids/ulster/process", json={"confirm": True})
        assert r.status_code == 400 and r.json()["detail"] == "OPENAI_API_KEY is not set"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(root)), base_url="http://test") as c:
        r = await c.post("/api/bids/ulster/process", json={})
        assert r.status_code == 400 and "confirm must be true" in r.json()["detail"]
        assert (await c.post("/api/bids/ulster/process", json={"confirm": True})).json()["detail"] == "the bid has no confirmed document"
        await upload(c, "ulster", "call.json", CALL)
        await upload(c, "ulster", "deal.md", NOTES)
        await c.patch("/api/bids/ulster/documents/1", json={"confirmed": True})
        await c.patch("/api/bids/ulster/documents/2", json={"confirmed": True, "issue_date": None})
        r = await c.post("/api/bids/ulster/process", json={"confirm": True})
        assert r.status_code == 400
        assert r.json()["detail"] == ("these documents are not ready: d1: speakers not confirmed, a speaker has no side; "
                                      "d2: issue date missing")
        await c.patch("/api/bids/ulster/documents/1", json={"confirmed": False})
        r = await c.post("/api/bids/ulster/process", json={"confirm": True, "votes": 4})
        assert r.status_code == 400 and "votes" in r.json()["detail"]


async def test_a_whole_bid_through_the_routes(c, root, model, monkeypatch):
    nos = await ready_bid(c)
    unconfirmed = (await upload(c, "ulster", "extra.md", b"# Extra\n\nNot confirmed yet.\n")).json()
    job = await process(c, "ulster")
    assert (job["status"], job["run"], job["error"]) == ("done", "_bids/ulster", None) and job["result"].endswith("from 3 documents")
    steps = job["steps"]
    assert set(steps[0]) == {"doc_no", "step", "status", "detail"} and steps[0]["step"] == "plan"
    assert f"skipped, not confirmed: d{unconfirmed['no']} extra.md" in steps[0]["detail"]
    assert {(s["doc_no"], s["step"]) for s in steps} >= {(nos["RFP"], "cut"), (nos["call"], "extract"), (nos["deal"], "relate"), (0, "group"),
                                                         (0, "pairs"), (0, "build")}
    assert steps[-1] == {"doc_no": 0, "step": "build", "status": "done", "detail": steps[-1]["detail"]}

    m = (await c.get("/api/bids/ulster")).json()
    assert m["run"] == "_bids/ulster" and [d["status"] for d in m["documents"]] == ["extracted", "extracted", "extracted", "uploaded"]
    assert m["order"] == ["extra", "RFP", "call", "deal"]  # the model called the unconfirmed note an RFP, with no date
    rows = {r["run"]: r for r in (await c.get("/api/runs")).json()}
    assert rows["_bids/ulster"]["kind"] == "bid" and rows["_bids/ulster"]["name"] == "Ulster" and rows["_bids/ulster"]["documents"] == 4
    assert all("kind" not in r for k, r in rows.items() if k != "_bids/ulster")

    got = (await c.get("/api/facts", params={"run": "_bids/ulster"})).json()
    assert [d["doc_id"] for d in got["documents"]] == ["RFP", "call", "deal"]
    assert set(got["documents"][0]) == {"no", "doc_id", "file_name", "playbook", "level", "visibility", "issue_date", "issue_number", "has_pdf"}
    assert [(d["has_pdf"], d["level"], d["visibility"]) for d in got["documents"]] == [
        (True, "1", "external"), (False, "by speaker", "internal"), (False, "4", "internal")]
    levels = {(f["doc_no"], f["level"]) for f in got["facts"]}
    assert (nos["RFP"], 1) in levels and (nos["deal"], 4) in levels and (nos["call"], 2) in levels
    listed = (await c.get("/api/facts/list", params={"run": "_bids/ulster", "docs": str(nos["deal"])})).json()
    by_id = {f["fact_id"]: f for f in got["facts"]}
    assert listed["total"] and {by_id[i]["doc_no"] for it in listed["items"] for i in it["fact_ids"]} == {nos["deal"]}
    four = (await c.get("/api/facts/list", params={"run": "_bids/ulster", "levels": "4,1"})).json()
    assert {by_id[i]["level"] for it in four["items"] for i in it["fact_ids"]} == {1, 4}
    assert (await c.get("/api/facts/list", params={"run": "_bids/ulster", "docs": "x"})).status_code == 400

    full = list(csv.DictReader(io.StringIO((await c.get("/api/facts.csv", params={"run": "_bids/ulster"})).content.decode("utf-8-sig"))))
    assert list(full[0])[-3:] == ["document", "level", "visibility"] and {r["document"] for r in full} == {"RFP", "call", "deal"}
    ext = await c.get("/api/facts.csv", params={"run": "_bids/ulster", "audience": "external"})
    rows = list(csv.DictReader(io.StringIO(ext.content.decode("utf-8-sig"))))
    assert rows and {r["document"] for r in rows} == {"RFP"} and {r["visibility"] for r in rows} == {"external"}
    assert len(rows) < len(full) and "external" in ext.headers["content-disposition"]
    assert (await c.get("/api/facts.csv", params={"run": "_bids/ulster", "audience": "x"})).status_code == 400

    # the page of a document of the bid
    rfp_fact = next(f for f in got["facts"] if f["doc_no"] == nos["RFP"])
    deal_fact = next(f for f in got["facts"] if f["doc_no"] == nos["deal"])
    seen = []
    real = server.render_page
    monkeypatch.setattr(server, "render_page", lambda p, page, boxes: seen.append(str(p)) or real(p, page, boxes))
    p = {"run": "_bids/ulster", "page": 1}
    ok = await c.get("/api/page", params={**p, "fact_id": rfp_fact["fact_id"]})
    assert ok.status_code == 200 and ok.content[:4] == b"\x89PNG" and seen[-1].endswith("1_RFP.pdf")
    assert (await c.get("/api/page", params={**p, "doc": "RFP"})).status_code == 200
    assert (await c.get("/api/page", params={**p, "doc": "deal"})).json() == {"detail": "this document has no page images"}
    assert (await c.get("/api/page", params={**p, "fact_id": deal_fact["fact_id"]})).status_code == 404
    assert (await c.get("/api/page", params={**p, "doc": "ghost"})).status_code == 404
    again = len(seen)
    await c.get("/api/page", params={**p, "fact_id": rfp_fact["fact_id"]})
    assert len(seen) == again  # cached

    # nothing new to read: settle and build still run
    n = len(model.requests)
    job = await process(c, "ulster")
    assert job["status"] == "done" and "reading nothing new" in job["steps"][0]["detail"]
    assert {s["step"] for s in job["steps"]} == {"plan", "group", "pairs", "build"}
    assert len(model.requests) >= n


async def test_process_asks_again_for_the_units_relate_left_unanswered(c, root):
    await ready_bid(c)
    assert (await process(c, "ulster"))["status"] == "done"
    bid = B.Bid(root, "ulster")
    [no] = [d["no"] for d in bid.manifest()["documents"] if d["doc_id"] == "deal"]
    path = root / bid.document(no)["run"] / "relations.json"
    rel = json.loads(path.read_text())
    assert rel["units"], "the notes are related to the RFP"
    rel["units"][0].update(kind="", targets=[], votes=[])
    rel["incomplete"] = [rel["units"][0]["unit"]]
    path.write_text(json.dumps(rel))
    assert bid.incomplete_relations() == {no: rel["incomplete"]}
    job = await process(c, "ulster")
    assert job["status"] == "done", job
    assert {"doc_no": no, "step": "relate", "status": "done", "detail": "1 units asked again"} in job["steps"]
    assert bid.incomplete_relations() == {}


async def test_an_earlier_document_added_later_makes_the_others_relate_again_and_a_relation_can_be_rejected(c, root, model):
    nos = await ready_bid(c)
    assert (await process(c, "ulster"))["status"] == "done"
    assert (await upload(c, "ulster", "ADD1.pdf", ADDENDUM)).status_code == 200
    no = 4
    await c.patch(f"/api/bids/ulster/documents/{no}", json={"playbook": "change-addendum", "issue_number": 1, "issue_date": "2026-08-01",
                                                          "confirmed": True})
    assert [d["doc_id"] for d in (await c.post("/api/bids/ulster/plan")).json()["documents"]] == ["ADD1"]
    job = await process(c, "ulster")
    assert job["status"] == "done", job
    again = {s["doc_no"] for s in job["steps"] if s["step"] == "relate" and s["status"] == "done"}
    assert {nos["call"], nos["deal"], no} <= again
    assert (await c.post("/api/bids/ulster/plan")).json()["relate_again"] == []

    facts = (await c.get("/api/facts", params={"run": "_bids/ulster"})).json()["facts"]  # the rebuilt facts, not the cached ones
    assert {f["doc_no"] for f in facts} == {nos["RFP"], nos["call"], nos["deal"], no}
    old = next(f for f in facts if f["doc_no"] == nos["RFP"] and "June 10" in f["text"])
    new = next(f for f in facts if f["doc_no"] == no)
    assert "replaced" in old["flags"] and old["replaced_by"] == new["fact_id"]
    rid = old["relations"][0]["id"]
    p = {"run": "_bids/ulster"}
    rej = (await c.post(f"/api/relations/{rid}/reject", params=p, json={"reason": "wrong"})).json()
    assert rej["ok"] and rej["rejected"] and rej["relation_id"] == rid
    now = {f["fact_id"]: f for f in (await c.get("/api/facts", params=p)).json()["facts"]}
    assert "replaced" not in now[old["fact_id"]]["flags"]
    assert (await c.post(f"/api/relations/{rid}/reject", params=p)).status_code == 404  # no longer on the facts
    back = (await c.post(f"/api/relations/{rid}/restore", params=p)).json()
    assert back["ok"] and not back["rejected"] and any(f["fact_id"] == old["fact_id"] for f in back["facts"])
    assert "replaced" in {f["fact_id"]: f for f in (await c.get("/api/facts", params=p)).json()["facts"]}[old["fact_id"]]["flags"]
    assert (await c.post("/api/relations/r_nope/reject", params=p)).status_code == 404
    assert (await c.post("/api/groups/g_nope/ungroup", params=p)).status_code == 404
    assert (await c.post("/api/groups/g_nope/regroup", params=p)).status_code == 404

    # precedence: a document the user ranks first; the facts are derived again
    assert (await c.patch("/api/bids/ulster", json={"precedence": ["ADD1", "RFP", "ADD1"]})).status_code == 400
    assert (await c.patch("/api/bids/ulster", json={"precedence": ["ADD1", "RFP"]})).json()["precedence"] == ["ADD1", "RFP"]
    assert (await c.patch("/api/bids/ulster", json={"precedence": []})).json()["precedence"] is None


async def test_a_failing_document_is_marked_failed_and_the_rest_go_on(root):
    def flaky(req):
        if task_name(req) in ("LABEL", "STATE") and "budget" in req.document:
            raise RuntimeError("boom")
        return handler(req)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(root, bid_client=ScriptedClient(flaky))), base_url="http://test") as c:
        nos = await ready_bid(c)
        job = await process(c, "ulster")
        assert job["status"] == "done" and "failed:" in job["result"] and "boom" in job["result"]
        docs = {d["doc_id"]: d for d in (await c.get("/api/bids/ulster")).json()["documents"]}
        assert docs["call"]["status"] == "failed" and "boom" in docs["call"]["error"] and docs["RFP"]["status"] == "extracted"
        assert any(s["doc_no"] == nos["call"] and s["status"] == "failed" for s in job["steps"])


async def test_one_job_at_a_time_and_old_jobs_have_steps_too(root):
    release = threading.Event()

    def slow(req):
        release.wait(5)
        return handler(req)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(root, bid_client=ScriptedClient(slow))), base_url="http://test") as c:
        await ready_bid(c)
        first = (await c.post("/api/bids/ulster/process", json={"confirm": True})).json()["job_id"]
        second = await c.post("/api/bids/ulster/process", json={"confirm": True})
        assert second.status_code == 409 and second.json()["detail"] == "an extraction is already running"
        running = (await c.get(f"/api/extract/{first}")).json()
        assert running["status"] == "running" and isinstance(running["steps"], list)
        release.set()
        assert (await wait_job(c, first))["status"] == "done"
        assert (await c.get("/api/extract/nope")).status_code == 404


# --- helpers without a server ---------------------------------------------------------------


def test_external_view_drops_internal_citations_and_the_facts_left_with_none():
    def cite(i, visibility):
        return {"id": i, "page": 1, "page_label": "1", "section": "", "text": f"t{i}", "doc_id": "d", "visibility": visibility}

    recs = R.normalize([
        {"category": "D", "text": "mixed", "fact_id": "a", "citations": [cite("p1.1", "external"), cite("p1.2", "internal")]},
        {"category": "Q", "text": "only inside", "fact_id": "b", "citations": [cite("p1.3", "internal")]},
        {"category": "D", "text": "outside", "fact_id": "c", "citations": [cite("p1.4", "external")]},
        {"category": "D", "text": "none", "fact_id": "d", "citations": []},
    ])
    out = R.external_view(recs)
    assert [r["fact_id"] for r in out] == ["a", "c", "d"] and [c["id"] for c in out[0]["citations"]] == ["p1.1"]
    assert [c["id"] for c in recs[0]["citations"]] == ["p1.1", "p1.2"]  # the input is not changed
    row = R.csv_row(out[0], bid=True)
    assert (row["citation_ids"], row["source_text"], row["visibility"]) == ("p1.1", "tp1.1", "external")
    assert R.csv_row(recs[0], bid=True)["visibility"] == "internal"
    assert list(R.csv_row(recs[2])) == list(R.CSV_COLUMNS)


def test_the_workspace_of_a_rebuilt_bid_is_read_again(tmp_path):
    from fact_extractor.web.workspace import Workspace

    folder = tmp_path / "_bids" / "x"
    folder.mkdir(parents=True)
    (folder / "bid.json").write_text(json.dumps({"bid_id": "x", "documents": []}))
    rec = {"category": "D", "text": "one", "fact_id": "a", "doc_id": "d", "citations": []}
    (folder / "facts.json").write_text(json.dumps([rec]))
    ws = Workspace(folder / "facts.json")
    assert len(ws.state().facts) == 1
    (folder / "facts.json").write_text(json.dumps([rec, {**rec, "fact_id": "b"}]))
    (folder / "conflicts.json").write_text(json.dumps([{"id": "d:1", "fact_ids": ["a", "b"], "options": []}]))
    state = ws.state()
    assert len(state.facts) == 2 and [c["id"] for c in state.conflicts] == ["d:1"]
    assert B.slug("Ulster County") == "ulster-county"


async def test_ungroup_and_regroup_return_the_facts_of_the_group(tmp_path):
    folder = tmp_path / "runs" / "doc" / "run1"
    folder.mkdir(parents=True)
    grouped = [{"category": "R", "text": t, "fact_id": i, "doc_id": "doc", "run_id": "run1", "group_id": "g_1", "group_kind": "list",
                "group_title": "Support", "citations": [{"id": f"p1.{n}", "page": 1}]} for n, (i, t) in enumerate([("a", "One."), ("b", "Two.")], 1)]
    (folder / "facts.json").write_text(json.dumps(grouped))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(tmp_path / "runs")), base_url="http://test") as c:
        p = {"run": "doc/run1"}
        out = (await c.post("/api/groups/g_1/ungroup", params=p, json={"reason": "different"})).json()
        assert out["ok"] and out["ungrouped"] and [f["fact_id"] for f in out["facts"]] == ["a", "b"] and all(not f["group_id"] for f in out["facts"])
        assert (await c.post("/api/groups/g_1/ungroup", params=p)).status_code == 409  # already ungrouped
        back = (await c.post("/api/groups/g_1/regroup", params=p)).json()
        assert back["ok"] and not back["ungrouped"] and [f["group_id"] for f in back["facts"]] == ["g_1", "g_1"]

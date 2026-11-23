"""The review routes (WEB_UI_SPEC.md 11.1). Offline: extraction is a fake."""

import asyncio
import csv
import io
import json
import threading

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import httpx
from test_web_agent import ScriptedChat
from test_web_server import make_pdf
from test_web_summaries import MORE, Scripted
from test_web_workspace import cite, fact, make_run

from fact_extractor.web.server import create_app

RUN = "doc/run1"
REPORT = {"run_id": "run1", "pages": 5, "seconds": {"total": 3.5},
          "output_tokens": 120, "cache_hit_calls_2_to_n": 0.5, "failed_calls": [], "calls": [
              {"name": "LABEL1", "kind": "label", "status": "ok", "seconds": 1.2, "lines": 4, "usage": {"output_tokens": 10},
               "retries": 0, "log": ["a"], "output": "out"}]}
FAKE_REPORT = {"facts": 1, "ids": 4, "seconds": {"total": 1.5}, "votes": 1, "facts_votes_agreed": 1,
               "facts_votes_split": 0, "failed_calls": []}


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = make_run(tmp_path / "runs", RUN, facts=[
        *MORE,
        fact("f_p1", "O", "Winner pays tax", [cite("p4.2", 4, "After award, the winner pays tax of $5,000.")],
             flags=["post-award", "risk"]),
    ])
    (folder / "report.json").write_text(json.dumps(REPORT))
    return tmp_path / "runs"


@pytest.fixture
def made(tmp_path):
    """Hands out PDFs in the working directory."""
    make_pdf(tmp_path / "rfp.pdf")
    return tmp_path / "rfp.pdf"


class Fake:
    """Stands in for runs.run_extraction: writes a run into runs_root, optionally blocks or fails."""

    def __init__(self, fail=None, gate=None):
        self.calls, self.fail, self.gate = [], fail, gate

    def __call__(self, pdf_bytes, *, deal_id, doc_id, model, votes, refresh, runs_root):
        self.calls.append({"deal_id": deal_id, "doc_id": doc_id, "model": model, "votes": votes, "refresh": refresh})
        if self.gate:
            self.gate.wait(5)
        if self.fail:
            raise self.fail
        folder = make_run(runs_root, f"{doc_id}/run_new", facts=[fact("f_n1", "B", "New fact", [cite("p1.1", 1, "x")])])
        return folder / "facts.json", FAKE_REPORT, False


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def fake():
    return Fake()


@pytest.fixture
async def c(root, fake):
    app = create_app(root, chat_model=ScriptedChat(["hi"]), summary_model=Scripted(), extractor=fake)
    async with client(app) as c:
        yield c


async def wait_job(c, job_id):
    for _ in range(100):
        j = (await c.get(f"/api/extract/{job_id}")).json()
        if j["status"] != "running":
            return j
        await asyncio.sleep(0.05)
    raise AssertionError("job did not finish")


# --- overview, facts list, csv ---------------------------------------------------------------


async def test_overview_shape_counts_and_views(c):
    r = (await c.get("/api/overview", params={"run": RUN})).json()
    assert set(r) == {"overview", "counts", "by_category", "has_post_award", "views"}
    assert r["views"] == ["All", "Bid", "After award"] and r["has_post_award"] is True
    assert r["counts"] == {"needs_review": 0, "conflicts": 1, "risk": 1, "mandatory": 1, "unclear": 0}
    assert r["by_category"]["D"] == 3 and set(r["overview"]) >= {"buyer_facts", "calendar", "gates", "scoring"} and not {"summary", "buyer"} & set(r["overview"])
    after = (await c.get("/api/overview", params={"run": RUN, "view": "After award"})).json()
    assert after["by_category"] == {"O": 1} and after["has_post_award"] is True
    assert (await c.get("/api/overview", params={"run": RUN, "view": "x"})).status_code == 400
    assert (await c.get("/api/overview", params={"run": "nope"})).status_code == 404


async def test_overview_uses_corrections_and_stored_summaries(c, root):
    await c.delete("/api/facts/f_b1", params={"run": RUN})
    await c.patch("/api/facts/f_r1", params={"run": RUN}, json={"flags": ["unclear"]})
    r = (await c.get("/api/overview", params={"run": RUN})).json()
    assert r["counts"]["unclear"] == 1 and "B" not in r["by_category"]
    assert r["overview"]["unclear"][0]["text"] == "Vendor must keep 24/7 support"
    rep = {**REPORT, "summaries": {"buyer": [{"row": "Buyer", "text": "The County", "checked": True, "fact_ids": ["f_b1"]}]}}
    make_run(root, "doc/sum", facts=MORE)
    (root / "doc" / "sum" / "report.json").write_text(json.dumps(rep))
    o = (await c.get("/api/overview", params={"run": "doc/sum"})).json()["overview"]
    assert "buyer" not in o and "summary" not in o
    s = (await c.get("/api/summaries", params={"run": "doc/sum"})).json()["sections"][0]
    assert s["key"] == "buyer" and s["source"] == "extraction" and s["rows"][0]["text"] == "The County"


def ids(listing: dict) -> list[str]:
    """The fact IDs of a /facts/list answer, in order."""
    return [i for it in listing["items"] for i in it["fact_ids"]]


async def test_facts_list_filters_and_by_category(c):
    r = (await c.get("/api/facts/list", params={"run": RUN})).json()
    assert set(r) == {"total", "by_category", "items"}  # ids only: the facts themselves come from /api/facts
    assert r["total"] == 8 == len(ids(r)) and set(r["by_category"]) == {"B", "D", "Q", "R", "S", "O"}
    assert r["items"][0] == {"kind": "fact", "fact_ids": [ids(r)[0]]}
    d = (await c.get("/api/facts/list", params={"run": RUN, "categories": "D"})).json()
    assert d["total"] == 3 == len(d["items"]) and d["by_category"] == r["by_category"]  # chips ignore the category filter
    d = (await c.get("/api/facts/list", params={"run": RUN, "categories": "D,S", "statuses": "conflict"})).json()
    assert ids(d) == ["f_d1"] and d["by_category"] == {"D": 1}
    q = (await c.get("/api/facts/list", params={"run": RUN, "q": "email"})).json()
    assert ids(q) == ["f_s1"]
    cited = (await c.get("/api/facts/list", params={"run": RUN, "q": "SHALL GIVE support"})).json()
    assert ids(cited) == ["f_r1"]  # search reaches the cited text
    pg = (await c.get("/api/facts/list", params={"run": RUN, "page_from": 4, "page_to": 5})).json()
    assert set(ids(pg)) == {"f_d2", "f_q1", "f_s1", "f_p1"}
    assert (await c.get("/api/facts/list", params={"run": RUN, "flags": "mandatory,risk"})).json()["total"] == 2
    assert (await c.get("/api/facts/list", params={"run": RUN, "view": "After award"})).json()["total"] == 1
    bid = (await c.get("/api/facts/list", params={"run": RUN, "view": "Bid"})).json()
    assert bid["total"] == 8  # the after-award obligation is a risk and states an amount, so it is kept
    assert (await c.get("/api/facts/list", params={"run": RUN, "view": "zzz"})).status_code == 400
    assert (await c.get("/api/facts/list", params={"run": RUN, "split_only": 1})).json()["total"] == 0


async def test_facts_list_edited_deleted_and_groups(c, root):
    await c.patch("/api/facts/f_b1", params={"run": RUN}, json={"text": "County buys"})
    await c.delete("/api/facts/f_r1", params={"run": RUN})
    assert (await c.get("/api/facts/list", params={"run": RUN})).json()["total"] == 7
    assert (await c.get("/api/facts/list", params={"run": RUN, "include_deleted": 1})).json()["total"] == 8
    e = (await c.get("/api/facts/list", params={"run": RUN, "edited": 1})).json()
    assert ids(e) == ["f_b1"]
    grouped = [fact("f_g1", "R", "Item one", [cite("p1.1", 1, "a")]), fact("f_g2", "R", "Item two", [cite("p1.2", 1, "b")])]
    for g in grouped:
        g.update(group_id="g1", group_kind="list", group_title="Items")
    make_run(root, "doc/grp", facts=grouped)
    r = (await c.get("/api/facts/list", params={"run": "doc/grp"})).json()
    assert r["items"] == [{"kind": "list", "fact_ids": ["f_g1", "f_g2"]}] and r["total"] == 2
    one = (await c.get("/api/facts/list", params={"run": "doc/grp", "q": "two"})).json()
    assert one["items"] == [{"kind": "fact", "fact_ids": ["f_g2"]}]


async def test_facts_route_has_computed_booleans(c):
    facts = (await c.get("/api/facts", params={"run": RUN})).json()["facts"]
    assert all({"post_award", "affects_bid", "split"} <= set(f) for f in facts)
    by = {f["fact_id"]: f for f in facts}
    assert by["f_p1"]["post_award"] and by["f_p1"]["affects_bid"] and not by["f_d1"]["split"]


async def test_csv_bom_headers_filters_and_effective_facts(c):
    await c.patch("/api/facts/f_s1", params={"run": RUN}, json={"text": "Submit by post, \"sealed\""})
    r = await c.get("/api/facts.csv", params={"run": RUN, "categories": "S,D"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="doc_run1_facts.csv"'
    assert r.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert list(rows[0]) == ["category", "category_name", "text", "flags", "status", "page_labels", "sections",
                             "citation_ids", "source_text", "note", "problems", "fact_id"]
    assert [x["fact_id"] for x in rows] == ["f_d1", "f_d3", "f_s1", "f_d2"]  # document order
    assert rows[2]["text"] == 'Submit by post, "sealed"'
    only = await c.get("/api/facts.csv", params={"run": RUN, "q": "nothing matches this"})
    assert len(list(csv.DictReader(io.StringIO(only.content.decode("utf-8-sig"))))) == 0
    assert (await c.get("/api/facts.csv", params={"run": "../x"})).status_code == 404


# --- report, runs table, compare -----------------------------------------------------------------


async def test_report_as_is_and_missing(c, root):
    assert (await c.get("/api/report", params={"run": RUN})).json() == REPORT
    make_run(root, "doc/bare")
    r = await c.get("/api/report", params={"run": "doc/bare"})
    assert r.status_code == 404 and "report" in r.json()["detail"]


async def test_runs_table(c, root):
    (root / RUN / "facts_extra.json").write_text(json.dumps(MORE))
    make_run(root, "doc/run2")
    rows = (await c.get("/api/runs/table")).json()
    assert {r["run"] for r in rows} == {RUN, "doc/run2"}
    row = next(r for r in rows if r["run"] == RUN)
    assert row["document"] == "doc" and row["facts"] == 8 and row["total s"] == 3.5
    assert row["output tokens"] == 120 and len(row["finished"]) == 16


async def test_compare_agreement_and_doc_mismatch(c, root):
    other = [fact("f_d1", "G", "Bids due March 3", [cite("p1.2", 1, "Bids are due March 3.")]),
             fact("f_x", "B", "Other", [cite("p9.1", 9, "z")])]
    make_run(root, "doc/run2", facts=other)
    r = (await c.get("/api/compare", params={"a": RUN, "b": "doc/run2"})).json()
    assert set(r) == {"agreement", "code_differences"}
    ag = r["agreement"]
    assert ag["facts"] == [8, 2] and ag["cited_both"] == 1 and ag["code_agreement"] == 0.0
    assert ag["by_category"]["G"] == {"a": 0, "b": 1, "ids_both": 0}
    assert ag["code_flips"] == [[["DQ", "G"], 1]]
    assert r["code_differences"] == [{"id": "p1.2", "codes_a": "DQ", "codes_b": "G", "facts_a": "Bids due March 3 / Due date is given twice",
                                      "facts_b": "Bids due March 3"}]
    stranger = [fact("f_y", "B", "Other", [cite("p1.1", 1, "z")])]
    stranger[0]["doc_id"] = "other"
    make_run(root, "other/run1", facts=stranger)
    bad = await c.get("/api/compare", params={"a": RUN, "b": "other/run1"})
    assert bad.status_code == 400 and "different" in bad.json()["detail"]
    assert (await c.get("/api/compare", params={"a": RUN, "b": "nope"})).status_code == 404
    assert (await c.get("/api/compare", params={"a": "../..", "b": RUN})).status_code == 404


async def test_compare_ignores_corrections(c, root):
    make_run(root, "doc/run2")
    await c.delete("/api/facts/f_b1", params={"run": RUN})
    ag = (await c.get("/api/compare", params={"a": RUN, "b": "doc/run2"})).json()["agreement"]
    assert ag["facts"][0] == 8  # the stored extraction, not the corrected facts


# --- PDFs ----------------------------------------------------------------------------------------


async def test_pdfs_listing(c, made):
    assert (await c.get("/api/pdfs")).json() == [{"path": "rfp.pdf", "name": "rfp.pdf"}]


async def test_upload_must_be_a_pdf_and_is_capped(c, monkeypatch):
    bad = await c.post("/api/uploads", content=b"hello")
    assert bad.status_code == 400 and "PDF" in bad.json()["detail"]
    assert (await c.post("/api/uploads", content=b"%PDF-1.4 nonsense")).status_code == 400
    from fact_extractor.web import server

    monkeypatch.setattr(server, "MAX_PDF", 10)
    assert (await c.post("/api/uploads", content=b"%PDF" + b"0" * 20)).status_code == 413


# --- uploads and the plan --------------------------------------------------------------------------


async def test_upload_and_plan(c, root, made, tmp_path):
    r = await c.post("/api/uploads", params={"name": "a b/../c.pdf"}, content=made.read_bytes(),
                     headers={"content-type": "application/pdf"})
    up = r.json()
    assert r.status_code == 200 and up["name"] == "c.pdf" and up["pages"] == 3
    assert len(up["upload_id"]) == 16 and int(up["upload_id"], 16) >= 0
    assert (await c.post("/api/uploads", content=b"not a pdf")).status_code == 400
    plan = (await c.post("/api/extract/plan", json={"upload_id": up["upload_id"], "doc_id": "d1", "votes": 3})).json()
    assert set(plan) == {"calls", "total_calls", "units", "stored"} and plan["stored"] is None
    assert plan["calls"][-2:] == [{"call": c, "times": 1, "units": plan["units"], "pages": "1-3"} for c in ("CHECK", "XREF")]
    assert plan["total_calls"] == sum(x["times"] for x in plan["calls"])
    by_path = (await c.post("/api/extract/plan", json={"path": "rfp.pdf", "doc_id": "d1", "votes": 1})).json()
    assert by_path["units"] == plan["units"]
    assert not (root / ".staging").exists() and not (tmp_path / "runs" / "d1").exists()


async def test_plan_reports_stored_result(c, root, made):
    from fact_extractor import results, units

    store_dir = root / "d1" / "run_old"
    store_dir.mkdir(parents=True)
    (store_dir / "facts.json").write_text("[]")
    (store_dir / "meta.json").write_text(json.dumps({
        "pdf_sha256": results.pdf_hash(made.read_bytes()), "pipeline": units.VERSION, "doc_id": "d1",
        "facts": 12, "created": "2026-11-01T10:00:00+00:00"}))
    plan = (await c.post("/api/extract/plan", json={"path": "rfp.pdf", "doc_id": "d1"})).json()
    assert plan["stored"] == {"run": "d1/run_old", "facts": 12, "created": "2026-11-01T10:00:00+00:00"}


async def test_plan_errors(c, made):
    ok = {"path": "rfp.pdf", "doc_id": "d1", "votes": 3}
    assert (await c.post("/api/extract/plan", json={**ok, "votes": 2})).status_code == 400
    assert (await c.post("/api/extract/plan", json={**ok, "doc_id": " "})).status_code == 400
    assert (await c.post("/api/extract/plan", json={**ok, "path": "/etc/passwd"})).status_code == 400
    assert (await c.post("/api/extract/plan", json={"doc_id": "d1"})).status_code == 400
    assert (await c.post("/api/extract/plan", json={**ok, "upload_id": "abc"})).status_code == 400
    assert (await c.post("/api/extract/plan", json={"upload_id": "abc", "doc_id": "d1"})).status_code == 404


# --- extract -------------------------------------------------------------------------------------


async def test_extract_done(c, root, made, fake):
    r = await c.post("/api/extract", json={"path": "rfp.pdf", "deal_id": " deal ", "doc_id": "docX", "votes": 1, "confirm": True})
    assert r.status_code == 200
    j = await wait_job(c, r.json()["job_id"])
    assert j["status"] == "done" and j["error"] is None and j["run"] == "docX/run_new"
    assert j["result"] == "1 facts from 4 units in 1.5 s: 1 with all 1 votes agreed, 0 split; failed calls []" and j["seconds"] >= 0
    assert fake.calls == [{"deal_id": "deal", "doc_id": "docX", "model": None, "votes": 1, "refresh": True}]
    assert (await c.get("/api/facts", params={"run": j["run"]})).status_code == 200  # the frontend can open it


async def test_extract_with_upload_and_model(c, made, fake):
    up = (await c.post("/api/uploads", content=made.read_bytes())).json()
    r = await c.post("/api/extract", json={"upload_id": up["upload_id"], "deal_id": "d", "doc_id": "x", "model": "m1", "confirm": True})
    assert (await wait_job(c, r.json()["job_id"]))["status"] == "done"
    assert fake.calls[0]["model"] == "m1" and fake.calls[0]["votes"] == 3


async def test_extract_failed(root, made):
    app = create_app(root, chat_model=ScriptedChat([]), summary_model=Scripted(), extractor=Fake(fail=RuntimeError("boom")))
    async with client(app) as c:
        r = await c.post("/api/extract", json={"path": "rfp.pdf", "deal_id": "d", "doc_id": "x", "confirm": True})
        j = await wait_job(c, r.json()["job_id"])
        assert j["status"] == "failed" and j["error"] == "RuntimeError: boom" and j["run"] is None and j["result"] is None
        again = await c.post("/api/extract", json={"path": "rfp.pdf", "deal_id": "d", "doc_id": "x", "confirm": True})
        assert again.status_code == 200  # a failed job does not block the next


async def test_extract_refusals(c, made, fake):
    ok = {"path": "rfp.pdf", "deal_id": "d", "doc_id": "x", "confirm": True}
    r = await c.post("/api/extract", json={**ok, "confirm": False})
    assert r.status_code == 400 and "confirm" in r.json()["detail"]
    assert (await c.post("/api/extract", json={k: v for k, v in ok.items() if k != "confirm"})).status_code == 400
    r = await c.post("/api/extract", json={**ok, "deal_id": " "})
    assert r.status_code == 400 and "deal_id" in r.json()["detail"] and "doc_id" not in r.json()["detail"]
    r = await c.post("/api/extract", json={**ok, "deal_id": "", "doc_id": ""})
    assert "deal_id" in r.json()["detail"] and "doc_id" in r.json()["detail"]
    assert (await c.post("/api/extract", json={**ok, "votes": 4})).status_code == 400
    assert (await c.post("/api/extract", json={**ok, "path": "nope.pdf"})).status_code == 400
    assert (await c.get("/api/extract/zzz")).status_code == 404
    assert fake.calls == []


async def test_extract_needs_the_key_unless_a_fake_is_injected(root, made, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = create_app(root, chat_model=ScriptedChat([]), summary_model=Scripted())  # the real extractor
    async with client(app) as c:
        r = await c.post("/api/extract", json={"path": "rfp.pdf", "deal_id": "d", "doc_id": "x", "confirm": True})
        assert r.status_code == 400 and "OPENAI_API_KEY" in r.json()["detail"]


async def test_one_extraction_at_a_time(root, made):
    gate = threading.Event()
    fake = Fake(gate=gate)
    app = create_app(root, chat_model=ScriptedChat([]), summary_model=Scripted(), extractor=fake)
    body = {"path": "rfp.pdf", "deal_id": "d", "doc_id": "x", "confirm": True}
    async with client(app) as c:
        first = (await c.post("/api/extract", json=body)).json()["job_id"]
        assert (await c.get(f"/api/extract/{first}")).json()["status"] == "running"
        busy = await c.post("/api/extract", json=body)
        assert busy.status_code == 409 and "already running" in busy.json()["detail"]
        assert (await c.get("/api/status")).status_code == 200  # the server stays responsive
        gate.set()
        assert (await wait_job(c, first))["status"] == "done"
        assert (await c.post("/api/extract", json=body)).status_code == 200


@pytest.mark.parametrize("view", ["Bid", "After award"])
async def test_overview_and_facts_list_agree_per_view(c, view):
    """The Overview's per-category counts and the Facts page's list and CSV describe the same facts."""
    ov = (await c.get("/api/overview", params={"run": RUN, "view": view})).json()
    lst = (await c.get("/api/facts/list", params={"run": RUN, "view": view})).json()
    assert ov["by_category"] == lst["by_category"] and sum(ov["by_category"].values()) == lst["total"]
    csv = (await c.get("/api/facts.csv", params={"run": RUN, "view": view})).text
    assert len(csv.strip().splitlines()) == lst["total"] + 1

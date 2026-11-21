"""The routes that carry over the old review app (WEB_UI_SPEC.md 11.1). Offline: extraction is a fake."""

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
REPORT = {"run_id": "run1", "pages": 5, "seconds": {"total": 3.5, "extract": 2.0, "sweep": 1.0},
          "output_tokens": 120, "cache_hit_calls_2_to_n": 0.5, "failed_calls": [], "calls": [
              {"name": "LABEL1", "kind": "label", "status": "ok", "seconds": 1.2, "lines": 4, "usage": {"output_tokens": 10},
               "retries": 0, "log": ["a"], "output": "out"}]}
FAKE_REPORT = {"facts": 1, "by_status": {"valid": 1}, "seconds": {"total": 1.5}, "cache_hit_calls_2_to_n": 0.0,
               "failed_calls": 0}


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
    rep = {"buyer_brief": rep["summaries"]["buyer"]}  # older runs stored the buyer brief only
    other = make_run(root, "doc/old", facts=MORE)
    (other / "report.json").write_text(json.dumps(rep))
    s = (await c.get("/api/summaries", params={"run": "doc/old"})).json()["sections"][0]
    assert s["source"] == "extraction" and s["rows"][0]["text"] == "The County"


async def test_facts_list_filters_and_by_category(c):
    r = (await c.get("/api/facts/list", params={"run": RUN})).json()
    assert r["total"] == 8 == len(r["facts"]) and set(r["by_category"]) == {"B", "D", "Q", "R", "S", "O"}
    assert r["items"][0] == {"kind": "fact", "fact_ids": [r["facts"][0]["fact_id"]]}
    assert {"post_award", "affects_bid", "split"} <= set(r["facts"][0])
    by = {f["fact_id"]: f for f in r["facts"]}
    assert by["f_p1"]["post_award"] and by["f_p1"]["affects_bid"] and not by["f_d1"]["split"]
    d = (await c.get("/api/facts/list", params={"run": RUN, "categories": "D"})).json()
    assert d["total"] == 3 == len(d["items"]) and d["by_category"] == r["by_category"]  # chips ignore the category filter
    d = (await c.get("/api/facts/list", params={"run": RUN, "categories": "D,S", "statuses": "conflict"})).json()
    assert [f["fact_id"] for f in d["facts"]] == ["f_d1"] and d["by_category"] == {"D": 1}
    q = (await c.get("/api/facts/list", params={"run": RUN, "q": "email"})).json()
    assert [f["fact_id"] for f in q["facts"]] == ["f_s1"]
    cited = (await c.get("/api/facts/list", params={"run": RUN, "q": "SHALL GIVE support"})).json()
    assert [f["fact_id"] for f in cited["facts"]] == ["f_r1"]  # search reaches the cited text
    pg = (await c.get("/api/facts/list", params={"run": RUN, "page_from": 4, "page_to": 5})).json()
    assert {f["fact_id"] for f in pg["facts"]} == {"f_d2", "f_q1", "f_s1", "f_p1"}
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
    assert [f["fact_id"] for f in e["facts"]] == ["f_b1"] and e["facts"][0]["text"] == "County buys"
    grouped = [fact("f_g1", "R", "Item one", [cite("p1.1", 1, "a")]), fact("f_g2", "R", "Item two", [cite("p1.2", 1, "b")])]
    for g in grouped:
        g.update(group_id="g1", group_kind="list", group_title="Items")
    make_run(root, "doc/grp", facts=grouped)
    r = (await c.get("/api/facts/list", params={"run": "doc/grp"})).json()
    assert r["items"] == [{"kind": "list", "fact_ids": ["f_g1", "f_g2"]}] and r["total"] == 2
    one = (await c.get("/api/facts/list", params={"run": "doc/grp", "q": "two"})).json()
    assert one["items"] == [{"kind": "fact", "fact_ids": ["f_g2"]}]


async def test_facts_route_has_computed_booleans(c):
    f = (await c.get("/api/facts", params={"run": RUN})).json()["facts"][0]
    assert {"post_award", "affects_bid", "split"} <= set(f)


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
    assert row["document"] == "doc" and row["facts"] == 8 and row["total s"] == 3.5 and row["extract s"] == 2.0
    assert row["sweep and check s"] == 1.0 and row["output tokens"] == 120 and len(row["finished"]) == 16


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


async def test_attach_pdf_by_path_then_page_and_detach(c, root, made):
    assert (await c.get("/api/page", params={"run": RUN, "page": 1})).status_code == 404
    runs = (await c.get("/api/runs")).json()
    assert runs[0]["has_pdf"] is False and runs[0]["pdf_name"] is None
    r = await c.put("/api/pdf", params={"run": RUN}, json={"path": "rfp.pdf"})
    assert r.status_code == 200 and r.json() == {"has_pdf": True, "name": "rfp.pdf"}
    assert (root / RUN / "workspace" / "pdf.json").is_file()
    png = await c.get("/api/page", params={"run": RUN, "page": 2, "fact_id": "f_d1"})
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    runs = (await c.get("/api/runs")).json()
    assert runs[0]["has_pdf"] is True and runs[0]["pdf_name"] == "rfp.pdf"
    assert not (root / RUN / "source.pdf").exists()
    assert (await c.delete("/api/pdf", params={"run": RUN})).json() == {"has_pdf": False}
    assert (await c.get("/api/page", params={"run": RUN, "page": 1})).status_code == 404
    assert made.is_file()  # the picked file itself is never removed


async def test_attach_path_must_be_listed(c, tmp_path, made):
    (tmp_path / "sub").mkdir()
    make_pdf(tmp_path / "sub" / "deep.pdf")
    for bad in ("sub/deep.pdf", "/etc/passwd", "../rfp.pdf", "nope.pdf", str(tmp_path / "sub" / "deep.pdf"), ""):
        r = await c.put("/api/pdf", params={"run": RUN}, json={"path": bad})
        assert r.status_code == 400, bad
    assert (await c.put("/api/pdf", params={"run": RUN}, json={})).status_code == 400
    assert (await c.put("/api/pdf", params={"run": RUN}, json={"path": str(made.resolve())})).status_code == 200


async def test_attach_pdf_by_upload(c, root, tmp_path):
    src = tmp_path / "x.pdf"
    make_pdf(src)
    data = src.read_bytes()
    r = await c.put("/api/pdf", params={"run": RUN, "name": "../my rfp.pdf"}, content=data,
                    headers={"content-type": "application/pdf"})
    assert r.status_code == 200 and r.json() == {"has_pdf": True, "name": "my_rfp.pdf"}
    assert (root / RUN / "workspace" / "source.pdf").read_bytes() == data
    assert (await c.get("/api/page", params={"run": RUN, "page": 3})).status_code == 200
    assert (await c.get("/api/page", params={"run": RUN, "page": 9})).status_code == 404
    assert (await c.get("/api/runs")).json()[0]["pdf_name"] == "my_rfp.pdf"
    from fact_extractor.web.workspace import Workspace

    # The PDF viewer reads the tagged document.
    doc = Workspace(root / RUN / "facts.json").document()
    assert doc is not None and doc.page_count == 3
    await c.delete("/api/pdf", params={"run": RUN})
    assert not (root / RUN / "workspace" / "source.pdf").exists()
    assert Workspace(root / RUN / "facts.json").document() is None


async def test_upload_must_be_a_pdf_and_is_capped(c, root, monkeypatch):
    bad = await c.put("/api/pdf", params={"run": RUN}, content=b"hello", headers={"content-type": "application/pdf"})
    assert bad.status_code == 400 and "PDF" in bad.json()["detail"]
    broken = await c.put("/api/pdf", params={"run": RUN}, content=b"%PDF-1.4 nonsense", headers={"content-type": "application/pdf"})
    assert broken.status_code == 400
    from fact_extractor.web import server

    monkeypatch.setattr(server, "MAX_PDF", 10)
    big = await c.put("/api/pdf", params={"run": RUN}, content=b"%PDF" + b"0" * 20, headers={"content-type": "application/pdf"})
    assert big.status_code == 413
    assert (await c.post("/api/uploads", content=b"%PDF" + b"0" * 20)).status_code == 413
    assert not (root / RUN / "workspace" / "source.pdf").exists()


async def test_own_source_pdf_is_never_touched(c, root, made):
    make_pdf(root / "doc" / "source.pdf")  # shared by the document's runs
    before = (root / "doc" / "source.pdf").read_bytes()
    assert (await c.put("/api/pdf", params={"run": RUN}, json={"path": "rfp.pdf"})).status_code == 400
    assert (await c.put("/api/pdf", params={"run": RUN}, content=made.read_bytes(), headers={"content-type": "application/pdf"})).status_code == 400
    assert (await c.delete("/api/pdf", params={"run": RUN})).json() == {"has_pdf": True}
    assert (root / "doc" / "source.pdf").read_bytes() == before
    assert (await c.get("/api/runs")).json()[0]["pdf_name"] == "source.pdf"


async def test_attach_to_unknown_run(c, made):
    assert (await c.put("/api/pdf", params={"run": "nope"}, json={"path": "rfp.pdf"})).status_code == 404
    assert (await c.delete("/api/pdf", params={"run": "../.."})).status_code == 404


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
    assert plan["calls"][-1] == {"call": "CHECK", "times": 1, "units": plan["units"], "pages": "1-3"}
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
    assert j["result"] == "1 facts, {'valid': 1}, 1.5 s, cache hit 0.0, failed calls 0" and j["seconds"] >= 0
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

"""Every route of the web app, through FastAPI's ASGI interface. Offline: models are scripted."""

import json
import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import httpx
import pymupdf
from test_web_agent import ScriptedChat, call
from test_web_summaries import MORE, Scripted
from test_web_workspace import FACTS, make_run

from fact_extractor.web import server
from fact_extractor.web.server import create_app, resolve_run

RUN = "doc/run1"


def make_pdf(path):
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page().insert_text((72, 100), f"Page {i + 1} text")
    doc.save(str(path))
    doc.close()


@pytest.fixture
def root(tmp_path):
    folder = make_run(tmp_path / "runs", RUN, facts=MORE)
    make_pdf(folder.parent / "source.pdf")
    return tmp_path / "runs"


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def app(root):
    return create_app(root, chat_model=ScriptedChat(["hi"]), summary_model=Scripted())


@pytest.fixture
async def c(app):
    async with client(app) as c:
        yield c


async def test_status(c, root, monkeypatch):
    monkeypatch.setenv("FACT_EXTRACTOR_MODEL", "some-model")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert (await c.get("/api/status")).json() == {"model": "some-model", "has_key": True, "runs_folder": str(root)}
    monkeypatch.delenv("OPENAI_API_KEY")
    assert (await c.get("/api/status")).json()["has_key"] is False


async def test_runs_listing(c, root):
    other = make_run(root, "doc/other", facts=FACTS[:2])
    os.utime(other / "facts.json", (1, 1))
    (root / "doc" / "run1" / "facts_extra.json").write_text(json.dumps(FACTS))  # not a run folder file
    await c.patch("/api/facts/f_b1", params={"run": RUN}, json={"text": "x"})
    rows = (await c.get("/api/runs")).json()
    assert [r["run"] for r in rows] == [RUN, "doc/other"]
    first = rows[0]
    assert first == {"run": RUN, "doc_id": "doc", "run_id": "run1", "facts": len(MORE), "modified": first["modified"],
                     "has_pdf": True, "corrections": 1, "pdf_name": "source.pdf"}
    assert first["modified"].endswith("Z") and rows[1]["has_pdf"] is True and rows[1]["corrections"] == 0


async def test_facts_and_include_deleted(c):
    r = (await c.get("/api/facts", params={"run": RUN})).json()
    assert r["doc_id"] == "doc" and r["run_id"] == "run1" and len(r["facts"]) == len(MORE) and r["pages"] >= 5
    assert {"origin", "edited", "deleted", "original", "resolution", "corrections"} <= set(r["facts"][0])
    assert (await c.delete("/api/facts/f_r1", params={"run": RUN})).json() == {"ok": True}
    assert len((await c.get("/api/facts", params={"run": RUN})).json()["facts"]) == len(MORE) - 1
    both = (await c.get("/api/facts", params={"run": RUN, "include_deleted": 1})).json()["facts"]
    assert len(both) == len(MORE) and [f for f in both if f["fact_id"] == "f_r1"][0]["deleted"] is True


async def test_fact_writes(c):
    p = {"run": RUN}
    f = (await c.patch("/api/facts/f_d1", params=p, json={"text": "Bids due March 5", "reason": "customer"})).json()
    assert f["text"] == "Bids due March 5" and f["edited"] and f["original"]["text"] == "Bids due March 3"
    added = await c.post("/api/facts", params=p, json={"category": "R", "text": "Needs a license", "flags": ["mandatory"]})
    assert added.status_code == 200 and added.json()["origin"] == "user"
    restored = (await c.post("/api/facts/f_d1/restore", params=p)).json()
    assert restored["text"] == "Bids due March 3" and not restored["edited"]
    log = (await c.get("/api/corrections", params=p)).json()
    assert [e["op"] for e in log] == ["add", "edit"] and [e["undone"] for e in log] == [False, True]
    assert all(e["source"] == "ui" for e in log)


async def test_write_errors(c):
    p = {"run": RUN}
    assert (await c.patch("/api/facts/nope", params=p, json={"text": "x"})).status_code == 404
    assert (await c.delete("/api/facts/nope", params=p)).status_code == 404
    assert (await c.post("/api/facts/nope/restore", params=p)).status_code == 404
    bad = await c.patch("/api/facts/f_d1", params=p, json={"category": "Z"})
    assert bad.status_code == 400 and "category" in bad.json()["detail"]
    assert (await c.patch("/api/facts/f_d1", params=p, json={"text": ""})).status_code == 400
    assert (await c.patch("/api/facts/f_d1", params=p, json={})).status_code == 400
    assert (await c.patch("/api/facts/f_d1", params=p, json={"flags": ["x"]})).status_code == 400
    assert (await c.post("/api/facts", params=p, json={"category": "R"})).status_code == 400  # text missing
    r = await c.post("/api/facts", params=p, json={"category": "R", "text": " "})
    assert r.status_code == 400 and set(r.json()) == {"detail"}
    assert (await c.get("/api/facts")).status_code == 400  # run is required
    assert (await c.post("/api/corrections/c_nope/undo", params=p)).status_code == 404


async def test_corrections_and_undo(c):
    p = {"run": RUN}
    await c.patch("/api/facts/f_b1", params=p, json={"text": "one"})
    [entry] = (await c.get("/api/corrections", params=p)).json()
    assert entry["undone"] is False and entry["fact_text"] == "one" and entry["fact_id"] == "f_b1"
    assert (await c.post(f"/api/corrections/{entry['id']}/undo", params=p)).json() == {"ok": True}
    assert (await c.post(f"/api/corrections/{entry['id']}/undo", params=p)).status_code == 409
    [entry] = (await c.get("/api/corrections", params=p)).json()
    assert entry["undone"] is True and entry["fact_text"] == "Buyer is the County"


async def test_conflicts(c):
    p = {"run": RUN}
    [q] = (await c.get("/api/conflicts", params=p)).json()
    assert q["id"] == "q:f_q1" and q["status"] == "open" and len(q["options"]) == 2
    assert (await c.post("/api/conflicts/q:f_q1/resolve", params=p, json={"option": 5})).status_code == 400
    assert (await c.post("/api/conflicts/q:f_q1/resolve", params=p, json={})).status_code == 400
    assert (await c.post("/api/conflicts/q:nope/resolve", params=p, json={"option": 0})).status_code == 404
    assert (await c.post("/api/conflicts/q:f_q1/reopen", params=p)).status_code == 409
    done = (await c.post("/api/conflicts/q:f_q1/resolve", params=p, json={"option": 1})).json()
    assert done["status"] == "resolved" and done["resolution"]["label"] == "Page 5: Term"
    assert (await c.post("/api/conflicts/q:f_q1/resolve", params=p, json={"option": 0})).status_code == 409
    facts = {f["fact_id"]: f for f in (await c.get("/api/facts", params=p)).json()["facts"]}
    assert facts["f_d1"]["status"] == "valid" and "replaced" in facts["f_d1"]["flags"]
    assert facts["f_q1"]["resolution"]["text"] == "Bids are due March 5."
    reopened = (await c.post("/api/conflicts/q:f_q1/reopen", params=p)).json()
    assert reopened["status"] == "open"
    custom = (await c.post("/api/conflicts/q:f_q1/resolve", params=p, json={"text": "March 4"})).json()
    assert custom["resolution"] == {"option": None, "label": "Custom answer", "text": "March 4", "at": custom["resolution"]["at"]}


async def test_summaries_generate_and_background_rebuild(c, app):
    p = {"run": RUN}
    get = lambda: c.get("/api/summaries", params=p)
    by = lambda r, key: [x for x in r["sections"] if x["key"] == key][0]
    s = (await get()).json()
    assert s["updating"] is False and [x["key"] for x in s["sections"]] == [
        "buyer", "submission", "gates", "scoring", "questions", "contract", "requirements"]
    assert set(s["sections"][0]) == {"key", "title", "codes", "rows", "source", "generated_at", "stale", "updating",
                                     "fact_count", "uncovered", "error"}
    assert s["sections"][1]["source"] is None and s["sections"][1]["rows"] == []
    r = await c.post("/api/summaries/generate", params=p, json={"sections": ["submission"]})
    assert r.status_code == 200 and r.json()["updating"] is True
    assert (await c.post("/api/summaries/generate", params=p, json={"sections": ["dates"]})).status_code == 400
    await app.state.summaries.wait_idle()
    sub = by((await get()).json(), "submission")
    assert sub["source"] == "app" and sub["generated_at"] and not sub["stale"] and len(sub["rows"]) == 6
    assert set(sub["rows"][0]) == {"row", "text", "page", "fact_ids", "checked"}
    await c.patch("/api/facts/f_d1", params=p, json={"text": "Bids due March 9"})  # a write starts the rebuild
    assert (await get()).json()["updating"] is True
    await app.state.summaries.wait_idle()
    assert not by((await get()).json(), "submission")["stale"]
    assert by((await get()).json(), "contract")["rows"] == []  # never built: not rebuilt by a change
    assert (await c.post("/api/summaries/pin", params=p, json={"fact_ids": ["f_d2"]})).status_code in (404, 405)
    all_ = await c.post("/api/summaries/generate", params=p, json={})
    assert all_.json()["updating"] is True
    await app.state.summaries.wait_idle()
    assert all(x["generated_at"] for x in (await get()).json()["sections"])


async def test_page_image(c, root, monkeypatch):
    p = {"run": RUN}
    r = await c.get("/api/page", params={**p, "page": 1})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    seen = []
    real = server.render_page
    monkeypatch.setattr(server, "render_page", lambda pdf, page, boxes: seen.append(boxes) or real(pdf, page, boxes))
    assert (await c.get("/api/page", params={**p, "page": 9, "fact_id": "f_d2"})).status_code == 404  # the PDF has 3 pages
    seen.clear()
    ok = await c.get("/api/page", params={**p, "page": 3, "fact_id": "f_r1"})
    assert ok.status_code == 200 and seen == [[[1, 2, 30, 40]]]  # the fact's bbox on that page
    again = await c.get("/api/page", params={**p, "page": 3, "fact_id": "f_r1"})
    assert again.content == ok.content and len(seen) == 1  # cached
    other = await c.get("/api/page", params={**p, "page": 2, "fact_id": "f_r1"})
    assert other.status_code == 200 and seen[-1] == []  # the fact has nothing on page 2
    assert (await c.get("/api/page", params={**p, "page": 1, "fact_id": "nope"})).status_code == 404


async def test_page_without_pdf_is_404(tmp_path):
    folder = make_run(tmp_path / "runs", "x/y")
    async with client(create_app(tmp_path / "runs")) as c:
        assert (await c.get("/api/page", params={"run": "x/y", "page": 1})).status_code == 404
    assert folder.exists()


@pytest.mark.parametrize("run", ["../outside", "doc/../../outside", "/etc", "", "doc/run1/../../..", "..", "doc/nope",
                                 "doc\x00", "doc"])
async def test_run_parameter_cannot_escape(c, tmp_path, run):
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    (outside / "facts.json").write_text(json.dumps(FACTS))
    for path in ("/api/facts", "/api/conflicts", "/api/summaries", "/api/corrections", "/api/chat"):
        r = await c.get(path, params={"run": run})
        assert r.status_code == 404 and r.json() == {"detail": "no such run"}, (path, run)
    assert (await c.post("/api/summaries/generate", params={"run": run}, json={})).status_code == 404
    assert not (outside / "workspace").exists()


async def test_symlink_escape_is_404(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    outside = make_run(tmp_path, "elsewhere")
    (root / "link").symlink_to(outside, target_is_directory=True)
    async with client(create_app(root)) as c:
        assert (await c.get("/api/facts", params={"run": "link"})).status_code == 404
    with pytest.raises(Exception):
        resolve_run(root, "link")


def events_of(text):
    assert text.endswith("\n\n")
    out = []
    for block in text.split("\n\n")[:-1]:
        assert block.startswith("data: ") and "\n" not in block
        out.append(json.loads(block[len("data: "):]))
    return out


async def test_chat_stream_format_and_history(root):
    model = ScriptedChat([call("edit_fact", fact_id="f_d1", text="Bids due March 5", reason="customer")],
                         ["Changed ", "[f_d1]."])
    app = create_app(root, chat_model=model, summary_model=Scripted())
    async with client(app) as c:
        r = await c.post("/api/chat", params={"run": RUN}, json={"message": "The deadline is 5 March"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache"
        ev = events_of(r.text)
        assert [e["type"] for e in ev] == ["tool", "changed", "text", "text", "done"]
        assert ev[0] == {"type": "tool", "name": "edit_fact", "label": "Changed fact f_d1", "ok": True}
        assert ev[-1]["message"]["text"] == "Changed [f_d1]."
        hist = (await c.get("/api/chat", params={"run": RUN})).json()
        assert [m["role"] for m in hist] == ["user", "assistant"] and hist[0]["text"] == "The deadline is 5 March"
        assert hist[1]["tools"][0]["ok"] is True
        corr = (await c.get("/api/corrections", params={"run": RUN})).json()
        assert corr[0]["source"] == "chat" and corr[0]["fact_text"] == "Bids due March 5"
        assert (await c.post("/api/chat", params={"run": RUN}, json={"message": "  "})).status_code == 400
        assert (await c.post("/api/chat", params={"run": RUN}, json={})).status_code == 400
        assert (await c.delete("/api/chat", params={"run": RUN})).json() == {"ok": True}
        assert (await c.get("/api/chat", params={"run": RUN})).json() == []
        assert len((await c.get("/api/corrections", params={"run": RUN})).json()) == 1  # corrections stay
        await app.state.summaries.wait_idle()


async def test_chat_without_api_key_streams_error_then_done(root, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    async with client(create_app(root)) as c:
        r = await c.post("/api/chat", params={"run": RUN}, json={"message": "hi"})
        ev = events_of(r.text)
        assert ev[0] == {"type": "error", "message": "OPENAI_API_KEY is not set"} and ev[-1]["type"] == "done"
        s = await c.post("/api/summaries/generate", params={"run": RUN}, json={"sections": ["submission"]})
        assert s.status_code == 200


async def test_frontend_placeholder_when_not_built(c, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "STATIC", tmp_path / "missing")
    r = await c.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "npm --prefix web install && npm --prefix web run build" in r.text
    assert (await c.get("/api/status")).status_code == 200  # the API still wins
    assert (await c.get("/api/nothing")).status_code == 404


async def test_frontend_files_and_index_fallback(c, monkeypatch, tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>app</html>")
    (static / "assets" / "a.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("secret")
    monkeypatch.setattr(server, "STATIC", static)
    assert (await c.get("/")).text == "<html>app</html>"
    assert (await c.get("/assets/a.js")).text == "console.log(1)"
    assert (await c.get("/some/client/route")).text == "<html>app</html>"
    assert (await c.get("/")).headers["cache-control"] == "no-cache"
    assert (await c.get("/some/client/route")).headers["cache-control"] == "no-cache"
    assert "immutable" in (await c.get("/assets/a.js")).headers["cache-control"]
    assert "secret" not in (await c.get("/..%2fsecret.txt")).text
    assert "secret" not in (await c.get("/%2e%2e/secret.txt")).text
    r = await c.get("/api/unknown")
    assert r.status_code == 404 and r.json() == {"detail": "not found"}
    assert (await c.get("/api/facts", params={"run": RUN})).status_code == 200


def test_cli_web_reports_a_missing_extra(monkeypatch, capsys):
    import importlib.util

    from fact_extractor import cli

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "uvicorn" else real(name, *a))
    assert cli.main(["web"]) == 1
    assert "uv sync --extra web" in capsys.readouterr().err

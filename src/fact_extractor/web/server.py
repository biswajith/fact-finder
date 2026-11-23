"""The FastAPI app: JSON routes under /api, the chat stream, and the built frontend at /.

Routes follow WEB_UI_SPEC.md section 6. The server only ever reads a run's own files; every
change goes through `Workspace`. Needs the `web` extra (fastapi, uvicorn).
"""

from __future__ import annotations

import asyncio
import atexit
import json
import re
import secrets
import shutil
import tempfile
import threading
import time
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from .. import bid as B
from .. import classify, cutters, playbooks, results, stability
from . import has_api_key, model_name
from . import runs as R
from .agent import ChatModel, OpenAIChatModel, chat, check_fact
from .consistency import ConsistencyChecker
from .planning import Planning, planning_from_env
from .runs import find_runs, render_page
from .summaries import SECTIONS, CompletionModel, SummaryService
from .workspace import BadRequest, Conflict, NotFound, Workspace, WorkspaceError

STATIC = Path(__file__).parent / "static"
BUILD_COMMAND = "npm --prefix web install && npm --prefix web run build"
PAGE_CACHE = 32
MAX_PDF = 100 * 1024 * 1024
VOTES = (1, 3, 5)
BID_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
UPLOAD_TYPES = (".pdf", ".json", ".txt", ".md", ".csv", ".xlsx")
AUDIENCES = ("", "internal", "external")


class FactIn(BaseModel):
    category: str
    text: str
    flags: list[str] | None = None
    note: str | None = None
    citation_ids: list[str] | None = None


class FactPatch(BaseModel):
    text: str | None = None
    category: str | None = None
    flags: list[str] | None = None
    note: str | None = None
    reason: str | None = None


class Reason(BaseModel):
    reason: str | None = None


class ResolveIn(BaseModel):
    option: int | None = None
    text: str | None = None


class GenerateIn(BaseModel):
    sections: list[str] | None = None


class ChatIn(BaseModel):
    message: str


def resolve_run(root: Path, run: str) -> Path:
    """The facts.json of run `run` (a folder relative to `root`). Anything that leaves `root`
    (.., an absolute path, a symlink out) or has no facts.json is a 404."""
    try:
        if not run or run.startswith(("/", "\\")) or "\x00" in run or ".." in Path(run).parts:
            raise NotFound("no such run")
        folder = (root / run).resolve()
        if not folder.is_relative_to(root.resolve()):
            raise NotFound("no such run")
        facts = folder / "facts.json"
        if not facts.is_file():
            raise NotFound("no such run")
    except (OSError, ValueError) as e:
        raise NotFound("no such run") from e
    return facts


class PlanIn(BaseModel):
    path: str | None = None
    upload_id: str | None = None
    doc_id: str = ""
    votes: int = 3


class ExtractIn(BaseModel):
    path: str | None = None
    upload_id: str | None = None
    deal_id: str = ""
    doc_id: str = ""
    model: str | None = None
    votes: int = 3
    confirm: bool = False


class BidIn(BaseModel):
    name: str = ""
    deal_id: str = ""


class BidPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    team: list[dict] | None = None
    precedence: list[str] | None = None


class DocPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_id: str | None = None
    playbook: str | None = None
    issue_number: int | str | None = None
    issue_date: str | None = None
    previous: str | None = None
    confirmed: bool | None = None
    speakers: list[dict] | None = None
    speakers_confirmed: bool | None = None


class BidPlanIn(BaseModel):
    votes: int | None = None


class BidProcessIn(BaseModel):
    confirm: bool = False
    votes: int | None = None
    model: str | None = None


class RelationIn(BaseModel):
    reason: str | None = None


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _view(view: str) -> str:
    if view not in R.VIEWS:
        raise BadRequest(f"view must be one of: {', '.join(R.VIEWS)}")
    return view


def _ints(value: str, what: str) -> list[int]:
    try:
        return [int(v) for v in _csv(value)]
    except ValueError:
        raise BadRequest(f"{what} must be whole numbers separated by commas") from None


def fact_filters(q: str = "", categories: str = "", statuses: str = "", flags: str = "",
                 page_from: int | None = None, page_to: int | None = None, view: str = "All",
                 split_only: bool = False, edited: bool = False, include_deleted: bool = False,
                 docs: str = "", levels: str = "") -> dict:
    """The query parameters shared by /facts/list and /facts.csv. `docs` (document numbers) and
    `levels` only mean something in a bid."""
    pages = (page_from or 1, page_to or 10**9) if page_from or page_to else None
    return {"q": q, "categories": _csv(categories), "statuses": _csv(statuses), "flags": _csv(flags),
            "pages": pages, "view": _view(view), "split_only": split_only, "edited": edited,
            "include_deleted": include_deleted, "docs": _ints(docs, "docs"), "levels": _ints(levels, "levels")}


def with_computed(f: dict) -> dict:
    return {**f, "post_award": R.is_post_award(f), "affects_bid": R.affects_bid(f), "split": R.is_split(f)}


def filtered(ws: Workspace, p: dict, with_categories: bool = True) -> list[dict]:
    """Effective facts through every filter in `p` (the category filter only when asked), in document order."""
    state = ws.state()
    base = state.facts if p["include_deleted"] else state.visible()
    rows = R.filter_facts(base, p["categories"] if with_categories else None, p["statuses"], p["flags"],
                          p["q"], p["pages"], p["view"], p["split_only"])
    if p["edited"]:
        rows = [f for f in rows if f["edited"] or f["origin"] != "extracted"]
    if p["docs"]:
        rows = [f for f in rows if f.get("doc_no") in p["docs"]]
    if p["levels"]:
        rows = [f for f in rows if f.get("level") in p["levels"]]
    return R.document_order(rows)


async def read_body(request: Request) -> bytes:
    """The raw request body, refused with 413 as soon as it passes MAX_PDF bytes."""
    limit = MAX_PDF
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, "the file is larger than 100 MB")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > limit:
            raise HTTPException(413, "the file is larger than 100 MB")
    return bytes(data)


def check_pdf(data: bytes) -> int:
    """The page count of `data`; a 400 unless it is a readable PDF."""
    if not data.startswith(b"%PDF"):
        raise BadRequest("the file is not a PDF")
    import pymupdf

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            return doc.page_count
        finally:
            doc.close()
    except Exception as e:
        raise BadRequest("the file is not a readable PDF") from e


def check_upload(name: str, data: bytes) -> None:
    """A 400 unless `data` can be read as the kind of file its name says."""
    unreadable = BadRequest("the file could not be read")
    ext = Path(name.replace("\\", "/")).suffix.lower()
    if ext == ".pdf":
        check_pdf(data)
    elif ext == ".xlsx":
        import io

        try:
            from openpyxl import load_workbook

            load_workbook(io.BytesIO(data), read_only=True).close()
        except Exception as e:
            raise unreadable from e
    else:
        try:
            if not data.decode("utf-8-sig").strip():
                raise unreadable
        except UnicodeDecodeError as e:
            raise unreadable from e


def pdf_start(data: bytes, words: int = classify.FIRST_WORDS, pages: int = 5) -> str:
    """The text CLASSIFY reads of a PDF: its first pages, up to `words` words."""
    try:
        import pymupdf

        with pymupdf.open(stream=data, filetype="pdf") as doc:
            text = " \n".join(doc[i].get_text() for i in range(min(pages, doc.page_count)))
    except Exception:
        return ""
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())[: words * 8]


def safe_pdf_name(name: str) -> str:
    n = R.safe_name(Path(name.replace("\\", "/")).name)[:100] if name.strip() else "upload.pdf"
    return n if n.lower().endswith(".pdf") else n + ".pdf"


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _has_pdf(facts_path: Path) -> bool:
    """Whether the run has a source.pdf (in its own folder or its document's)."""
    return any(p.is_file() for p in (facts_path.parent / "source.pdf", facts_path.parent.parent / "source.pdf"))


def create_app(runs_folder: str | Path, chat_model: ChatModel | None = None,
               summary_model: CompletionModel | None = None, extractor: Callable | None = None,
               chat_planning: Planning | None = None, checker: ConsistencyChecker | None = None,
               classifier=None, bid_client=None) -> FastAPI:
    """Build the app. Models are injected by tests; otherwise the OpenAI-backed ones are created
    on first use, and a missing OPENAI_API_KEY shows up as a chat error or a section error.
    `extractor` replaces `runs.run_extraction` (the one call that spends tokens) in tests.
    `chat_planning` sets how each chat message is planned; with the real chat model and none
    given, it comes from FACT_EXTRACTOR_CHAT_PLANNING and _PLAN_APPROVAL. An injected chat model gets none unless passed.
    `classifier` (an LLMClient) answers CLASSIFY at upload to a bid; `bid_client` (an LLMClient) reads a bid's
    documents when it is processed. Without them the OpenAI client is used, and only when a key is set."""
    root = Path(runs_folder)
    extract_fn = extractor or R.run_extraction
    app = FastAPI(title="fact-extractor web", docs_url=None, redoc_url=None)
    app.state.summaries = summaries = SummaryService(summary_model)
    app.state.chat_model = chat_model or OpenAIChatModel()
    app.state.chat_planning = chat_planning if chat_planning is not None or chat_model is not None else planning_from_env()
    # Added facts are checked against existing ones (consistency.py); like planning, only with the real chat model
    # unless a checker is passed, so tests never call the API by accident.
    app.state.checker = checker if checker is not None or chat_model is not None else ConsistencyChecker()
    workspaces: dict[Path, Workspace] = {}
    pages: OrderedDict[tuple, bytes] = OrderedDict()
    uploads: dict[str, tuple[Path, str]] = {}  # upload_id -> (file, name), in a folder the app owns
    jobs: dict[str, dict] = {}
    jobs_lock = threading.Lock()
    upload_dir: list[Path] = []

    def ws_for(run: str) -> Workspace:
        facts = resolve_run(root, run)
        return workspaces.setdefault(facts, Workspace(facts))

    @app.exception_handler(WorkspaceError)
    async def _workspace_error(_: Request, e: WorkspaceError) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, e: RequestValidationError) -> JSONResponse:
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ())[1:])
        return JSONResponse({"detail": f"invalid request: {where} {first.get('msg', '')}".strip()}, status_code=400)

    def changed(ws: Workspace) -> None:
        summaries.notify_change(ws)

    def get_bid(bid_id: str) -> B.Bid:
        """The bid, or a 404. The ID is checked before it is used to make a path."""
        if not BID_ID.match(bid_id or ""):
            raise NotFound("no such bid")
        bid = B.Bid(root, bid_id)
        if not bid.exists():
            raise NotFound("no such bid")
        return bid

    def forget(bid: B.Bid) -> None:
        """Drop the cached workspace of the bid, so the next read loads the facts as they are now."""
        workspaces.pop(bid.folder.resolve() / "facts.json", None)

    def entry(d: dict) -> dict:
        """A document of the manifest with what is still missing before it may be read."""
        return {**d, "missing": B.ready(d)}

    def bid_view(bid: B.Bid, m: dict | None = None) -> dict:
        m = m or bid.manifest()
        pbs = [{"name": pb.name, "description": pb.description, "role": pb.role, "form": pb.cutter,
                "level": pb.level, "visibility": pb.visibility, "calls": list(pb.calls), "votes": pb.votes}
               for pb in playbooks.all()]
        return {**m, "documents": [entry(d) for d in m["documents"]], "order": [d["doc_id"] for d in B.issue_order(m)],
                "playbooks": pbs, "run": f"{B.BIDS}/{bid.bid_id}" if (bid.folder / "facts.json").is_file() else ""}

    def bid_pdf(bid: B.Bid, d: dict) -> Path | None:
        """The uploaded PDF of a document of the bid; None when it is another kind of file."""
        path = (bid.folder / d["file"]).resolve()
        if not str(d["file"]).lower().endswith(".pdf") or not path.is_file() or not path.is_relative_to(bid.folder.resolve()):
            return None
        return path

    def bid_documents(ws: Workspace) -> list[dict]:
        folder = ws.facts_path.parent
        bid = B.Bid(folder.parent.parent, folder.name)
        out = []
        for d in B.issue_order(bid.manifest()):
            if not d.get("run"):
                continue
            pb = playbooks.load(d["playbook"])
            out.append({"no": d["no"], "doc_id": d["doc_id"], "file_name": d["file_name"], "playbook": d["playbook"],
                        "level": pb.level, "visibility": pb.visibility, "issue_date": d.get("issue_date"),
                        "issue_number": d.get("issue_number"), "has_pdf": bid_pdf(bid, d) is not None})
        return out

    # --- runs ---
    @app.get("/api/status")
    async def status() -> dict:
        return {"model": model_name(), "has_key": has_api_key(), "runs_folder": str(root)}

    @app.get("/api/runs")
    async def runs() -> list[dict]:
        out = []
        for r in find_runs(root):
            run = str(r.path.parent.relative_to(root))
            corrections = Workspace(r.path).live_count() if (r.path.parent / "workspace").is_dir() else 0
            row = {"run": run, "doc_id": r.doc_id, "run_id": r.run_id, "facts": r.facts,
                   "modified": datetime.fromtimestamp(r.mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "has_pdf": _has_pdf(r.path), "corrections": corrections}
            if r.kind == "bid":  # an ordinary run's row stays as it was
                m = R._read_bid(r.path) or {}
                row.update(kind="bid", name=m.get("name") or r.doc_id, documents=r.documents,
                           has_pdf=any(str(d.get("file", "")).lower().endswith(".pdf") for d in m.get("documents") or []))
            out.append(row)
        return out

    @app.get("/api/runs/table")
    async def runs_table() -> list[dict]:
        return R.runs_table(find_runs(root))

    # --- facts ---
    @app.get("/api/facts")
    async def facts(run: str, include_deleted: int = 0) -> dict:
        ws = ws_for(run)
        r, state = ws.run(), ws.state()
        out = {"doc_id": r.doc_id, "run_id": r.run_id, "pages": r.pages,
               "facts": [with_computed(f) for f in (state.facts if include_deleted else state.visible())]}
        if ws.is_bid():
            out["documents"] = bid_documents(ws)
        return out

    @app.get("/api/facts/list")
    async def facts_list(run: str, p: dict = Depends(fact_filters)) -> dict:
        ws = ws_for(run)
        rows = filtered(ws, p)
        others = filtered(ws, p, with_categories=False)
        by_category = Counter(f["category"] for f in others)
        return {"total": len(rows), "by_category": dict(by_category),
                "items": [{"kind": it.kind, "fact_ids": [f["fact_id"] for f in it.facts]} for it in R.items(rows)]}

    @app.get("/api/facts.csv")
    async def facts_csv(run: str, audience: str = "", p: dict = Depends(fact_filters)) -> Response:
        if audience not in AUDIENCES:
            raise BadRequest(f"audience must be one of: {', '.join(a for a in AUDIENCES if a)}")
        ws = ws_for(run)
        r = ws.run()
        name = R.csv_name(r.doc_id, r.run_id)
        rows = filtered(ws, p)
        if audience == "external":
            rows, name = R.external_view(rows), name.replace("_facts.csv", "_facts_external.csv")
        return Response(R.to_csv(rows, bid=ws.is_bid()), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/overview")
    async def overview(run: str, view: str = "All") -> dict:
        ws = ws_for(run)
        _view(view)
        everything = ws.state().visible()
        facts = [f for f in everything if R.in_view(f, view)]
        return {
            "overview": R.overview(facts),
            "counts": {
                "needs_review": sum(f["status"] == "needs_review" for f in facts),
                "conflicts": sum(f["status"] == "conflict" for f in facts),
                "risk": sum("risk" in f["flags"] for f in facts),
                "mandatory": sum("mandatory" in f["flags"] for f in facts),
                "unclear": sum("unclear" in f["flags"] for f in facts),
            },
            "by_category": dict(Counter(f["category"] for f in facts)),
            "has_post_award": any(R.is_post_award(f) for f in everything),
            "views": list(R.VIEWS),
        }

    @app.get("/api/report")
    async def report(run: str) -> JSONResponse:
        rep = ws_for(run).run().report
        if rep is None:
            raise NotFound("this run has no report")
        return JSONResponse(rep)

    @app.get("/api/compare")
    async def compare(a: str, b: str) -> dict:
        ra, rb = Workspace(resolve_run(root, a)).run(), Workspace(resolve_run(root, b)).run()
        if ra.doc_id != rb.doc_id:
            raise BadRequest(f"the runs are of different documents ({ra.doc_id} and {rb.doc_id})")
        return {"agreement": stability.compare_runs(ra.records, rb.records),
                "code_differences": R.code_differences(ra.records, rb.records)}

    @app.post("/api/facts")
    async def add_fact(run: str, body: FactIn) -> dict:
        ws = ws_for(run)
        f = ws.add(body.model_dump(exclude_none=True), source="ui")
        check = await check_fact(ws, app.state.checker, f, "ui")
        changed(ws)
        return {**f, **({"check": check} if check else {})}

    @app.patch("/api/facts/{fact_id}")
    async def patch_fact(fact_id: str, run: str, body: FactPatch) -> dict:
        ws = ws_for(run)
        fields = body.model_dump(exclude_unset=True)
        reason = fields.pop("reason", None) or ""
        f = ws.edit(fact_id, fields, reason, source="ui")
        check = await check_fact(ws, app.state.checker, f, "ui", kind="edited") if "text" in fields else {}
        changed(ws)
        return {**f, **({"check": check} if check else {})}

    @app.delete("/api/facts/{fact_id}")
    async def delete_fact(fact_id: str, run: str, body: Reason | None = None) -> dict:
        ws = ws_for(run)
        ws.delete(fact_id, (body.reason if body else None) or "", source="ui")
        changed(ws)
        return {"ok": True}

    @app.post("/api/facts/{fact_id}/restore")
    async def restore_fact(fact_id: str, run: str) -> dict:
        ws = ws_for(run)
        f = ws.restore(fact_id, source="ui")
        changed(ws)
        return f

    # --- corrections and conflicts ---
    @app.get("/api/corrections")
    async def corrections(run: str) -> list[dict]:
        return ws_for(run).corrections()

    @app.post("/api/corrections/{entry_id}/undo")
    async def undo(entry_id: str, run: str) -> dict:
        ws = ws_for(run)
        ws.undo(entry_id, source="ui")
        changed(ws)
        return {"ok": True}

    @app.get("/api/conflicts")
    async def conflicts(run: str) -> list[dict]:
        return ws_for(run).state().conflicts

    @app.post("/api/conflicts/{conflict_id}/resolve")
    async def resolve(conflict_id: str, run: str, body: ResolveIn) -> dict:
        ws = ws_for(run)
        c = ws.resolve(conflict_id, body.option, body.text, source="ui")
        changed(ws)
        return c

    @app.post("/api/conflicts/{conflict_id}/reopen")
    async def reopen(conflict_id: str, run: str) -> dict:
        ws = ws_for(run)
        c = ws.reopen(conflict_id, source="ui")
        changed(ws)
        return c

    # --- summaries ---
    @app.get("/api/summaries")
    async def get_summaries(run: str) -> dict:
        return summaries.view(ws_for(run))

    @app.post("/api/summaries/generate")
    async def generate(run: str, body: GenerateIn | None = None) -> dict:
        ws = ws_for(run)
        keys = body.sections if body else None
        known = [s.key for s in SECTIONS]
        bad = [k for k in keys or [] if k not in known]
        if bad:
            raise HTTPException(400, f"unknown section {bad[0]}; sections: {', '.join(known)}")
        summaries.generate(ws, keys or None)
        return {"sections": summaries.sections(ws), "updating": True}

    # --- PDFs ---
    def under_cwd(path: str) -> Path:
        """`path` if it is one of the PDFs of the working directory (GET /pdfs), else a 400."""
        try:
            want = Path(path).resolve()
            ok = next((p for p in R.pdfs_in(".") if p.resolve() == want), None)
        except (OSError, ValueError):
            ok = None
        if ok is None:
            raise BadRequest("path must be one of the PDFs listed by /api/pdfs")
        return want

    @app.get("/api/pdfs")
    async def pdfs() -> list[dict]:
        return [{"path": str(p), "name": p.name} for p in R.pdfs_in(".")]

    @app.post("/api/uploads")
    async def upload(request: Request, name: str = "") -> dict:
        data = await read_body(request)
        n = check_pdf(data)
        if not upload_dir:
            upload_dir.append(Path(tempfile.mkdtemp(prefix="fact-extractor-uploads-")))
            atexit.register(shutil.rmtree, upload_dir[0], ignore_errors=True)
        upload_id = secrets.token_hex(8)
        file_name = safe_pdf_name(name)
        folder = upload_dir[0] / upload_id
        folder.mkdir()
        (folder / file_name).write_bytes(data)
        uploads[upload_id] = (folder / file_name, file_name)
        return {"upload_id": upload_id, "name": file_name, "pages": n}

    def source_bytes(path: str | None, upload_id: str | None) -> bytes:
        if bool(path) == bool(upload_id):
            raise BadRequest("give either path or upload_id")
        if upload_id:
            if upload_id not in uploads:
                raise NotFound("no such upload")
            return uploads[upload_id][0].read_bytes()
        return under_cwd(path or "").read_bytes()

    def plan_args(body: PlanIn | ExtractIn) -> tuple[bytes, str]:
        if body.votes not in VOTES:
            raise BadRequest(f"votes must be one of {', '.join(map(str, VOTES))}")
        data = source_bytes(body.path, body.upload_id)
        return data, body.doc_id.strip()

    @app.post("/api/extract/plan")
    async def extract_plan(body: PlanIn) -> dict:
        data, doc_id = plan_args(body)
        if not doc_id:
            raise BadRequest("doc_id is missing")
        try:
            doc = await asyncio.to_thread(R.tag_pdf, data, doc_id, root)
        except Exception as e:
            raise BadRequest(f"could not read this PDF: {e}") from e
        rows = R.plan_rows(doc, body.votes)
        found = await asyncio.to_thread(R.stored_result, data, doc_id, root)
        stored = None
        if found is not None:
            stored = {"run": str(found.folder.relative_to(root)), "facts": found.meta.get("facts"),
                      "created": found.meta.get("created")}
        return {"calls": rows, "total_calls": sum(r["times"] for r in rows), "units": len(doc.anchors),
                "stored": stored}

    def finish(job_id: str, **fields) -> None:
        with jobs_lock:
            jobs[job_id].update(fields, ended=time.monotonic())

    def work(job_id: str, data: bytes, body: ExtractIn) -> None:
        # run_extraction calls asyncio.run, so it runs in a thread of its own with no event loop.
        try:
            facts_path, rep, _ = extract_fn(
                data, deal_id=body.deal_id.strip(), doc_id=body.doc_id.strip(), model=(body.model or "").strip() or None,
                votes=body.votes, refresh=True, runs_root=root)
            finish(job_id, status="done", result=R.result_line(rep),
                   run=str(Path(facts_path).parent.resolve().relative_to(root.resolve())))
        except BaseException as e:
            finish(job_id, status="failed", error=f"{type(e).__name__}: {e}")

    @app.post("/api/extract")
    async def extract(body: ExtractIn) -> dict:
        if not body.confirm:
            raise BadRequest("confirm must be true: extracting calls the model and spends API tokens")
        if extractor is None and not has_api_key():
            raise BadRequest("OPENAI_API_KEY is not set")
        missing = [w for w, v in (("deal_id", body.deal_id.strip()), ("doc_id", body.doc_id.strip())) if not v]
        if missing:
            raise BadRequest(f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} missing")
        data, _ = plan_args(body)
        with jobs_lock:
            if any(j["status"] == "running" for j in jobs.values()):
                raise Conflict("an extraction is already running")
            job_id = secrets.token_hex(8)
            jobs[job_id] = {"status": "running", "started": time.monotonic(), "ended": None,
                            "result": None, "run": None, "error": None}
        threading.Thread(target=work, args=(job_id, data, body), daemon=True).start()
        return {"job_id": job_id}

    @app.get("/api/extract/{job_id}")
    async def extract_status(job_id: str) -> dict:
        with jobs_lock:
            j = jobs.get(job_id)
            if j is None:
                raise NotFound("no such extraction")
            end = j["ended"] if j["ended"] is not None else time.monotonic()
            return {"status": j["status"], "seconds": round(end - j["started"], 1), "result": j["result"],
                    "run": j["run"], "error": j["error"], "steps": [dict(s) for s in j.get("steps", [])]}

    # --- page image ---
    @app.get("/api/page")
    async def page(run: str, page: int, fact_id: str | None = None, doc: str | None = None) -> Response:
        ws = ws_for(run)
        f = None
        if fact_id:
            f = ws.state().get(fact_id)
            if f is None:
                raise NotFound(f"no fact {fact_id}")
        doc_id = ""
        if ws.is_bid():
            folder = ws.facts_path.parent
            bid = B.Bid(folder.parent.parent, folder.name)
            docs = B.issue_order(bid.manifest())
            if doc:
                found = next((d for d in docs if d["doc_id"] == doc), None)
                if found is None:
                    raise NotFound(f"no document {doc}")
            elif f is not None:
                cited = next((c["doc_id"] for c in f["citations"] if c["page"] == page and c["doc_id"]), "")
                found = next((d for d in docs if d["doc_id"] == cited), None)
                if found is None:
                    raise NotFound("this fact cites no document on that page")
            else:
                found = next((d for d in docs if bid_pdf(bid, d)), None)
                if found is None:
                    raise NotFound("this document has no page images")
            pdf = bid_pdf(bid, found)
            if pdf is None:
                raise NotFound("this document has no page images")
            doc_id = found["doc_id"]
        else:
            pdf = ws.run().pdf
            if pdf is None:
                raise NotFound("this run has no PDF")
        boxes: list = []
        if f is not None:
            boxes = [c["bbox"] for c in f["citations"] if c["page"] == page and c["bbox"] and (not doc_id or c["doc_id"] == doc_id)]
        key = (str(pdf), pdf.stat().st_mtime_ns, doc_id, page, json.dumps(boxes))
        png = pages.get(key)
        if png is None:
            try:
                png = await asyncio.to_thread(render_page, pdf, page, boxes)
            except (IndexError, ValueError) as e:
                raise NotFound(f"no page {page}") from e
            pages[key] = png
            while len(pages) > PAGE_CACHE:
                pages.popitem(last=False)
        else:
            pages.move_to_end(key)
        return Response(png, media_type="image/png")


    # --- bids: many documents, one fact list ---
    @app.get("/api/bids")
    async def list_bids() -> list[dict]:
        return B.list_bids(root)

    @app.post("/api/bids")
    async def create_bid(body: BidIn) -> dict:
        if not body.name.strip():
            raise BadRequest("name is missing")
        bid = B.create(root, body.name, body.deal_id.strip())
        return bid_view(bid)

    @app.get("/api/bids/{bid_id}")
    async def get_bid_route(bid_id: str) -> dict:
        bid = get_bid(bid_id)
        return bid_view(bid)

    @app.patch("/api/bids/{bid_id}")
    async def patch_bid(bid_id: str, body: BidPatch) -> dict:
        bid = get_bid(bid_id)
        fields = body.model_dump(exclude_unset=True)
        if "name" in fields and not (fields["name"] or "").strip():
            raise BadRequest("name must not be empty")
        team = None
        if "team" in fields:
            team, seen = [], set()
            for t in fields["team"] or []:
                name = t.get("name") if isinstance(t, dict) else None
                if not isinstance(name, str):
                    raise BadRequest("every team member needs a name")
                if name.strip() and name.strip().casefold() not in seen:
                    seen.add(name.strip().casefold())
                    team.append({"name": name.strip()})
        with bid.lock:
            m = bid.manifest()
            if "precedence" in fields:
                order = fields["precedence"] or None
                known = {d["doc_id"] for d in m["documents"]}
                if order is not None and (len(set(order)) != len(order) or not set(order) <= known):
                    raise BadRequest("precedence must list each document of the bid once, by its ID")
                rebuild = order != m.get("precedence")
                m["precedence"] = order
            else:
                rebuild = False
            if "name" in fields:
                m["name"] = fields["name"].strip()
            if team is not None:
                m["team"] = team
            bid.save(m)
            if team is not None:
                for d in m["documents"]:
                    if d.get("playbook") in playbooks.names() and not d["speakers_confirmed"] and not d.get("run"):
                        bid.refresh_speakers(d["no"])
        if rebuild and (bid.folder / "facts.json").is_file():
            await asyncio.to_thread(B.build, bid)
            forget(bid)
        return bid_view(bid)

    @app.post("/api/bids/{bid_id}/documents")
    async def upload_document(bid_id: str, request: Request, name: str = "") -> dict:
        bid = get_bid(bid_id)
        file_name = Path(name.replace("\\", "/")).name.strip()
        if Path(file_name).suffix.lower() not in UPLOAD_TYPES:
            raise BadRequest("this file type is not supported")
        data = await read_body(request)
        check_upload(file_name, data)
        try:
            doc = await asyncio.to_thread(bid.add_document, data, file_name)
        except ValueError as e:
            raise BadRequest(str(e)) from e
        client = classifier
        if client is None and has_api_key():
            try:
                from ..llm import OpenAIClient

                client = OpenAIClient()
            except Exception:
                client = None
        if client is not None:  # one small call; any failure leaves the rules' proposal
            try:
                text = pdf_start(data) if file_name.lower().endswith(".pdf") else classify.first_text(
                    cutters.cut(cutters.form_of(file_name, data), data, file_name))
                got = await classify.by_model(file_name, text, client, rules=doc["proposed"]) if text.strip() else None
                if got is not None:
                    doc = await asyncio.to_thread(bid.set_proposal, doc["no"], got)
            except Exception:
                pass
        return entry(bid.document(doc["no"]))

    def one_document(fn, *args, **kw) -> dict:
        try:
            return fn(*args, **kw)
        except KeyError as e:
            raise NotFound(str(e.args[0]) if e.args else "no such document") from e
        except ValueError as e:
            raise BadRequest(str(e)) from e

    @app.patch("/api/bids/{bid_id}/documents/{no}")
    async def patch_document(bid_id: str, no: int, body: DocPatch) -> dict:
        bid = get_bid(bid_id)
        fields = body.model_dump(exclude_unset=True)
        for key in ("doc_id", "playbook", "confirmed", "speakers", "speakers_confirmed"):
            if key in fields and fields[key] is None:
                raise BadRequest(f"{key} must not be null")
        return entry(one_document(bid.update_document, no, **fields))

    @app.delete("/api/bids/{bid_id}/documents/{no}")
    async def delete_document(bid_id: str, no: int) -> dict:
        bid = get_bid(bid_id)
        one_document(lambda: bid.remove_document(no) or {})
        return {"ok": True}

    def plan_bid(bid: B.Bid, votes: int | None) -> dict:
        m = bid.manifest()
        store = results.ResultStore(root)
        from .. import units as U

        planned, skipped = [], []
        for d in B.issue_order(m):
            if d.get("run"):
                continue
            if not d["confirmed"]:
                skipped.append({"no": d["no"], "doc_id": d["doc_id"], "why": "type not confirmed"})
                continue
            pb = playbooks.load(d["playbook"])
            row = {"no": d["no"], "doc_id": d["doc_id"], "file_name": d["file_name"], "playbook": d["playbook"],
                   "missing": B.ready(d), "units": 0, "calls": [], "total_calls": 0, "stored": None, "error": ""}
            try:
                data = bid.data(d)
                if pb.cutter == "pdf":
                    tagged = R.tag_pdf(data, d["doc_id"], root)
                else:
                    from ..api import document_from_units

                    tagged, _ = document_from_units(d["doc_id"], cutters.cut(pb.cutter, data, d["file_name"]))
                rows = R.plan_rows(tagged, votes, pb)
                row.update(units=len(tagged.anchors), calls=rows, total_calls=sum(r["times"] for r in rows))
                found = store.find(d["sha256"], U.VERSION, d["doc_id"], pb.key)
                if found is not None:
                    row["stored"] = {"run": str(found.folder.relative_to(root)), "facts": found.meta.get("facts"),
                                     "created": found.meta.get("created")}
            except Exception as e:
                row["error"] = f"could not read this document: {e}"
            planned.append(row)
        return {"documents": planned, "skipped": skipped, "relate_again": bid.needs_relate(m),
                "total_calls": sum(r["total_calls"] for r in planned)}

    def check_votes(votes: int | None) -> None:
        if votes is not None and votes not in VOTES:
            raise BadRequest(f"votes must be one of {', '.join(map(str, VOTES))}")

    @app.post("/api/bids/{bid_id}/plan")
    async def plan_route(bid_id: str, body: BidPlanIn | None = None) -> dict:
        bid = get_bid(bid_id)
        votes = body.votes if body else None
        check_votes(votes)
        return await asyncio.to_thread(plan_bid, bid, votes)

    def note_step(job_id: str, no: int, step: str, status: str, detail: str = "") -> None:
        with jobs_lock:
            jobs[job_id]["steps"].append({"doc_no": no, "step": step, "status": status, "detail": detail})

    def bid_work(job_id: str, bid: B.Bid, votes: int | None, model: str | None) -> None:
        """Read every ready document in issue order, run RELATE again where documents were added before
        others, then GROUP, the pair check and the fact list. One event loop for the whole job."""
        say = lambda *a: note_step(job_id, *a)  # noqa: E731

        async def go() -> tuple[int, list[str]]:
            client = bid_client
            if client is None:
                from ..llm import OpenAIClient

                client = OpenAIClient(model or None)
            store = results.ResultStore(root)
            m = bid.manifest()
            todo = [d for d in B.issue_order(m) if d["confirmed"] and not d.get("run")]
            skipped = [d for d in m["documents"] if not d["confirmed"] and not d.get("run")]
            say(0, "plan", "done", "reading " + (", ".join(f"d{d['no']}" for d in todo) or "nothing new") + (
                "; skipped, not confirmed: " + ", ".join(f"d{d['no']} {d['file_name']}" for d in skipped) if skipped else ""))
            failed: list[str] = []
            tried: set[int] = set()

            async def relate_again() -> None:
                for no in bid.needs_relate():
                    if no in tried:
                        continue
                    tried.add(no)
                    try:
                        await B.extract_document(bid, no, client, votes=votes, store=store, on_step=say, relate_only=True)
                    except Exception as e:
                        say(no, "relate", "failed", str(e))
                        failed.append(f"d{no}: {e}")

            for d in todo:
                try:
                    await B.extract_document(bid, d["no"], client, votes=votes, store=store, on_step=say)
                except Exception as e:  # marked failed in the manifest; the others go on
                    failed.append(f"d{d['no']}: {e}")
                    continue
                await relate_again()
            await relate_again()
            await B.settle(bid, client, app.state.checker, on_step=say)
            say(0, "build", "running")
            facts = B.build(bid)
            say(0, "build", "done", f"{len(facts)} facts")
            return len(facts), failed

        try:
            n, failed = asyncio.run(go())
            docs = [d for d in bid.manifest()["documents"] if d.get("run")]
            if not docs or not n:
                finish(job_id, status="failed", error="no document was extracted" + (": " + "; ".join(failed) if failed else ""))
            else:
                finish(job_id, status="done", run=f"{B.BIDS}/{bid.bid_id}",
                       result=f"{n} facts from {len(docs)} documents" + (f"; failed: {'; '.join(failed)}" if failed else ""))
        except BaseException as e:
            finish(job_id, status="failed", error=f"{type(e).__name__}: {e}")
        finally:
            forget(bid)

    @app.post("/api/bids/{bid_id}/process")
    async def process_route(bid_id: str, body: BidProcessIn) -> dict:
        bid = get_bid(bid_id)
        if not body.confirm:
            raise BadRequest("confirm must be true: reading the documents calls the model and spends API tokens")
        if bid_client is None and not has_api_key():
            raise BadRequest("OPENAI_API_KEY is not set")
        check_votes(body.votes)
        m = bid.manifest()
        waiting = [d for d in m["documents"] if d["confirmed"] and not d.get("run")]
        problems = [f"d{d['no']}: {', '.join(B.ready(d))}" for d in waiting if B.ready(d)]
        if problems:
            raise BadRequest("these documents are not ready: " + "; ".join(problems))
        if not waiting and not any(d.get("run") for d in m["documents"]):
            raise BadRequest("the bid has no confirmed document")
        with jobs_lock:
            if any(j["status"] == "running" for j in jobs.values()):
                raise Conflict("an extraction is already running")
            job_id = secrets.token_hex(8)
            jobs[job_id] = {"status": "running", "started": time.monotonic(), "ended": None,
                            "result": None, "run": None, "error": None, "steps": []}
        threading.Thread(target=bid_work, args=(job_id, bid, body.votes, (body.model or "").strip() or None),
                         daemon=True).start()
        return {"job_id": job_id}

    # --- relations and groups of a bid ---
    def touched(ws: Workspace, key: str, value: str) -> list[str]:
        """The IDs of the facts that now carry relation `value` (key "relation") or sit in group `value`."""
        if key == "relation":
            return [f["fact_id"] for f in ws.state().facts if any(r.get("id") == value for r in f.get("relations") or [])]
        return [f["fact_id"] for f in ws.state().facts if f.get("group_id") == value]

    def changed_facts(ws: Workspace, ids: list[str]) -> list[dict]:
        state = ws.state()
        return [with_computed(f) for f in (state.get(i) for i in ids) if f is not None]

    async def relation_change(run: str, rid: str, op: str, reason: str = "") -> dict:
        ws = ws_for(run)
        ids = touched(ws, "relation", rid)
        if op == "reject":
            await asyncio.to_thread(ws.reject_relation, rid, "ui", reason)
        else:
            await asyncio.to_thread(ws.restore_relation, rid, "ui")
        changed(ws)
        ids = ids or touched(ws, "relation", rid)
        return {"ok": True, "relation_id": rid, "rejected": op == "reject", "facts": changed_facts(ws, ids)}

    @app.post("/api/relations/{rid}/reject")
    async def reject_relation(rid: str, run: str, body: RelationIn | None = None) -> dict:
        return await relation_change(run, rid, "reject", (body.reason if body else None) or "")

    @app.post("/api/relations/{rid}/restore")
    async def restore_relation(rid: str, run: str) -> dict:
        return await relation_change(run, rid, "restore")

    async def group_change(run: str, gid: str, op: str, reason: str = "") -> dict:
        ws = ws_for(run)
        ids = touched(ws, "group", gid)
        if op == "ungroup":
            await asyncio.to_thread(ws.ungroup, gid, "ui", reason)
        else:
            await asyncio.to_thread(ws.regroup, gid, "ui")
        changed(ws)
        ids = ids or touched(ws, "group", gid)
        return {"ok": True, "group_id": gid, "ungrouped": op == "ungroup", "facts": changed_facts(ws, ids)}

    @app.post("/api/groups/{gid}/ungroup")
    async def ungroup(gid: str, run: str, body: RelationIn | None = None) -> dict:
        return await group_change(run, gid, "ungroup", (body.reason if body else None) or "")

    @app.post("/api/groups/{gid}/regroup")
    async def regroup(gid: str, run: str) -> dict:
        return await group_change(run, gid, "regroup")

    # --- chat ---
    @app.get("/api/chat")
    async def get_chat(run: str) -> list[dict]:
        return ws_for(run).chat()

    @app.get("/api/chat/sessions")
    async def chat_sessions(run: str) -> list[dict]:
        """Every chat session of the run, newest first, with its totals (chatlog.py)."""
        return ws_for(run).chat_sessions()

    @app.get("/api/chat/sessions/{session_id}")
    async def chat_session_events(run: str, session_id: str) -> dict:
        """One session's metadata and its full event log."""
        ws = ws_for(run)
        meta = next((s for s in ws.chat_sessions() if s["session_id"] == session_id), None)
        return {"session": meta, "events": ws.chat_events(session_id)}

    @app.delete("/api/chat/sessions/{session_id}")
    async def delete_chat_session(run: str, session_id: str) -> dict:
        """Delete one session's log; deleting the current session also clears the chat."""
        return ws_for(run).delete_chat_session(session_id)

    @app.delete("/api/chat/sessions")
    async def delete_chat_sessions(run: str) -> dict:
        """Delete every session log of the run and clear the chat."""
        return ws_for(run).delete_chat_sessions()

    @app.delete("/api/chat")
    async def clear_chat(run: str) -> dict:
        ws_for(run).clear_chat()
        return {"ok": True}

    @app.post("/api/chat")
    async def post_chat(run: str, body: ChatIn) -> StreamingResponse:
        ws = ws_for(run)
        if not body.message.strip():
            raise HTTPException(400, "message must not be empty")

        async def events() -> AsyncIterator[str]:
            async for ev in chat(ws, summaries, app.state.chat_model, body.message.strip(), app.state.chat_planning,
                                 app.state.checker):
                yield sse(ev)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --- frontend (registered last, so every API route wins) ---
    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "not found")
        index = STATIC / "index.html"
        if not index.is_file():
            return HTMLResponse(
                "<!doctype html><title>fact-extractor web</title><h1>The frontend is not built</h1>"
                f"<p>Run <code>{BUILD_COMMAND}</code> from the repository root, then reload.</p>"
                "<p>The API is running at <code>/api/status</code>.</p>", status_code=200)
        target = (STATIC / path).resolve()
        if path and target.is_file() and target.is_relative_to(STATIC.resolve()):
            # hashed bundles under assets/ never change; everything else (index.html) must revalidate
            cc = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cc})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


def serve(runs_folder: str, port: int) -> None:
    import uvicorn

    app = create_app(runs_folder)
    print(f"fact-extractor web: http://127.0.0.1:{port}  (runs folder: {runs_folder})")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

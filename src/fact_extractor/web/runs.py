"""Everything the workspace does with runs that is not layout: find and load runs, filter,
summarise, export CSV, render a PDF page with highlights, compare runs, start a run.

No FastAPI import here, so all of it is tested with plain pytest.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import shutil
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..models import CATEGORIES
from .. import results
from ..results import safe_name

CSV_COLUMNS = (
    "category", "category_name", "text", "flags", "status", "page_labels", "sections",
    "citation_ids", "source_text", "note", "problems", "fact_id",
)


@dataclass(frozen=True)
class RunRef:
    path: Path  # <runs folder>/<doc>/<run>/facts.json
    label: str  # path relative to the runs folder
    facts: int
    mtime: float
    doc_id: str
    run_id: str


@dataclass
class Run:
    path: Path
    records: list[dict]
    report: dict | None
    pdf: Path | None  # source.pdf beside the facts file, if any
    doc_id: str
    run_id: str
    pages: int
    source: Path | None = None  # the stored source file of any form (source.pdf, source.json, ...)


# --- finding and loading runs ---------------------------------------------------------


def _read_facts(path: Path) -> list | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _read_report(path: Path) -> dict | None:
    """The report.json beside a facts file, or None when it is missing or unreadable."""
    try:
        with open(path.parent / "report.json", encoding="utf-8") as f:
            rep = json.load(f)
    except (OSError, ValueError):
        return None
    return rep if isinstance(rep, dict) else None


def find_runs(folder: str | Path) -> list[RunRef]:
    """Every run under `folder` (a `<doc>/<run>/facts.json`), newest first. A facts file that is
    not a JSON list is skipped."""
    root = Path(folder)
    if not root.is_dir():
        return []
    out = []
    for p in root.glob("*/*/facts.json"):
        data = _read_facts(p)
        if data is None:
            continue
        first = data[0] if data and isinstance(data[0], dict) else {}
        out.append(RunRef(
            path=p, label=str(p.relative_to(root)), facts=len(data), mtime=p.stat().st_mtime,
            doc_id=str(first.get("doc_id", "")), run_id=str(first.get("run_id", "")),
        ))
    out.sort(key=lambda r: (-r.mtime, r.label))
    return out


def runs_table(runs: list[RunRef]) -> list[dict]:
    """One row per run with how long it took, newest first (the order of `find_runs`).
    Stage seconds and output tokens come from each run's report; empty without one."""
    rows = []
    for r in runs:
        rep = _read_report(r.path) or {}
        secs = rep.get("seconds") if isinstance(rep.get("seconds"), dict) else {}
        tokens = rep.get("output_tokens")
        rows.append({
            "run": r.label.removesuffix("/facts.json"), "document": r.doc_id, "facts": r.facts,
            "total s": secs.get("total") if isinstance(secs.get("total"), (int, float)) else None,
            "output tokens": tokens if isinstance(tokens, int) else None,
            "finished": datetime.fromtimestamp(r.mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return rows


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def cite_key(c: dict) -> tuple[str, str]:
    """A citation names a unit of one document: the pair (document ID, unit ID)."""
    return (str(c.get("doc_id") or ""), str(c.get("id") or ""))


def normalize(records: list[dict]) -> list[dict]:
    """Give every record every field the app reads, with an empty value where it has none
    (user-added facts, `also` = null, test fixtures), so the rest of the app can index them directly."""
    out = []
    for i, r in enumerate(records):
        cites = []
        for c in r.get("citations") or []:
            page = c.get("page")
            cites.append({
                "doc_id": c.get("doc_id") or r.get("doc_id") or "",
                "doc_no": _int(c.get("doc_no") or r.get("doc_no")),
                "id": str(c.get("id", "")),
                "page": page if isinstance(page, int) else None,
                "page_label": str(c.get("page_label") or (page if page is not None else "")),
                "section": c.get("section") or "",
                "text": c.get("text") or "",
                "bbox": c.get("bbox") or None,
                "speaker": c.get("speaker") or "",
                "side": c.get("side") or "",
                "level": _int(c.get("level")),
                "visibility": c.get("visibility") or "external",
            })
        out.append({
            **r,
            "fact_id": r.get("fact_id") or str(i + 1),
            "category": r["category"],
            "text": r["text"],
            "citations": cites,
            "flags": list(r.get("flags") or []),
            "status": r.get("status") or "valid",
            "note": r.get("note") or "",
            "source_call": r.get("source_call") or "",
            "problems": list(r.get("problems") or []),
            "conflicts": list(r.get("conflicts") or []),
            "unresolved_ids": list(r.get("unresolved_ids") or []),
            "doc_id": r.get("doc_id") or "",
            "run_id": r.get("run_id") or "",
            # unit-label pipeline: the votes behind the code, and where the text came from
            "votes": list(r.get("votes") or []),
            "agreement": r.get("agreement") or "",
            "also": r.get("also") or "",
            "text_from": r.get("text_from") or "",
            # groups: the same point restated ("same"), or items of one list ("list")
            "group_id": r.get("group_id") or "",
            "group_kind": r.get("group_kind") or "",
            "group_title": r.get("group_title") or "",
        })
    return out


def load_run(path: str | Path) -> Run:
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        records = normalize(json.load(f))
    report = _read_report(path)
    # The PDF sits beside the run, or one level up when a document's runs share it.
    pdf = next((p for p in (path.parent / "source.pdf", path.parent.parent / "source.pdf") if p.is_file()), None)
    first = records[0] if records else {}
    doc_id = first.get("doc_id") or (report or {}).get("doc_id") or path.parent.name
    run_id = first.get("run_id") or (report or {}).get("run_id") or path.stem
    pages = (report or {}).get("pages") or max(
        (c["page"] for r in records for c in r["citations"] if c["page"]), default=1
    )
    source = pdf or next(
        (p for d in (path.parent, path.parent.parent) for ext in results.SOURCE_SUFFIXES
         if (p := d / f"source{ext}").is_file()),
        None,
    )
    return Run(path, records, report, pdf, doc_id, run_id, int(pages), source)


# --- filtering and ordering: before the bid, after award ------------------------------

POST_AWARD = "post-award"
VIEWS = ("All", "Bid", "After award")
_MONEY = re.compile(r"[$€£]\s?\d|\b\d[\d,.]*\s*(?:million|thousand|percent|%)", re.I)


def is_split(r: dict) -> bool:
    """The labelling votes did not all give this fact the same code: worth a look."""
    return len(set(r["votes"])) > 1


def is_post_award(r: dict) -> bool:
    return POST_AWARD in r["flags"]


def affects_bid(r: dict) -> bool:
    """An after-award obligation the bid team still has to weigh now: it is flagged as a
    risk, or it states an amount that belongs in the price."""
    return is_post_award(r) and ("risk" in r["flags"] or bool(_MONEY.search(r["text"])))


def in_view(r: dict, view: str) -> bool:
    """Bid: everything to know, decide or submit before the deadline, plus the after-award
    obligations that change the price or the risk. After award: every obligation of the winner."""
    if view == "Bid":
        return not is_post_award(r) or affects_bid(r)
    if view == "After award":
        return is_post_award(r)
    return True


def filter_facts(
    records: list[dict],
    categories: list[str] | None = None,
    statuses: list[str] | None = None,
    flags: list[str] | None = None,
    query: str = "",
    pages: tuple[int, int] | None = None,
    view: str = "All",
    split_only: bool = False,
) -> list[dict]:
    """Empty or None arguments do not filter. Flags match on any; pages on any citation."""
    q = query.strip().lower()
    out = []
    for r in records:
        if not in_view(r, view):
            continue
        if split_only and not is_split(r):
            continue
        if categories and r["category"] not in categories:
            continue
        if statuses and r["status"] not in statuses:
            continue
        if flags and not set(flags) & set(r["flags"]):
            continue
        if q and q not in r["text"].lower() and not any(q in c["text"].lower() for c in r["citations"]):
            continue
        if pages and not any(c["page"] and pages[0] <= c["page"] <= pages[1] for c in r["citations"]):
            continue
        out.append(r)
    return out


_ID = re.compile(r"^p(\d+)\.(?:(\d+)|h(\d+)|t(\d+)r(\d+))$")


def id_position(cid: str) -> tuple:
    """Sort key of a source ID: page, number, then plain sentences before headings and
    table rows of the same number. Unknown shapes sort last on their page."""
    m = _ID.match(cid)
    if not m:
        return (10**9, 10**9, 9, 0, cid)
    page = int(m.group(1))
    if m.group(2):
        return (page, int(m.group(2)), 0, 0, "")
    if m.group(3):
        return (page, int(m.group(3)), 1, 0, "")
    return (page, int(m.group(4)), 2, int(m.group(5)), "")


def document_order(records: list[dict]) -> list[dict]:
    """By first citation: page, then position in the ID. Facts without citations go last."""

    def key(r: dict) -> tuple:
        if not r["citations"]:
            return (10**9, (10**9, 10**9, 9, 0, ""))
        c = r["citations"][0]
        return (c["page"] or 10**9, id_position(c["id"]))

    return sorted(records, key=key)


def page_labels(r: dict) -> str:
    return "; ".join(dict.fromkeys(c["page_label"] for c in r["citations"] if c["page_label"]))


# --- groups ---------------------------------------------------------------------------


@dataclass
class Item:
    """What the lists show: one fact, one point stated in several places ("same"), or
    the items of one list ("list"). `facts` is in document order."""

    kind: str  # "fact", "same" or "list"
    title: str
    facts: list[dict]

    @property
    def first(self) -> dict:
        return self.facts[0]

    def pages(self) -> str:
        return "; ".join(dict.fromkeys(c["page_label"] for f in self.facts for c in f["citations"] if c["page_label"]))


def items(records: list[dict]) -> list[Item]:
    """Collapse grouped facts, keeping the order of `records`: a group sits where its first
    member is. A group with only one member in `records` (the others filtered out) is
    shown as the plain fact it is."""
    members: dict[str, list[dict]] = {}
    for r in records:
        if r["group_id"]:
            members.setdefault(r["group_id"], []).append(r)
    out: list[Item] = []
    done: set[str] = set()
    for r in records:
        gid = r["group_id"]
        if not gid or len(members[gid]) < 2:
            out.append(Item("fact", r["text"], [r]))
        elif gid not in done:
            done.add(gid)
            out.append(Item(r["group_kind"] or "list", r["group_title"] or r["text"], members[gid]))
    return out


# --- Overview screen: buyer, gates, clarifications, scoring, calendar -----------------


def _entries(records: list[dict]) -> list[dict]:
    """Lines for a Summary card: a fact, a repeated point once, or a list with its items."""
    out = []
    for it in items(document_order(records)):
        if it.kind == "list":
            out.append({
                "text": it.title, "page": it.pages(),
                "children": [{"text": f["text"], "page": page_labels(f)} for f in it.facts],
            })
        else:
            out.append({"text": it.first["text"], "page": it.pages(), "children": []})
    return out


def buyer_rows(records: list[dict], brief: list[dict] | None) -> list[dict]:
    """A section summary's rows: a row's text when it was checked against the facts it
    cites, otherwise those facts themselves. Empty when the run has no summary."""
    by_id = {r["fact_id"]: r for r in records}
    rows = []
    for b in brief or []:
        cited = [by_id[i] for i in b.get("fact_ids", []) if i in by_id]
        if b.get("text") and b.get("checked"):
            text = b["text"]
        elif cited:
            text = " ".join(dict.fromkeys(f["text"] for f in cited))  # the model's wording failed the check
        else:
            text = ""
        rows.append({
            "row": b["row"], "text": text,
            "page": "; ".join(dict.fromkeys(p for f in cited for p in page_labels(f).split("; ") if p)),
        })
    return rows


def calendar(records: list[dict]) -> dict:
    """Date facts in time order. A fact goes under the first calendar date it names; one
    with no date of its own ("30 days after award") is kept apart, in document order."""
    from ..normalize import values

    dated, undated = [], []
    seen: set[str] = set()
    for it in items(document_order([r for r in records if r["category"] == "D"])):
        for f in ([it.first] if it.kind == "same" else it.facts):
            tokens = values(f["text"])
            days = sorted(t.split(":", 1)[1] for t in tokens if t.startswith("date:"))
            times = sorted(t.split(":", 1)[1] for t in tokens if t.startswith("time:"))
            page = it.pages() if it.kind == "same" else page_labels(f)
            if not days:
                undated.append({"text": f["text"], "page": page})
                continue
            if f["text"] in seen:
                continue
            seen.add(f["text"])
            when = datetime.strptime(days[0], "%Y-%m-%d")
            dated.append({
                "date": days[0], "label": f"{when:%a} {when.day} {when:%b %Y}",
                "time": times[0] if times and len(days) == 1 else "", "text": f["text"], "page": page,
            })
    dated.sort(key=lambda d: (d["date"], d["time"] or "99:99"))
    return {"dated": dated, "undated": undated}


def overview(records: list[dict]) -> dict:
    """The fact lists the Overview screen shows. The row summaries come from the summaries API."""
    def of(code: str) -> list[dict]:
        return [r for r in records if r["category"] == code]

    contradictions = [
        {"text": r["text"], "page": " vs ".join(c["page_label"] or "?" for c in r["citations"]), "children": []}
        for r in document_order(of("Q"))
    ]
    return {
        "buyer_facts": _entries(of("B")),
        "gates": _entries(of("G")),
        "disqualifiers": _entries(of("X")),
        "submission": _entries(of("S")),  # how to package and deliver the proposal
        "contradictions": contradictions,
        "unclear": _entries([r for r in records if "unclear" in r["flags"] and r["category"] != "Q"]),
        # The lists of criteria first, then the single statements about how scoring works.
        "scoring": sorted(_entries(of("E")), key=lambda e: not e["children"]),
        "calendar": calendar(records),
    }


# --- CSV ------------------------------------------------------------------------------


def csv_row(r: dict) -> dict:
    cites = r["citations"]
    return {
        "category": r["category"],
        "category_name": CATEGORIES.get(r["category"], ""),
        "text": r["text"],
        "flags": "; ".join(r["flags"]),
        "status": r["status"],
        "page_labels": page_labels(r),
        "sections": "; ".join(dict.fromkeys(c["section"] for c in cites if c["section"])),
        "citation_ids": "; ".join(c["id"] for c in cites),
        "source_text": " / ".join(c["text"] for c in cites),
        "note": r["note"],
        "problems": "; ".join(r["problems"]),
        "fact_id": r["fact_id"],
    }


def to_csv(records: list[dict]) -> bytes:
    """UTF-8 with a byte order mark, so Excel reads it as UTF-8."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    for r in records:
        w.writerow(csv_row(r))
    return buf.getvalue().encode("utf-8-sig")


def csv_name(doc_id: str, run_id: str) -> str:
    return f"{safe_name(doc_id)}_{safe_name(run_id)}_facts.csv"


# --- page image -----------------------------------------------------------------------


def render_page(pdf: str | Path | bytes, page: int, boxes: list, zoom: float = 1.5) -> bytes:
    """PNG of 1-based `page` with each box ([x0, y0, x1, y1], PDF points, top-left
    origin) drawn as a translucent highlight. Boxes that are None are skipped. The
    document is changed in memory only; the file on disk is never written."""
    import pymupdf

    doc = pymupdf.open(stream=pdf) if isinstance(pdf, bytes) else pymupdf.open(str(pdf))
    try:
        p = doc[page - 1]
        for b in boxes:
            if not b:
                continue
            r = pymupdf.Rect(*b)
            r = pymupdf.Rect(r.x0 - 1.5, r.y0 - 1.5, r.x1 + 1.5, r.y1 + 1.5)
            p.draw_rect(r, color=(0.85, 0.45, 0.0), fill=(1.0, 0.85, 0.0), fill_opacity=0.35, width=0.8)
        return p.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
    finally:
        doc.close()


# --- comparing runs -------------------------------------------------------------------


def code_differences(a: list[dict], b: list[dict]) -> list[dict]:
    """Source IDs both runs cite but file under different codes, in document order."""

    def index(records: list[dict]) -> tuple[dict[str, set[str]], dict[str, list[str]]]:
        codes: dict[str, set[str]] = defaultdict(set)
        texts: dict[str, list[str]] = defaultdict(list)
        for r in records:
            for c in r["citations"]:
                codes[c["id"]].add(r["category"])
                if r["text"] not in texts[c["id"]]:
                    texts[c["id"]].append(r["text"])
        return codes, texts

    ca, ta = index(a)
    cb, tb = index(b)
    out = []
    for i in sorted(set(ca) & set(cb), key=id_position):
        if ca[i] != cb[i]:
            out.append({
                "id": i,
                "codes_a": "".join(sorted(ca[i])),
                "codes_b": "".join(sorted(cb[i])),
                "facts_a": " / ".join(ta[i]),
                "facts_b": " / ".join(tb[i]),
            })
    return out


# --- new run --------------------------------------------------------------------------


def result_line(report: dict) -> str:
    """The one-line result `fact-extractor extract` prints."""
    r = report
    return (
        f"{r['facts']} facts from {r['ids']} units in {r['seconds']['total']} s: "
        f"{r['facts_votes_agreed']} with all {r['votes']} votes agreed, {r['facts_votes_split']} split; "
        f"failed calls {r['failed_calls']}"
    )


def new_run_id() -> str:
    """Same shape as units.extract's default run ID."""
    return f"run_{datetime.now(timezone.utc):%Y_%m_%d}_{uuid.uuid4().hex[:6]}"


@contextmanager
def staged_pdf(pdf_bytes: bytes, runs_root: str | Path = "runs"):
    """A path to `pdf_bytes` for read_pdf, which needs a file: written under
    `runs/.staging/` (the app writes nowhere else) and removed afterwards."""
    root = Path(runs_root)
    staging = root / ".staging"
    made_root = not root.exists()
    staging.mkdir(parents=True, exist_ok=True)
    path = staging / f"{uuid.uuid4().hex}.pdf"
    try:
        path.write_bytes(pdf_bytes)
        yield path
    finally:
        path.unlink(missing_ok=True)
        for d in (staging, root) if made_root else (staging,):
            try:
                d.rmdir()  # only when empty
            except OSError:
                pass


def tag_pdf(pdf_bytes: bytes, doc_id: str, runs_root: str | Path = "runs"):
    from ..pdf import read_pdf
    from ..tagging import tag_pages

    with staged_pdf(pdf_bytes, runs_root) as path:
        return tag_pages(doc_id, read_pdf(str(path)))


def plan_rows(doc, votes: int = 3) -> list[dict]:
    """The calls of the first round of one extraction: every unit labelled `votes` times and
    stated once, one contradiction check and one cross-reference call. All are sent together.
    The group and summary calls that follow depend on the facts found and are not listed."""
    from .. import units

    cfg = units.Config()

    def pages(ids: list[str]) -> str:
        first, last = doc.anchors[ids[0]].page, doc.anchors[ids[-1]].page
        return f"{first}-{last}"

    rows = [
        {"call": f"LABEL{k}", "times": votes, "units": len(ids), "pages": pages(ids)}
        for k, ids in enumerate(units.chunks(doc, cfg.units_per_label_call), start=1)
    ]
    rows += [
        {"call": f"STATE{k}", "times": 1, "units": len(ids), "pages": pages(ids)}
        for k, ids in enumerate(units.chunks(doc, cfg.units_per_state_call), start=1)
    ]
    whole = {"times": 1, "units": len(doc.anchors), "pages": f"1-{doc.page_count}"}
    return rows + [{"call": "CHECK", **whole}, {"call": "XREF", **whole}]


def stored_result(pdf_bytes: bytes, doc_id: str, runs_root: str | Path = "runs"):
    """The stored result for this PDF and doc ID under the current pipeline, or None."""
    from .. import results, units

    return results.ResultStore(runs_root).find(results.pdf_hash(pdf_bytes), units.VERSION, doc_id)


def run_extraction(
    pdf_bytes: bytes,
    *,
    deal_id: str,
    doc_id: str,
    model: str | None,
    votes: int = 3,
    refresh: bool = False,
    runs_root: str | Path = "runs",
    client=None,
    cfg=None,
    source_name: str | None = None,
) -> tuple[Path, dict, bool]:
    """What `fact-extractor extract` does: return the stored result for this PDF, or
    extract and store it under `runs/<doc_id>/<run_id>/`.

    Returns the facts path, the report, and whether the result came from the store
    (then no model was called). On an exception nothing is left on disk.
    """
    from .. import units

    root = Path(runs_root)
    store = results.ResultStore(root)
    sha = results.pdf_hash(pdf_bytes)
    stored = store.find(sha, units.VERSION, doc_id, "rfp@1")
    if stored and not refresh:
        return stored.facts_path, stored.report(), True
    made_root = not root.exists()
    try:
        doc = tag_pdf(pdf_bytes, doc_id, root)
        if client is None:
            from ..llm import OpenAIClient

            client = OpenAIClient(model or None)
        result = asyncio.run(units.extract(
            doc, client, deal_id=deal_id, cfg=cfg or units.Config(votes=votes), run_id=new_run_id(),
        ))
    except BaseException:
        if made_root:
            shutil.rmtree(root, ignore_errors=True)
        raise
    saved = store.save(
        pdf_bytes, sha, units.VERSION, result, result.labels,
        playbook="rfp@1", source_name=source_name or f"{doc_id}.pdf", units=doc,
    )
    return saved.facts_path, result.report, False


def pdfs_in(folder: str | Path = ".") -> list[Path]:
    return sorted(Path(folder).glob("*.pdf"))

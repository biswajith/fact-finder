"""Corrections on top of an extraction run: the log, the effective facts, the conflicts.

The run's own files are never touched (WEB_UI_SPEC.md section 2). Everything the customer
changes goes to `<run folder>/workspace/`: `corrections.jsonl` (append-only), `summaries.json`,
`chat.jsonl`, and `chat/<session id>/` (one folder per chat session: `session.json` and the
append-only `events.jsonl` that agent.py writes for every turn). The effective state is always recomputed by replaying the log over the base
facts, which is what makes undo exact: cancelling an entry just removes it from the replay.

`replay` is pure (no files, no model). `Workspace` wraps one run folder with a lock.
No FastAPI import here.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from ..models import CATEGORIES, FLAGS
from .pricing import fill_costs
from .runs import Run, document_order, load_run, normalize

EDITABLE = ("text", "category", "flags", "note")
SESSION_ID = re.compile(r"^s_[0-9a-f]{12}$")
CUSTOM_LABEL = "Custom answer"


# --- errors: each carries the HTTP status the server answers with ---------------------


class WorkspaceError(Exception):
    status = 400


class BadRequest(WorkspaceError):
    status = 400


class NotFound(WorkspaceError):
    status = 404


class Conflict(WorkspaceError):
    status = 409


# --- small helpers ----------------------------------------------------------------------


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str, hex_len: int = 8) -> str:
    return f"{prefix}{uuid.uuid4().hex[:hex_len]}"


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def atomic_write(path: Path, text: str) -> None:
    """Write to a temp file beside `path` and rename it over, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex[:6]}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_jsonl(path: Path) -> list[dict]:
    """Every object line of a jsonl file; blank or damaged lines are skipped."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def append_jsonl(path: Path, objs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in objs)
    with open(path, "a", encoding="utf-8") as f:
        f.write(data)


# --- validation of customer input -------------------------------------------------------


def clean_fields(fields: dict, require_text: bool = False) -> dict:
    """Validate and normalise the fields of an edit or add. Unknown keys and bad values are a 400."""
    out: dict = {}
    for key, value in fields.items():
        if key == "text":
            if not isinstance(value, str) or not value.strip():
                raise BadRequest("text must not be empty")
            out["text"] = value.strip()
        elif key == "category":
            if value not in CATEGORIES:
                raise BadRequest(f"category must be one of {', '.join(CATEGORIES)}")
            out["category"] = value
        elif key == "flags":
            if not isinstance(value, list) or any(f not in FLAGS for f in value):
                raise BadRequest(f"flags must be a list of: {', '.join(FLAGS)}")
            out["flags"] = list(dict.fromkeys(value))
        elif key == "note":
            if not isinstance(value, str):
                raise BadRequest("note must be text")
            out["note"] = value.strip()
        else:
            raise BadRequest(f"cannot change '{key}'; allowed: {', '.join(EDITABLE)}")
    if require_text and "text" not in out:
        raise BadRequest("text must not be empty")
    return out


# --- replay -------------------------------------------------------------------------------


def live_entries(log: list[dict]) -> list[dict]:
    """The entries that count: not an undo, and not cancelled by a live undo. Undoing an undo
    brings the first entry back, so the log is read from the end."""
    undone: set[str] = set()
    for e in reversed(log):
        if e.get("op") == "undo" and e.get("id") not in undone:
            undone.add(str(e.get("target")))
    return [e for e in log if e.get("op") != "undo" and e.get("id") not in undone]


def undone_ids(log: list[dict]) -> set[str]:
    live = {e.get("id") for e in live_entries(log)}
    return {e["id"] for e in log if e.get("op") != "undo" and e.get("id") not in live}


@dataclass
class State:
    facts: list[dict]  # effective facts in document order, deleted ones included
    conflicts: list[dict]  # open first
    live: list[dict] = field(default_factory=list)
    before: dict[str, dict] = field(default_factory=dict)  # edit entry ID -> the edited fields' values just before it

    def get(self, fact_id: str) -> dict | None:
        return next((f for f in self.facts if f["fact_id"] == fact_id), None)

    def visible(self) -> list[dict]:
        return [f for f in self.facts if not f["deleted"]]

    def conflict(self, conflict_id: str) -> dict | None:
        return next((c for c in self.conflicts if c["id"] == conflict_id), None)


def _blank(rec: dict) -> dict:
    out = copy.deepcopy(rec)
    out.update(origin="extracted", edited=False, deleted=False, original=None, resolution=None, corrections=[])
    return out


def option_label(c: dict) -> str:
    return f"Page {c['page_label']}: {c['section']}"


def _source_conflicts(base: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for q in base:
        if q["category"] != "Q":
            continue
        linked = [r["fact_id"] for r in base if q["fact_id"] in r["conflicts"]]
        cid = f"q:{q['fact_id']}"
        out[cid] = {
            "id": cid, "kind": "source", "title": q["text"], "description": "The document contradicts itself.",
            "fact_ids": [q["fact_id"], *linked],
            "options": [
                {"label": option_label(c), "text": c["text"],
                 "citation": {k: c[k] for k in ("id", "page", "page_label", "section")}, "changes": []}
                for c in q["citations"]
            ],
            "status": "open", "resolution": None,
        }
    return out


def _user_fact(entry: dict, template: dict, doc) -> dict:
    """A customer-written fact. Citations come from the tagged document when it has the IDs."""
    f = entry.get("fields") or {}
    cites, unresolved = [], []
    anchors = getattr(doc, "anchors", {}) if doc is not None else {}
    for cid in f.get("citation_ids") or []:
        a = anchors.get(cid)
        if a is not None:
            cites.append(a.citation())
        else:
            unresolved.append(cid)
    rec = normalize([{
        "fact_id": entry["fact_id"], "doc_id": template.get("doc_id", ""), "run_id": template.get("run_id", ""),
        "deal_id": template.get("deal_id", ""), "category": f["category"], "text": f["text"],
        "flags": f.get("flags") or [], "note": f.get("note") or "", "citations": cites,
        "unresolved_ids": unresolved, "source_call": "user", "status": "valid",
    }])[0]
    rec.update(origin="user", edited=False, deleted=False, original=None, resolution=None, corrections=[entry["id"]])
    if cites and cites[0].get("doc_no"):  # a fact added in a bid sits with the document it cites
        rec.update(doc_no=cites[0]["doc_no"], level=cites[0]["level"])
    return rec


class _Cited:
    """An anchor of a bid's document, cited as `d<no>:<unit>`: its citation says which document,
    at which level, and who may see it."""

    def __init__(self, anchor, doc_no: int, level: int, visibility: str) -> None:
        self.anchor, self.extra = anchor, {"doc_no": doc_no, "level": level, "visibility": visibility}

    def citation(self) -> dict:
        return {**self.anchor.citation(), **self.extra}


class _BidAnchors:
    """`anchors` of a bid: the units of each extracted document, found by `d<no>:<unit ID>` and
    read from the document's stored units when first asked for."""

    TOKEN = re.compile(r"^d(\d+):(.+)$")

    def __init__(self, folder: Path) -> None:
        self.folder, self._docs = folder, {}

    def _doc(self, no: int):
        if no not in self._docs:
            from .. import bid as B
            from .. import playbooks
            from ..results import load_document

            self._docs[no] = None
            try:
                m = json.loads((self.folder / "bid.json").read_text(encoding="utf-8"))
                d = next(d for d in m["documents"] if d["no"] == no and d.get("run"))
                tagged = load_document(self.folder.parent.parent / d["run"], d["doc_id"])
                pb = playbooks.load(d["playbook"])
                if tagged is not None:
                    self._docs[no] = (tagged, pb, B)
            except (OSError, ValueError, StopIteration, KeyError):
                pass
        return self._docs[no]

    def get(self, key, default=None):
        m = self.TOKEN.match(key or "")
        found = self._doc(int(m[1])) if m else None
        anchor = found[0].anchors.get(m[2]) if found else None
        if anchor is None:
            return default
        tagged, pb, B = found
        return _Cited(anchor, int(m[1]), B.citation_level(pb, {"side": anchor.side}), pb.visibility)


def _document_conflict(raw: dict) -> dict:
    """A conflict derived for a document (`conflicts.json`, written by `bid.build`) as the workspace
    shows it. Its ID is fixed, so a choice the user made stays attached to it."""
    return {
        "id": raw["id"], "kind": "document", "title": raw.get("title", ""), "description": raw.get("description", ""),
        "fact_ids": list(raw.get("fact_ids") or []),
        "options": [{"label": o.get("label", ""), "text": o.get("text", ""), "citation": o.get("citation"),
                     "changes": copy.deepcopy(o.get("changes") or []), **({"question": True} if o.get("question") else {})}
                    for o in raw.get("options") or []],
        "status": "open", "resolution": None, "reason": raw.get("reason", ""), "doc_id": raw.get("doc_id", ""),
        "closed_by": raw.get("closed_by") or "", "note": "", "acknowledged": "",
    }


def _settle(c: dict) -> None:
    """A conflict a later buyer document settled shows as resolved, unless the user had already
    resolved it: then it shows open again, because the answer they chose may no longer hold."""
    if c["kind"] != "document" or not c["closed_by"]:
        return
    if c["status"] == "open":
        c["status"] = "resolved"
        c["resolution"] = {"option": None, "label": f"Settled by {c['closed_by']}", "text": "", "at": ""}
    elif c["acknowledged"] != c["closed_by"]:  # the user chose before this document settled it
        c["previous_resolution"] = c["resolution"]
        c["status"], c["resolution"], c["note"] = "open", None, "A later document changes this"


def _resolve_source(c: dict, entry: dict, facts: dict[str, dict], derived: set[str]) -> None:
    f = entry.get("fields") or {}
    option = f.get("option")
    opts = c["options"]
    if option is None:
        label, text, chosen = CUSTOM_LABEL, str(f.get("text") or ""), None
    else:
        label, text, chosen = opts[option]["label"], opts[option]["text"], option
    c["status"] = "resolved"
    c["resolution"] = {"option": chosen, "label": label, "text": text, "at": entry["at"]}
    qid = c["fact_ids"][0]
    if qid in facts:
        facts[qid]["resolution"] = {"conflict_id": c["id"], "label": label, "text": text, "at": entry["at"]}
    winners = {opts[chosen]["citation"]["id"]} if chosen is not None else set()
    losers = {o["citation"]["id"] for i, o in enumerate(opts) if i != chosen} - winners
    for fid in c["fact_ids"][1:]:
        fact = facts.get(fid)
        if fact is None:
            continue
        if fact["status"] == "conflict":
            fact["status"] = "valid"
        cited = {x["id"] for x in fact["citations"]}
        if chosen is not None and cited & losers and not cited & winners and "replaced" not in fact["flags"]:
            fact["flags"] = [*fact["flags"], "replaced"]
            derived.add(fid)  # set by the customer's choice, not an edit of the flags


def _resolve_raised(c: dict, entry: dict) -> None:
    f = entry.get("fields") or {}
    option = f.get("option")
    if option is None:
        label, text = CUSTOM_LABEL, str(f.get("text") or "")
    else:
        label, text = c["options"][option]["label"], c["options"][option]["text"]
    c["status"] = "resolved"
    c["resolution"] = {"option": option, "label": label, "text": text, "at": entry["at"]}
    if c["kind"] == "document":
        c["acknowledged"] = f.get("acknowledged") or ""


def _describe(e: dict) -> str:
    """A line for the corrections list about an entry that has no fact of its own."""
    f = e.get("fields") or {}
    if e.get("op") == "reject_relation":
        return f"Rejected the relation {f.get('kind', '')}: {f.get('from', '')} to {f.get('to', '')}".replace("  ", " ")
    n = f.get("facts")
    what = f.get("title") or (f"{n} facts" if n else f.get("group_id", ""))
    return f"Ungrouped: {what}"


def _choice(c: dict | None, fields: dict) -> str | None:
    """What a resolve entry chose, in words: the option's label or the customer's own answer."""
    option = fields.get("option")
    if option is None:
        return f"Your own answer: {fields.get('text') or ''}"
    if c is not None and isinstance(option, int) and 0 <= option < len(c["options"]):
        return c["options"][option]["label"]
    return None


def _without_orphans(log: list[dict], live: list[dict]) -> list[dict]:
    """Drop the edits and deletes that came from choosing an option of a raised conflict when the
    choice itself (the `resolve` entry logged just before them) is no longer live. A conflict can
    be resolved, reopened and resolved again; each change belongs to the resolve before it."""
    live_ids = {e["id"] for e in live}
    owner: dict[str, str] = {}
    for e in log:
        cid = e.get("conflict_id")
        if e.get("op") == "resolve":
            owner[cid] = e["id"]
        elif e.get("op") in ("edit", "delete") and cid and owner.get(cid) not in live_ids:
            live_ids.discard(e["id"])
    return [e for e in live if e["id"] in live_ids]


def replay(base: list[dict], log: list[dict], doc=None, derived: list[dict] | None = None) -> State:
    """Effective facts and conflicts: the base records with the live log entries applied in order.

    An edit or delete that came from resolving a raised conflict only counts while that
    resolve entry is live, so reopening a conflict takes its changes back with it.
    `before` holds, for every edit entry (undone ones too), the values it replaced at that point.
    `derived` is the content of a bid's `conflicts.json`: each becomes a conflict of kind
    "document", resolved like a raised one. An `ungroup` entry clears the group of its facts.
    """
    live = _without_orphans(log, live_entries(log))
    live_ids = {e["id"] for e in live}
    before: dict[str, dict] = {}
    facts = {r["fact_id"]: _blank(r) for r in base}
    originals = {r["fact_id"]: r for r in base}
    conflicts = _source_conflicts(base)
    for raw in derived or []:
        if isinstance(raw, dict) and raw.get("id") and any(f in facts for f in raw.get("fact_ids") or []):
            conflicts[raw["id"]] = _document_conflict(raw)
    derived_ids: set[str] = set()
    template = base[0] if base else {}
    for e in log:
        op, fid = e.get("op"), e.get("fact_id")
        if op == "edit" and fid in facts:
            before[e["id"]] = {k: copy.deepcopy(facts[fid].get(k)) for k in e.get("fields") or {}}
        if e.get("id") not in live_ids:
            continue
        if op == "add":
            facts[fid] = _user_fact(e, template, doc)
        elif op in ("edit", "delete") and fid in facts:
            facts[fid]["corrections"].append(e["id"])
            if op == "delete":
                facts[fid]["deleted"] = True
            else:
                for k, v in (e.get("fields") or {}).items():
                    facts[fid][k] = list(v) if isinstance(v, list) else v
        elif op == "ungroup":
            for f in facts.values():
                if f.get("group_id") and f["group_id"] == (e.get("fields") or {}).get("group_id"):
                    f["group_id"], f["group_kind"], f["group_title"] = "", "", ""
        elif op == "raise":
            fields = e.get("fields") or {}
            conflicts[e["conflict_id"]] = {
                "id": e["conflict_id"], "kind": "raised", "title": fields.get("title", ""),
                "description": fields.get("description", ""), "fact_ids": list(fields.get("fact_ids") or []),
                "options": [{"label": o.get("label", ""), "text": o.get("text", ""), "citation": o.get("citation"),
                             "changes": list(o.get("changes") or [])} for o in fields.get("options") or []],
                "status": "open", "resolution": None,
            }
        elif op == "resolve":
            c = conflicts.get(e.get("conflict_id"))
            if c is None:
                continue
            if c["kind"] == "source":
                _resolve_source(c, e, facts, derived_ids)
            else:
                _resolve_raised(c, e)
    for fid, fact in facts.items():
        if fact["origin"] == "extracted":
            b = originals[fid]
            now_flags = [x for x in fact["flags"] if not (fid in derived_ids and x == "replaced" and x not in b["flags"])]
            diff = {k: copy.deepcopy(b[k]) for k in EDITABLE if (now_flags if k == "flags" else fact[k]) != b[k]}
            fact["original"] = diff or None
            fact["edited"] = bool(diff)
        else:
            fact["edited"] = len(fact["corrections"]) > 1
    for c in conflicts.values():
        if c["kind"] == "source" and c["fact_ids"][0] in facts:
            c["title"] = facts[c["fact_ids"][0]]["text"]
        _settle(c)
    ordered = document_order(list(facts.values()))
    gone = {f["fact_id"] for f in ordered if f["deleted"]}
    shown = [c for c in conflicts.values() if not (c["kind"] == "source" and c["fact_ids"][0] in gone)]
    shown.sort(key=lambda c: c["status"] != "open")
    return State(ordered, shown, live, before)


# --- one run folder -------------------------------------------------------------------------


class Workspace:
    """A run folder and its `workspace/` folder. All reads and writes go through one lock."""

    def __init__(self, facts_path: Path) -> None:
        self.facts_path = facts_path
        self.dir = facts_path.parent / "workspace"
        self.lock = threading.RLock()
        self._run: Run | None = None
        self._stamp: tuple | None = None
        self._doc = None
        self._bid_anchors: SimpleNamespace | None = None
        self._doc_pdf: tuple | None = None
        self._doc_loaded = False
        self._state: State | None = None
        self._state_key: tuple | None = None

    # files
    @property
    def corrections_path(self) -> Path:
        return self.dir / "corrections.jsonl"

    @property
    def summaries_path(self) -> Path:
        return self.dir / "summaries.json"

    @property
    def chat_path(self) -> Path:
        return self.dir / "chat.jsonl"

    @property
    def conflicts_path(self) -> Path:
        """The conflicts code derived for the documents of a bid (`bid.build` writes it)."""
        return self.facts_path.parent / "conflicts.json"

    def is_bid(self) -> bool:
        """This run folder is a bid: `bid.json` sits beside `facts.json`."""
        return (self.facts_path.parent / "bid.json").is_file()

    def _rebuild_bid(self) -> None:
        """Derive the bid's facts again (a rejected relation changes which facts are replaced)."""
        if self.is_bid():
            from .. import bid as B

            folder = self.facts_path.parent
            B.build(B.Bid(folder.parent.parent, folder.name))

    # the extraction (read only)
    def run(self) -> Run:
        """The loaded run; read again when the facts file changed on disk."""
        with self.lock:
            st = self.facts_path.stat()
            stamp = (st.st_mtime_ns, st.st_size)
            if self._run is None or stamp != self._stamp:
                self._run, self._stamp = load_run(self.facts_path), stamp
            return self._run

    def document(self):
        """The tagged document of the run: rebuilt from its stored units when it has them, else read
        from its PDF; None without either. Built once; slow on first use for a PDF."""
        with self.lock:
            if self.is_bid():  # a bid has many documents; the pages of each are read from its own result
                return None
            run = self.run()
            pdf = run.pdf
            has_units = (self.facts_path.parent / "units.json").is_file()
            if not self._doc_loaded or (pdf, has_units) != self._doc_pdf:
                self._doc, self._doc_pdf = None, (pdf, has_units)
                if has_units:
                    from ..results import load_document

                    self._doc = load_document(self.facts_path.parent, run.doc_id)
                if self._doc is None and pdf is not None:
                    from ..pdf import read_pdf
                    from ..tagging import tag_pages

                    self._doc = tag_pages(self.run().doc_id, read_pdf(str(pdf)))
                self._doc_loaded = True
            return self._doc

    def labels(self) -> dict[str, dict]:
        """The labelling pass of this run by unit ID (label, votes, flags), or {} for a run without labels.json."""
        try:
            rows = json.loads((self.facts_path.parent / "labels.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {r["id"]: r for r in rows if isinstance(r, dict) and "id" in r}

    # the log
    def log(self) -> list[dict]:
        return read_jsonl(self.corrections_path)

    def live_count(self) -> int:
        return len(live_entries(self.log()))

    def state(self) -> State:
        """The replayed log, kept until the facts file or the log changes. Shared:
        callers must not change the facts or conflicts it holds."""
        with self.lock:
            run = self.run()
            try:
                st = self.corrections_path.stat()
                log_stamp = (st.st_mtime_ns, st.st_size)
            except FileNotFoundError:
                log_stamp = None
            try:
                st = self.conflicts_path.stat()
                conflicts_stamp = (st.st_mtime_ns, st.st_size)
            except FileNotFoundError:
                conflicts_stamp = None
            key = (self._stamp, log_stamp, conflicts_stamp)
            if self._state is None or key != self._state_key:
                log = self.log()
                needs_doc = any(e.get("op") == "add" and (e.get("fields") or {}).get("citation_ids") for e in log)
                derived = None
                if conflicts_stamp is not None:
                    try:
                        derived = json.loads(self.conflicts_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        derived = None
                    if not isinstance(derived, list):
                        derived = None
                doc = None
                if needs_doc and self.is_bid():
                    if self._bid_anchors is None:
                        self._bid_anchors = SimpleNamespace(anchors=_BidAnchors(self.facts_path.parent))
                    doc = self._bid_anchors
                elif needs_doc:
                    doc = self.document()
                self._state, self._state_key = replay(run.records, log, doc, derived), key
            return self._state

    def _entry(self, op: str, source: str, **kw) -> dict:
        if source not in ("chat", "ui", "document"):
            raise BadRequest("source must be chat, ui or document")
        return {"id": new_id("c_"), "at": now(), "source": source, "op": op, "fact_id": None, "fields": {},
                "reason": "", "conflict_id": None, "target": None, **kw}

    def _append(self, entries: list[dict]) -> None:
        append_jsonl(self.corrections_path, entries)

    def _fact(self, fact_id: str) -> dict:
        f = self.state().get(fact_id)
        if f is None:
            raise NotFound(f"no fact {fact_id}")
        return f

    # fact operations
    def edit(self, fact_id: str, fields: dict, reason: str = "", source: str = "ui") -> dict:
        with self.lock:
            self._fact(fact_id)
            clean = clean_fields(fields)
            if not clean:
                raise BadRequest("nothing to change")
            self._append([self._entry("edit", source, fact_id=fact_id, fields=clean, reason=reason or "")])
            return self._fact(fact_id)

    def delete(self, fact_id: str, reason: str = "", source: str = "ui") -> None:
        with self.lock:
            self._fact(fact_id)
            self._append([self._entry("delete", source, fact_id=fact_id, reason=reason or "")])

    def add(self, fields: dict, source: str = "ui", reason: str = "") -> dict:
        with self.lock:
            ids = fields.get("citation_ids") or []
            if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
                raise BadRequest("citation_ids must be a list of IDs")
            clean = clean_fields({k: v for k, v in fields.items() if k != "citation_ids" and v is not None}, require_text=True)
            if "category" not in clean:
                raise BadRequest(f"category must be one of {', '.join(CATEGORIES)}")
            clean["citation_ids"] = ids
            fid = new_id("u_", 10)
            self._append([self._entry("add", source, fact_id=fid, fields=clean, reason=reason)])
            return self._fact(fid)

    def restore(self, fact_id: str, source: str = "ui") -> dict:
        """Cancel every live entry on the fact except the one that created it."""
        with self.lock:
            fact = self._fact(fact_id)
            by_id = {e["id"]: e for e in self.log()}
            targets = [c for c in fact["corrections"] if by_id.get(c, {}).get("op") != "add"]
            self._append([self._entry("undo", source, target=t) for t in targets])
            return self._fact(fact_id)

    def undo(self, entry_id: str, source: str = "ui") -> None:
        with self.lock:
            log = self.log()
            target = next((e for e in log if e.get("id") == entry_id and e.get("op") != "undo"), None)
            if target is None:
                raise NotFound(f"no correction {entry_id}")
            if entry_id in undone_ids(log):
                raise Conflict("that correction is already undone")
            self._append([self._entry("undo", source, target=entry_id)])
            if target.get("op") == "reject_relation":
                self._rebuild_bid()

    # relations and groups
    def _live(self, op: str, key: str, value: str) -> dict | None:
        """The newest live entry of `op` whose field `key` is `value`."""
        found = [e for e in live_entries(self.log()) if e.get("op") == op and (e.get("fields") or {}).get(key) == value]
        return found[-1] if found else None

    def reject_relation(self, rid: str, source: str = "ui", reason: str = "") -> dict:
        """The user says a relation between two documents is wrong. It is skipped when the bid's facts are
        derived, so the fact it replaced is current again. Undo, or `restore_relation`, takes it back."""
        with self.lock:
            rel = next((r for f in self.state().facts for r in f.get("relations") or [] if r.get("id") == rid), None)
            if rel is None:
                raise NotFound(f"no relation {rid}")
            if self._live("reject_relation", "relation_id", rid):
                raise Conflict("that relation is already rejected")
            end = lambda x: f"{x['doc_id']}:{x['unit']}"  # noqa: E731
            entry = self._entry("reject_relation", source, reason=reason, fields={
                "relation_id": rid, "kind": rel["kind"], "from": end(rel["from"]), "to": end(rel["to"]),
            })
            self._append([entry])
            self._rebuild_bid()
            return entry

    def restore_relation(self, rid: str, source: str = "ui") -> dict:
        with self.lock:
            live = self._live("reject_relation", "relation_id", rid)
            if live is None:
                raise NotFound(f"relation {rid} is not rejected")
            self._append([self._entry("undo", source, target=live["id"])])
            self._rebuild_bid()
            return {"ok": True, "relation_id": rid}

    def ungroup(self, gid: str, source: str = "ui", reason: str = "") -> dict:
        """The user says the facts of a group do not belong together: they are shown one by one."""
        with self.lock:
            if self._live("ungroup", "group_id", gid):
                raise Conflict("that group is already ungrouped")
            members = [f for f in self.state().facts if f.get("group_id") == gid]
            if not members:
                raise NotFound(f"no group {gid}")
            entry = self._entry("ungroup", source, reason=reason, fields={
                "group_id": gid, "title": members[0].get("group_title") or "", "kind": members[0].get("group_kind") or "",
                "facts": len(members),
            })
            self._append([entry])
            return entry

    def regroup(self, gid: str, source: str = "ui") -> dict:
        with self.lock:
            live = self._live("ungroup", "group_id", gid)
            if live is None:
                raise NotFound(f"group {gid} is not ungrouped")
            self._append([self._entry("undo", source, target=live["id"])])
            return {"ok": True, "group_id": gid}

    def corrections(self) -> list[dict]:
        """The log without undo entries, newest first, each with `undone` and the fact's current text."""
        with self.lock:
            log = self.log()
            gone = undone_ids(log)
            state = self.state()
            out = []
            for e in reversed(log):
                if e.get("op") == "undo":
                    continue
                f = state.get(e["fact_id"]) if e.get("fact_id") else None
                row = {**e, "undone": e["id"] in gone, "fact_text": f["text"] if f else None}
                if e["id"] in state.before:
                    row["before"] = state.before[e["id"]]
                if e.get("conflict_id"):
                    c = state.conflict(e["conflict_id"])
                    row["conflict_title"] = c["title"] if c else (e.get("fields") or {}).get("title") if e.get("op") == "raise" else None
                    if e.get("op") == "resolve":
                        row["choice"] = _choice(c, e.get("fields") or {})
                if e.get("op") in ("reject_relation", "ungroup"):
                    row["description"] = _describe(e)
                out.append(row)
            return out

    # conflicts
    def raise_conflict(self, title: str, description: str, fact_ids: list, options: list, source: str = "chat") -> dict:
        with self.lock:
            if not isinstance(title, str) or not title.strip():
                raise BadRequest("title must not be empty")
            if not isinstance(fact_ids, list) or not fact_ids:
                raise BadRequest("fact_ids must list at least one fact")
            state = self.state()
            for fid in fact_ids:
                if state.get(fid) is None:
                    raise NotFound(f"no fact {fid}")
            if not isinstance(options, list) or len(options) < 2:
                raise BadRequest("a conflict needs at least two options")
            opts = []
            for o in options:
                if not isinstance(o, dict) or not str(o.get("label", "")).strip():
                    raise BadRequest("every option needs a label")
                changes = []
                for ch in o.get("changes") or []:
                    if not isinstance(ch, dict) or ch.get("op") not in ("edit", "delete"):
                        raise BadRequest("a change must be an edit or a delete")
                    if state.get(ch.get("fact_id")) is None:
                        raise NotFound(f"no fact {ch.get('fact_id')}")
                    fields = clean_fields(ch.get("fields") or {}) if ch["op"] == "edit" else {}
                    if ch["op"] == "edit" and not fields:
                        raise BadRequest("an edit change needs fields")
                    changes.append({"op": ch["op"], "fact_id": ch["fact_id"], "fields": fields})
                opts.append({"label": str(o["label"]).strip(), "text": str(o.get("text") or ""),
                             "citation": o.get("citation"), "changes": changes})
            cid = new_id("k_")
            fields = {"id": cid, "kind": "raised", "title": title.strip(), "description": str(description or ""),
                      "fact_ids": list(fact_ids), "options": opts}
            self._append([self._entry("raise", source, conflict_id=cid, fields=fields)])
            return self.state().conflict(cid) or {}

    def resolve(self, conflict_id: str, option: int | None = None, text: str | None = None,
                source: str = "ui", reason: str = "") -> dict:
        with self.lock:
            c = self.state().conflict(conflict_id)
            if c is None:
                raise NotFound(f"no conflict {conflict_id}")
            if c["status"] == "resolved":
                raise Conflict("that conflict is already resolved; reopen it first")
            if option is not None:
                if isinstance(option, bool) or not isinstance(option, int) or not 0 <= option < len(c["options"]):
                    raise BadRequest(f"option must be between 0 and {len(c['options']) - 1}")
                fields: dict = {"option": option}
            else:
                if not isinstance(text, str) or not text.strip():
                    raise BadRequest("choose an option or give a custom answer")
                fields = {"option": None, "text": text.strip()}
            if c["kind"] == "document" and c.get("note"):  # chosen with the later document in view: stays resolved
                fields["acknowledged"] = c["closed_by"]
            entries = [self._entry("resolve", source, conflict_id=conflict_id, fields=fields, reason=reason)]
            if c["kind"] in ("raised", "document") and option is not None:
                for ch in c["options"][option]["changes"]:
                    fields = ch.get("fields") or {}
                    if ch.get("add_flag"):  # add to the flags the fact has now, which the user may have changed
                        now_fact = self.state().get(ch["fact_id"])
                        flags = list(now_fact["flags"]) if now_fact else []
                        fields = {"flags": [*flags, *([] if ch["add_flag"] in flags else [ch["add_flag"]])]}
                    entries.append(self._entry(ch["op"], source, fact_id=ch["fact_id"], fields=fields,
                                               reason=reason or c["title"], conflict_id=conflict_id))
            self._append(entries)
            return self.state().conflict(conflict_id) or {}

    def reopen(self, conflict_id: str, source: str = "ui") -> dict:
        with self.lock:
            c = self.state().conflict(conflict_id)
            if c is None:
                raise NotFound(f"no conflict {conflict_id}")
            if c["status"] != "resolved":
                raise Conflict("that conflict is not resolved")
            live = [e for e in live_entries(self.log()) if e.get("op") == "resolve" and e.get("conflict_id") == conflict_id]
            if not live:
                raise Conflict("that conflict was settled by a later document, not by you")
            self._append([self._entry("undo", source, target=live[-1]["id"])])
            return self.state().conflict(conflict_id) or {}

    # summaries file
    def read_summaries(self) -> dict:
        try:
            data = json.loads(self.summaries_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("sections", {})
        data.setdefault("pinned", [])
        return data

    def write_summaries(self, data: dict) -> None:
        with self.lock:
            atomic_write(self.summaries_path, json.dumps(data, ensure_ascii=False, indent=1))

    # chat file
    def chat(self) -> list[dict]:
        return read_jsonl(self.chat_path)

    def append_chat(self, message: dict) -> None:
        with self.lock:
            append_jsonl(self.chat_path, [message])

    def clear_chat(self) -> None:
        """Clears the history and ends the chat session; the next message starts a new one.
        The session's log folder is kept."""
        with self.lock:
            self.chat_path.unlink(missing_ok=True)
            (self.chat_dir / "current.json").unlink(missing_ok=True)

    # chat sessions: one id from the first message to the next clear, a folder of logs per id
    @property
    def chat_dir(self) -> Path:
        return self.dir / "chat"

    def chat_session(self) -> str:
        """The current session's id; the first call after a clear (or ever) starts a new session."""
        with self.lock:
            current = self.chat_dir / "current.json"
            try:
                sid = json.loads(current.read_text(encoding="utf-8"))["session_id"]
                if SESSION_ID.match(sid) and (self.chat_dir / sid).is_dir():
                    return sid
            except (FileNotFoundError, ValueError, KeyError, TypeError):
                pass
            sid = new_id("s_", 12)
            meta = {"session_id": sid, "started": now(), "run": str(self.facts_path.parent)}
            atomic_write(self.chat_dir / sid / "session.json", json.dumps(meta, ensure_ascii=False, indent=1))
            atomic_write(current, json.dumps({"session_id": sid}))
            return sid

    def _session_dir(self, sid: str) -> Path:
        if not SESSION_ID.match(sid or "") or not (self.chat_dir / sid).is_dir():
            raise NotFound(f"no chat session {sid}")
        return self.chat_dir / sid

    def _current_session(self) -> str | None:
        try:
            return json.loads((self.chat_dir / "current.json").read_text(encoding="utf-8")).get("session_id")
        except (FileNotFoundError, ValueError, AttributeError):
            return None

    def delete_chat_session(self, sid: str) -> dict:
        """Delete one session's log folder. Deleting the current session also clears the chat, so the
        next message starts a new session rather than continuing a conversation with no log."""
        with self.lock:
            folder = self._session_dir(sid)
            was_current = self._current_session() == sid
            shutil.rmtree(folder)
            if was_current:
                self.clear_chat()
            return {"ok": True, "deleted": [sid], "chat_cleared": was_current}

    def delete_chat_sessions(self) -> dict:
        """Delete every session log of this run and clear the chat."""
        with self.lock:
            ids = [d.name for d in self.chat_dir.glob("s_*") if SESSION_ID.match(d.name) and d.is_dir()] \
                if self.chat_dir.is_dir() else []
            for sid in ids:
                shutil.rmtree(self.chat_dir / sid)
            self.clear_chat()
            return {"ok": True, "deleted": sorted(ids), "chat_cleared": True}

    def append_chat_events(self, sid: str, events: list[dict]) -> None:
        with self.lock:
            append_jsonl(self._session_dir(sid) / "events.jsonl", events)

    def chat_events(self, sid: str) -> list[dict]:
        return fill_costs(read_jsonl(self._session_dir(sid) / "events.jsonl"))

    def chat_sessions(self) -> list[dict]:
        """Every session of this run, newest first, with totals summed from its turn_end events."""
        out = []
        for d in sorted(self.chat_dir.glob("s_*")) if self.chat_dir.is_dir() else []:
            if not SESSION_ID.match(d.name) or not d.is_dir():
                continue
            try:
                meta = json.loads((d / "session.json").read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                meta = {"session_id": d.name}
            ends = [e for e in fill_costs(read_jsonl(d / "events.jsonl")) if e.get("event") == "turn_end"]
            totals: dict[str, float] = {}
            for e in ends:
                for k, v in (e.get("totals") or {}).items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        totals[k] = totals.get(k, 0) + v
            totals = {k: round(v, 8) if isinstance(v, float) else v for k, v in totals.items()}
            out.append({**meta, "session_id": d.name, "turns": len(ends),  # the folder name is the ID the API uses "last": ends[-1]["at"] if ends else meta.get("started"),
                        "totals": totals, "_order": (meta.get("started") or "", _mtime(d / "session.json"))})
        current = self.chat_dir / "current.json"
        cur = json.loads(current.read_text(encoding="utf-8")).get("session_id") if current.is_file() else None
        for s in out:
            s["current"] = s["session_id"] == cur
        out.sort(key=lambda s: s["_order"], reverse=True)  # started is to the second; session.json's write time breaks ties
        for s in out:
            del s["_order"]
        return out

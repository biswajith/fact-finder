"""Corrections on top of an extraction run: the log, the effective facts, the conflicts.

The run's own files are never touched (WEB_UI_SPEC.md section 2). Everything the customer
changes goes to `<run folder>/workspace/`: `corrections.jsonl` (append-only), `summaries.json`
and `chat.jsonl`. The effective state is always recomputed by replaying the log over the base
facts, which is what makes undo exact: cancelling an entry just removes it from the replay.

`replay` is pure (no files, no model). `Workspace` wraps one run folder with a lock.
No FastAPI import here.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..models import CATEGORIES, FLAGS
from .runs import Run, document_order, load_run, normalize

EDITABLE = ("text", "category", "flags", "note")
OPS = ("edit", "delete", "add", "raise", "resolve", "undo")
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
    return rec


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


def replay(base: list[dict], log: list[dict], doc=None) -> State:
    """Effective facts and conflicts: the base records with the live log entries applied in order.

    An edit or delete that came from resolving a raised conflict only counts while that
    resolve entry is live, so reopening a conflict takes its changes back with it.
    """
    live = _without_orphans(log, live_entries(log))
    facts = {r["fact_id"]: _blank(r) for r in base}
    originals = {r["fact_id"]: r for r in base}
    conflicts = _source_conflicts(base)
    derived: set[str] = set()
    template = base[0] if base else {}
    for e in live:
        op, fid = e.get("op"), e.get("fact_id")
        if op == "add":
            facts[fid] = _user_fact(e, template, doc)
        elif op in ("edit", "delete") and fid in facts:
            facts[fid]["corrections"].append(e["id"])
            if op == "delete":
                facts[fid]["deleted"] = True
            else:
                for k, v in (e.get("fields") or {}).items():
                    facts[fid][k] = list(v) if isinstance(v, list) else v
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
                _resolve_source(c, e, facts, derived)
            else:
                _resolve_raised(c, e)
    for fid, fact in facts.items():
        if fact["origin"] == "extracted":
            b = originals[fid]
            now_flags = [x for x in fact["flags"] if not (fid in derived and x == "replaced" and x not in b["flags"])]
            diff = {k: copy.deepcopy(b[k]) for k in EDITABLE if (now_flags if k == "flags" else fact[k]) != b[k]}
            fact["original"] = diff or None
            fact["edited"] = bool(diff)
        else:
            fact["edited"] = len(fact["corrections"]) > 1
    for c in conflicts.values():
        if c["kind"] == "source" and c["fact_ids"][0] in facts:
            c["title"] = facts[c["fact_ids"][0]]["text"]
    ordered = document_order(list(facts.values()))
    gone = {f["fact_id"] for f in ordered if f["deleted"]}
    shown = [c for c in conflicts.values() if not (c["kind"] == "source" and c["fact_ids"][0] in gone)]
    shown.sort(key=lambda c: c["status"] != "open")
    return State(ordered, shown, live)


# --- a PDF attached to a run that has none ------------------------------------------------


def attached_pdf(run_dir: Path) -> tuple[Path, str] | None:
    """The PDF the customer attached to the run in `run_dir`: a picked path
    (`workspace/pdf.json`) or an upload (`workspace/source.pdf`). None when there is none."""
    ws = run_dir / "workspace"
    try:
        meta = json.loads((ws / "pdf.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = None
    if isinstance(meta, dict):
        name = str(meta.get("name") or "")
        if meta.get("path"):
            path = Path(str(meta["path"]))
            if path.is_file():
                return path, name or path.name
        elif (ws / "source.pdf").is_file():
            return ws / "source.pdf", name or "source.pdf"
    elif (ws / "source.pdf").is_file():
        return ws / "source.pdf", "source.pdf"
    return None


# --- one run folder -------------------------------------------------------------------------


class Workspace:
    """A run folder and its `workspace/` folder. All reads and writes go through one lock."""

    def __init__(self, facts_path: Path) -> None:
        self.facts_path = facts_path
        self.dir = facts_path.parent / "workspace"
        self.lock = threading.RLock()
        self._run: Run | None = None
        self._stamp: tuple | None = None
        self._own_pdf: Path | None = None
        self._doc = None
        self._doc_pdf: Path | None = None
        self._doc_loaded = False

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

    # the extraction (read only)
    def run(self) -> Run:
        """The loaded run; read again when the facts file changed on disk."""
        with self.lock:
            st = self.facts_path.stat()
            stamp = (st.st_mtime_ns, st.st_size)
            if self._run is None or stamp != self._stamp:
                self._run, self._stamp = load_run(self.facts_path), stamp
                self._own_pdf = self._run.pdf
            # A run without a PDF of its own uses the one attached to it, if any.
            if self._own_pdf is None:
                att = attached_pdf(self.facts_path.parent)
                self._run.pdf = att[0] if att else None
            return self._run

    def has_own_pdf(self) -> bool:
        self.run()
        return self._own_pdf is not None

    def pdf_name(self) -> str | None:
        """File name of the run's PDF: source.pdf for its own, the attached name otherwise."""
        with self.lock:
            if self.has_own_pdf():
                return "source.pdf"
            att = attached_pdf(self.facts_path.parent)
            return att[1] if att else None

    def attach_path(self, path: Path) -> None:
        """Remember a PDF elsewhere on disk for this run (the file itself is not copied)."""
        with self.lock:
            (self.dir / "source.pdf").unlink(missing_ok=True)
            atomic_write(self.dir / "pdf.json", json.dumps({"path": str(path), "name": path.name}))

    def attach_bytes(self, data: bytes, name: str) -> None:
        with self.lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / f"source.pdf.{uuid.uuid4().hex[:6]}.tmp"
            try:
                tmp.write_bytes(data)
                os.replace(tmp, self.dir / "source.pdf")
            finally:
                tmp.unlink(missing_ok=True)
            atomic_write(self.dir / "pdf.json", json.dumps({"path": None, "name": name}))

    def detach_pdf(self) -> None:
        """Forget the attached PDF. The run's own source.pdf is never touched."""
        with self.lock:
            (self.dir / "pdf.json").unlink(missing_ok=True)
            (self.dir / "source.pdf").unlink(missing_ok=True)

    def document(self):
        """The tagged document of the run's PDF, or None without a PDF. Built once; slow on first use."""
        with self.lock:
            pdf = self.run().pdf
            if not self._doc_loaded or pdf != self._doc_pdf:
                self._doc, self._doc_pdf = None, pdf
                if pdf is not None:
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
        with self.lock:
            log = self.log()
            needs_doc = any(e.get("op") == "add" and (e.get("fields") or {}).get("citation_ids") for e in log)
            return replay(self.run().records, log, self.document() if needs_doc else None)

    def _entry(self, op: str, source: str, **kw) -> dict:
        if source not in ("chat", "ui"):
            raise BadRequest("source must be chat or ui")
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
                out.append({**e, "undone": e["id"] in gone, "fact_text": f["text"] if f else None})
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
            entries = [self._entry("resolve", source, conflict_id=conflict_id, fields=fields, reason=reason)]
            if c["kind"] == "raised" and option is not None:
                for ch in c["options"][option]["changes"]:
                    entries.append(self._entry(ch["op"], source, fact_id=ch["fact_id"], fields=ch.get("fields") or {},
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
        with self.lock:
            self.chat_path.unlink(missing_ok=True)

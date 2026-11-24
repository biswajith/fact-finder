"""A bid: several documents about one opportunity, read one by one and listed together.

A bid is the folder `<runs root>/_bids/<bid_id>/`:
- `bid.json`: the manifest (the documents, their type, issue number and date, who spoke);
- `files/<no>_<name>`: every uploaded file as uploaded;
- `facts.json`, `report.json`: derived by `build()` from the stored result of each document,
  never edited by hand. Because `facts.json` sits two levels under the runs folder, the web app
  opens a bid as the run `_bids/<bid_id>`.

Each document is extracted on its own with its playbook and stored like any other result under
`<runs root>/<doc_id>/<run_id>/`. The folder of a bid never holds a `meta.json`: the result
store lists every folder that has one.

No FastAPI and no model client is imported here; the model is passed in.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
import re
import tempfile
import threading
from collections import Counter
from collections.abc import Callable
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path

from . import classify, cutters, ladder, playbooks, relate, reissue, results

BIDS = "_bids"
SIDES = ("buyer", "ours", "other", "unknown")  # other: a named party that is neither the buyer nor us
# The side written on the units of an `other` speaker who acts for the buyer (an adviser the buyer hired).
BUYER_ADVISER = "other-buyer"
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NO_DATE = "9999-12-31"  # a document with no date sorts after the dated ones

Step = Callable[[int, str, str, str], None]  # (doc no, step, status, detail)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, obj, indent: int = 2) -> None:
    """Write `obj` as JSON so that a reader sees the old file or the new one, never half of it."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, indent=indent))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def slug(name: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return out or "bid"


class Bid:
    """The folder of one bid. Methods that change the manifest hold `lock`, so two threads of one
    process do not overwrite each other's change."""

    def __init__(self, root: str | Path, bid_id: str) -> None:
        self.root = Path(root)
        self.bid_id = bid_id
        self.folder = self.root / BIDS / bid_id
        with _LOCKS_GUARD:
            self.lock = _LOCKS.setdefault(str(self.folder.resolve()), threading.RLock())

    def exists(self) -> bool:
        return (self.folder / "bid.json").is_file()

    def manifest(self) -> dict:
        try:
            return json.loads((self.folder / "bid.json").read_text(encoding="utf-8"))
        except OSError:
            raise FileNotFoundError(f"no bid named {self.bid_id!r}") from None

    def save(self, manifest: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        _write_json(self.folder / "bid.json", manifest)

    # --- documents ----------------------------------------------------------------------

    def document(self, no: int) -> dict:
        for d in self.manifest()["documents"]:
            if d["no"] == no:
                return d
        raise KeyError(f"the bid has no document {no}")

    def _change(self, no: int, fn: Callable[[dict, dict], None]) -> dict:
        """Apply `fn(manifest, document)` to one document and save; returns the document."""
        with self.lock:
            m = self.manifest()
            d = next((d for d in m["documents"] if d["no"] == no), None)
            if d is None:
                raise KeyError(f"the bid has no document {no}")
            fn(m, d)
            self.save(m)
            return d

    def data(self, doc: dict) -> bytes:
        return (self.folder / doc["file"]).read_bytes()

    def add_document(self, data: bytes, file_name: str) -> dict:
        """Store an uploaded file and propose its type. Raises ValueError for a file already in the bid."""
        sha = results.content_hash(data)
        with self.lock:
            m = self.manifest()
            docs = m["documents"]
            if any(d["sha256"] == sha for d in docs):
                raise ValueError("this file is already in the bid")
            no = max((d["no"] for d in docs), default=0) + 1
            base = Path(file_name).name
            stem = Path(base).stem.strip() or "document"
            taken = {d["doc_id"] for d in docs}
            doc_id, n = stem, 1
            while doc_id in taken:
                n += 1
                doc_id = f"{stem}-{n}"
            stored = f"files/{no}_{results.safe_name(base)}"
            (self.folder / "files").mkdir(parents=True, exist_ok=True)
            (self.folder / stored).write_bytes(data)
            proposed = classify.by_rules(base, data)
            doc = {
                "no": no, "doc_id": doc_id, "file": stored, "file_name": base, "sha256": sha,
                "pages": _pdf_pages(data) if cutters.form_of(base, data) == "pdf" else 0,
                "proposed": proposed, "playbook": proposed["playbook"],
                "issue_number": proposed["issue_number"], "issue_date": proposed["issue_date"],
                "confirmed": False, "previous": None, "speakers": [], "speakers_confirmed": False,
                "run": "", "status": "uploaded", "error": "",
            }
            docs.append(doc)
            if playbooks.load(doc["playbook"]).cutter == "transcript":
                doc["speakers"] = self._propose(m, doc, data)
            self.save(m)
            return doc

    def _propose(self, m: dict, doc: dict, data: bytes) -> list[dict]:
        """The speakers of a transcript with their proposed sides; a side already chosen is kept."""
        try:
            info = cutters.cut_transcript(data, doc["file_name"])[1]
        except ValueError:
            return doc["speakers"]
        have = {s["id"]: s.get("side", "") for s in doc["speakers"]}
        out = propose_speakers(info, m.get("team") or [], self.b_fact_texts(m), doc.get("speakers_model"))
        for s in out:
            s["side"] = have.get(s["id"], "")
        return out

    def refresh_speakers(self, no: int) -> dict:
        """Propose the speakers' sides again (the team list or the buyer's facts may have changed).
        Does nothing once the speakers are confirmed."""
        def go(m: dict, d: dict) -> None:
            if not d["speakers_confirmed"] and playbooks.load(d["playbook"]).cutter == "transcript":
                d["speakers"] = self._propose(m, d, self.data(d))

        return self._change(no, go)

    def set_speaker_model(self, no: int, answer: dict) -> dict:
        """Keep the model's answer about who is on which side (`speakers.by_model`) and propose the sides
        again with it. Does nothing once the speakers are confirmed or the document is extracted."""
        def go(m: dict, d: dict) -> None:
            if d["speakers_confirmed"] or d["run"] or playbooks.load(d["playbook"]).cutter != "transcript":
                return
            d["speakers_model"] = answer
            d["speakers"] = self._propose(m, d, self.data(d))

        return self._change(no, go)

    def speakers_context(self, no: int) -> dict:
        """What the model is told about the bid when it places a call's speakers: the bid's name, the team,
        phrases from the buyer's facts (at most 20) and the file names of the other documents."""
        m = self.manifest()
        return {
            "bid_name": m.get("name", ""), "team": [t.get("name", "") for t in m.get("team") or []],
            "buyer_names": [" ".join(t.split())[:160] for t in self.b_fact_texts(m)[:20]],
            "other_documents": [d["file_name"] for d in m["documents"] if d["no"] != no],
        }

    def set_proposal(self, no: int, proposed: dict) -> dict:
        """Replace the proposal of a document the user has not confirmed yet (the model's CLASSIFY answer
        after the rules'), and take its type, number and date as the document's own. Does nothing once the
        document is confirmed or extracted: the user's choice stands."""
        def go(m: dict, d: dict) -> None:
            if d["confirmed"] or d["run"] or d["status"] in ("extracting", "extracted"):
                return
            d["proposed"] = proposed
            d["playbook"], d["issue_number"], d["issue_date"] = proposed["playbook"], proposed["issue_number"], proposed["issue_date"]
            if playbooks.load(d["playbook"]).cutter == "transcript" and not d["speakers"]:
                d["speakers"] = self._propose(m, d, self.data(d))

        return self._change(no, go)

    def b_fact_texts(self, m: dict | None = None) -> list[str]:
        """The texts of the B facts of the extracted base documents: where the buyer's people are named."""
        m = m or self.manifest()
        out: list[str] = []
        for d in m["documents"]:
            if d.get("run") and playbooks.load(d["playbook"]).role == "base":
                try:
                    facts = json.loads((self.root / d["run"] / "facts.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                out += [f["text"] for f in facts if f.get("category") == "B"]
        return out

    def update_document(self, no: int, **fields) -> dict:
        """Change what the user may set: doc_id, playbook, issue_number, issue_date, previous,
        confirmed, speakers (a list of {id or name, side}), speakers_confirmed. Raises ValueError
        for a value that is not allowed."""
        unknown = set(fields) - {
            "doc_id", "playbook", "issue_number", "issue_date", "previous", "confirmed", "speakers",
            "speakers_confirmed",
        }
        if unknown:
            raise ValueError(f"cannot set {', '.join(sorted(unknown))}")

        def go(m: dict, d: dict) -> None:
            done = bool(d["run"]) or d["status"] in ("extracting", "extracted")
            if "playbook" in fields and fields["playbook"] != d["playbook"]:
                if fields["playbook"] not in playbooks.names():
                    raise ValueError(f"no playbook named {fields['playbook']!r}")
                if done:
                    raise ValueError("an extracted document cannot change its type")
            if "doc_id" in fields and fields["doc_id"] != d["doc_id"]:
                new = str(fields["doc_id"]).strip()
                if not new:
                    raise ValueError("the document ID cannot be empty")
                if done:
                    raise ValueError("an extracted document cannot change its ID")
                if any(o["doc_id"] == new for o in m["documents"] if o["no"] != no):
                    raise ValueError(f"another document of the bid has the ID {new!r}")
            if "issue_date" in fields and fields["issue_date"] not in (None, ""):
                v = fields["issue_date"]
                try:
                    if not (isinstance(v, str) and _ISO.match(v)):
                        raise ValueError
                    _date.fromisoformat(v)
                except ValueError:
                    raise ValueError("the issue date must be YYYY-MM-DD") from None
            if "issue_number" in fields and fields["issue_number"] is not None:
                v = fields["issue_number"]
                if isinstance(v, str) and v.strip().isdigit():
                    v = fields["issue_number"] = int(v)
                if isinstance(v, bool) or not isinstance(v, int):
                    raise ValueError("the issue number must be a whole number")
            if "previous" in fields and fields["previous"] is not None:
                if not any(o["doc_id"] == fields["previous"] and o["no"] != no for o in m["documents"]):
                    raise ValueError("the previous version must be another document of the bid")
            if ("speakers" in fields or "speakers_confirmed" in fields) and done:
                raise ValueError("the speakers of an extracted document cannot change")
            for key in ("doc_id", "playbook", "issue_number", "issue_date", "previous"):
                if key in fields:
                    v = fields[key]
                    d[key] = (str(v).strip() if key == "doc_id" else None if v == "" else v)
            if "confirmed" in fields:
                d["confirmed"] = bool(fields["confirmed"])
            if "speakers_confirmed" in fields:
                d["speakers_confirmed"] = bool(fields["speakers_confirmed"])
            if "speakers" in fields:
                for given in fields["speakers"]:
                    s = next((s for s in d["speakers"] if given.get("id") in (s["id"],) or given.get("name") == s["name"]), None)
                    if s is None:
                        raise ValueError(f"no speaker {given.get('id') or given.get('name')!r} in this document")
                    if given.get("side") not in SIDES:
                        raise ValueError(f"a side is one of {', '.join(SIDES)}")
                    s["side"] = given["side"]
                    if "acts_for" in given:
                        if given["acts_for"] not in ("buyer", "ours", ""):
                            raise ValueError("acts_for is buyer, ours or empty")
                        s["acts_for"] = given["acts_for"]
            if playbooks.load(d["playbook"]).cutter == "transcript" and not d["speakers"]:
                d["speakers"] = self._propose(m, d, self.data(d))
            if d["status"] in ("uploaded", "confirmed", "failed"):
                d["status"] = "confirmed" if d["confirmed"] else "uploaded"

        return self._change(no, go)

    def earlier_documents(self, manifest: dict, doc: dict) -> list[dict]:
        """The documents RELATE reads `doc` against: those before it in issue order that are extracted,
        whose authority is the buyer's and whose units were stored. Empty for a playbook that relates
        to nothing."""
        if playbooks.load(doc["playbook"]).relate_to != "buyer documents":
            return []
        out = []
        for e in issue_order(manifest):
            if e["no"] == doc["no"]:
                break
            if e.get("run") and _authority(e) == "buyer" and (self.root / e["run"] / "units.json").is_file():
                out.append(e)
        return out

    def needs_relate(self, manifest: dict | None = None) -> list[int]:
        """The numbers of the extracted documents whose stored RELATE answers were made against other
        documents than the earlier buyer documents now in the bid (a document was added that sorts
        before them). `extract_document(..., relate_only=True)` runs RELATE again for one."""
        m = manifest or self.manifest()
        out = []
        for d in m["documents"]:
            if not d.get("run") or "RELATE" not in playbooks.load(d["playbook"]).calls:
                continue
            try:
                have = json.loads((self.root / d["run"] / "relations.json").read_text(encoding="utf-8")).get("against")
            except (OSError, ValueError):
                have = None
            want = [e["doc_id"] for e in self.earlier_documents(m, d)]
            if have is None or set(have) != set(want):
                out.append(d["no"])
        return out

    def incomplete_relations(self, manifest: dict | None = None) -> dict[int, list[str]]:
        """Document number -> the unit IDs whose stored RELATE answer is missing (the model gave no usable
        answer for them). Documents with none are left out."""
        m = manifest or self.manifest()
        out: dict[int, list[str]] = {}
        for d in m["documents"]:
            if not d.get("run"):
                continue
            try:
                left = json.loads((self.root / d["run"] / "relations.json").read_text(encoding="utf-8")).get("incomplete")
            except (OSError, ValueError):
                left = None
            if left:
                out[d["no"]] = [str(u) for u in left]
        return out

    def remove_document(self, no: int) -> None:
        with self.lock:
            m = self.manifest()
            d = next((d for d in m["documents"] if d["no"] == no), None)
            if d is None:
                raise KeyError(f"the bid has no document {no}")
            if d["run"] or d["status"] in ("extracting", "extracted"):
                raise ValueError("an extracted document cannot be removed")
            m["documents"].remove(d)
            self.save(m)
            (self.folder / d["file"]).unlink(missing_ok=True)


def _pdf_pages(data: bytes) -> int:
    try:
        import pymupdf

        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return doc.page_count
    except Exception:
        return 0


def create(root: str | Path, name: str, deal_id: str = "") -> Bid:
    """A new empty bid. Its ID is a lower-case slug of `name`, made unique among the bids."""
    base = slug(name)
    bid_id, n = base, 1
    while (Path(root) / BIDS / bid_id).exists():
        n += 1
        bid_id = f"{base}-{n}"
    bid = Bid(root, bid_id)
    bid.save({
        "bid_id": bid_id, "name": name.strip() or bid_id, "deal_id": deal_id or bid_id, "created": _now(),
        "team": [], "precedence": None, "documents": [],
    })
    return bid


def list_bids(root: str | Path) -> list[dict]:
    """Every bid under `root`, newest first: `{bid_id, name, run, documents, facts, modified}`.
    `run` is the run path the web app opens, empty until the bid has a fact list."""
    out = []
    for p in sorted((Path(root) / BIDS).glob("*/bid.json")):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        facts_path = p.parent / "facts.json"
        facts = 0
        if facts_path.is_file():
            try:
                facts = len(json.loads(facts_path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        mtime = max(p.stat().st_mtime, facts_path.stat().st_mtime if facts_path.is_file() else 0)
        out.append({
            "bid_id": m["bid_id"], "name": m.get("name", ""), "run": f"{BIDS}/{m['bid_id']}" if facts_path.is_file() else "",
            "documents": len(m.get("documents", [])), "facts": facts,
            "modified": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"), "_t": mtime,
        })
    out.sort(key=lambda b: -b["_t"])
    for b in out:
        b.pop("_t")
    return out


# --- order, speakers, readiness ---------------------------------------------------------


def _role(doc: dict) -> str:
    try:
        return playbooks.load(doc["playbook"]).role
    except ValueError:
        return ""


def issue_order(manifest: dict) -> list[dict]:
    """The documents in the order they were issued, never in the order they were uploaded: by date,
    then issue number, then upload number. Among the change documents (addenda) the issue number
    comes before the date, because a later addendum that carries an earlier date still applies after
    the one before it. A base document with no date comes first; any other with none, last."""
    docs = manifest["documents"]

    def key(d: dict) -> tuple:
        none = "0000-00-00" if _role(d) == "base" else _NO_DATE
        return (d.get("issue_date") or none, d.get("issue_number") or 0, d["no"])

    ordered = sorted(docs, key=key)
    slots = [i for i, d in enumerate(ordered) if _role(d) == "change"]
    changes = sorted(
        (ordered[i] for i in slots), key=lambda d: (d.get("issue_number") or 0, d.get("issue_date") or _NO_DATE, d["no"])
    )
    for i, d in zip(slots, changes):
        ordered[i] = d
    return ordered


def _authority(doc: dict) -> str:
    try:
        return playbooks.load(doc["playbook"]).authority
    except ValueError:
        return ""


def doc_numbers(manifest: dict) -> dict[str, int]:
    return {d["doc_id"]: d["no"] for d in manifest["documents"]}


def propose_speakers(info: dict, team: list[dict], b_fact_texts: list[str], model: dict | None = None) -> list[dict]:
    """A side for each speaker of a call. The team list wins; then the model's answer when it names the
    buyer, us or another party; then the buyer's facts; then the call system's affiliation. Each entry:
    `{id, name, side, proposed, why, organisation, title, note, acts_for}`; `side` is left empty for the
    user to confirm. `model` is `speakers.by_model`'s answer, by speaker id."""
    ours = {str(t.get("name", "")).strip().casefold() for t in team} - {""}
    out = []
    for s in info.get("speakers", []):
        name = (s.get("name") or "").strip()
        sid = s.get("id") or name
        said = (model or {}).get(sid) or {}
        proposed, why = "unknown", "none"
        if name.casefold() in ours:
            proposed, why = "ours", "team list"
        elif said.get("side") in ("buyer", "ours", "other"):
            proposed, why = said["side"], f"model: {said.get('reason', '')}".rstrip(": ")
        elif name and any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", t, re.I) for t in b_fact_texts):
            proposed, why = "buyer", "B fact"
        elif s.get("affiliation") == "Internal":
            proposed, why = "ours", "Gong affiliation"
        elif s.get("affiliation") == "External":
            proposed, why = "buyer", "Gong affiliation"
        out.append({
            "id": sid, "name": name, "side": "", "proposed": proposed, "why": why,
            "organisation": said.get("organisation") or s.get("organisation") or "",
            "title": s.get("title") or "", "note": s.get("note") or "", "acts_for": said.get("acts_for") or "",
        })
    return out


def ready(doc: dict) -> list[str]:
    """What is still missing before the document may be extracted; empty when it may."""
    if not doc.get("confirmed") or doc.get("playbook") not in playbooks.names():
        return ["type not confirmed"]
    pb = playbooks.load(doc["playbook"])
    missing = []
    if pb.role in ("change", "context") and not doc.get("issue_date"):
        missing.append("issue date missing")
    if pb.role == "change" and not doc.get("issue_number"):
        missing.append("issue number missing")
    if pb.cutter == "transcript":
        if not doc.get("speakers_confirmed"):
            missing.append("speakers not confirmed")
        if any(s.get("side") not in SIDES for s in doc.get("speakers", [])):
            missing.append("a speaker has no side")
    if pb.name == "reissued-rfp" and not doc.get("previous"):
        missing.append("previous version not chosen")
    return missing


# --- levels -----------------------------------------------------------------------------


def level_of(pb: playbooks.Playbook, sides: list[str]) -> tuple[int, list[str]]:
    """The level of a fact and the flags its sources add, from the sides of the units it cites.
    Never from a model answer. A buyer document or a note has the playbook's level. For a call:
    2 when any cited unit is the buyer's or the buyer's adviser's, else 3. An `other` side (an advisor, a partner) is neither the
    buyer nor ours and is clear; an `unknown` side is not decided, so a fact with `unknown` units and none
    of the buyer's or ours is `unclear`; units of both the buyer and ours add `both-sides`."""
    if pb.level != "by speaker":
        return int(pb.level), []
    s = {"buyer" if x == BUYER_ADVISER else x for x in sides}  # the buyer's adviser speaks for the buyer
    flags = []
    if {"buyer", "ours"} <= s:
        flags.append("both-sides")
    if not s & {"buyer", "ours"} and ("unknown" in s or s <= {""}):
        flags.append("unclear")
    return (2 if "buyer" in s else 3), flags


def apply_levels(record: dict, pb: playbooks.Playbook) -> dict:
    """Set `level` on a fact record and the flags its sources add. A fact with units of both sides
    shows the source's words: no one side's statement stands for both. Safe to apply twice."""
    level, add = level_of(pb, [c.get("side") or "" for c in record.get("citations") or []])
    record["level"] = level
    flags = record.setdefault("flags", [])
    flags += [f for f in add if f not in flags]
    if "both-sides" in add and "source_text" in record:
        record["text"], record["text_from"] = record["source_text"], "rfp"
    return record


def citation_level(pb: playbooks.Playbook, citation: dict) -> int:
    return level_of(pb, [citation.get("side") or ""])[0]


# --- extract one document ---------------------------------------------------------------


def _run_path(stored: results.Stored) -> str:
    return f"{stored.folder.parent.name}/{stored.folder.name}"


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


async def _relate(bid: Bid, d: dict, pb: playbooks.Playbook, tagged, facts: Records, client, cfg, refs, held,
                  only: list[str] | None = None, stored: dict | None = None) -> dict:
    """RELATE for one document against the earlier buyer documents now in the bid."""
    m = bid.manifest()
    earlier = []
    for e in bid.earlier_documents(m, d):
        t = results.load_document(bid.root / e["run"], e["doc_id"])
        if t is not None:
            earlier.append((e["no"], t, _read(bid.root / e["run"] / "facts.json", [])))
    return await relate.relate(tagged, d["no"], pb, facts, earlier, client, cfg, refs=refs, held_refs=held,
                               only=only, stored=stored)


def _with_held_q(rel: dict, tagged, facts: Records, report: dict, pb: playbooks.Playbook) -> Records:
    """The facts without the Q facts an earlier RELATE run made for held references, plus the ones
    this answer needs; the report's counts follow."""
    from . import units as U

    dropped = {f["fact_id"] for f in facts if f.get("from_held")}
    facts = [f for f in facts if not f.get("from_held")]
    for f in facts:
        if dropped & set(f.get("conflicts") or []):
            f["conflicts"] = [c for c in f["conflicts"] if c not in dropped]
            if not f["conflicts"] and f.get("status") == "conflict":
                f["status"] = "valid"
    for q in relate.q_records(rel, tagged, report.get("deal_id", ""), report.get("run_id", "")):
        apply_levels(q, pb)
        facts.append(q)
    U._mark_conflicts(facts)
    report["facts"] = len(facts)
    report["by_category"] = dict(Counter(f["category"] for f in facts))
    report["by_status"] = dict(Counter(f["status"] for f in facts))
    return facts


async def _relate_stored(bid: Bid, no: int, pb: playbooks.Playbook, found: results.Stored, client, cfg, say,
                         only_incomplete: bool = False) -> results.Stored:
    """Run RELATE again for a stored result and rewrite its `relations.json`, its Q facts for held
    references and the report's `relate_calls`. The labels, statements and checks are kept.
    With `only_incomplete`, only the units the stored answer left unanswered are asked, the other
    answers are kept, and the new calls are added to the report's `relate_calls`."""
    from . import units as U

    d = bid.document(no)
    tagged = results.load_document(found.folder, d["doc_id"])
    if tagged is None:
        raise ValueError(f"document {no} has no stored units to relate")
    old = _read(found.folder / "relations.json", {})
    facts, report = found.facts(), found.report()
    say("relate", "running")
    only = list(old.get("incomplete") or []) if only_incomplete else None
    rel = await _relate(bid, d, pb, tagged, [f for f in facts if not f.get("from_held")], client, cfg or U.Config(votes=pb.votes),
                        old.get("ref_units") or [], old.get("held_refs") or [], only=only, stored=old if only_incomplete else None)
    report["relate_calls"] = [*(report.get("relate_calls") or []), *rel.pop("calls")] if only_incomplete else rel.pop("calls")
    facts = _with_held_q(rel, tagged, facts, report, pb)
    _write_json(found.folder / "facts.json", facts)
    _write_json(found.folder / "report.json", report)
    _write_json(found.folder / "relations.json", rel)
    found.meta["facts"] = len(facts)
    _write_json(found.folder / "meta.json", found.meta)
    if only_incomplete:
        say("relate", "done", f"{len(only or [])} units asked again")
    else:
        say("relate", "done", f"{len(rel['units'])} units, {len(rel['incomplete'])} left out")
    return found


def _previous_result(bid: Bid, d: dict, pb: playbooks.Playbook) -> results.Stored | None:
    """The stored result of the version a reissued RFP replaces; None for any other document, or when
    that version is not extracted."""
    if pb.name != "reissued-rfp" or not d.get("previous"):
        return None
    old = next((o for o in bid.manifest()["documents"] if o["doc_id"] == d["previous"]), None)
    if old is None or not old.get("run"):
        return None
    folder = bid.root / old["run"]
    meta = _read(folder / "meta.json", None)
    return results.Stored(folder, meta) if meta and (folder / "facts.json").is_file() else None


async def extract_document(
    bid: Bid, no: int, client, *, votes: int | None = None, store: results.ResultStore,
    on_step: Step | None = None, cfg=None, relate_only: bool = False,
    only_incomplete: bool = False,
) -> results.Stored:
    """Cut one confirmed document with its playbook's cutter, give each unit its side from the
    confirmed speaker map, run the playbook, set each fact's level and flags, and store the result.
    A playbook with RELATE then compares every unit with the earlier buyer documents of the bid and
    stores the answers as `relations.json`. A stored result for the same content, playbook and doc_id
    is reused without a model call. `relate_only=True` runs only RELATE again for a document that is
    already extracted (see `Bid.needs_relate`); with `only_incomplete` it asks only the units the stored
    answer left unanswered (see `Bid.incomplete_relations`). `on_step(no, step, status, detail)` hears `cut`,
    `extract`, `relate` and `save`. On an error the manifest says `failed` with the message, and the
    error is raised."""
    from . import units as U
    from .api import document_from_units
    from .web import runs

    def say(step: str, status: str, detail: str = "") -> None:
        if on_step:
            on_step(no, step, status, detail)

    def mark(**fields) -> None:
        bid._change(no, lambda m, d: d.update(fields))

    d = bid.document(no)
    pb = playbooks.load(d["playbook"])
    if relate_only:
        if not d.get("run") or "RELATE" not in pb.calls:
            raise ValueError(f"document {no} is not extracted or does not use RELATE")
        folder = bid.root / d["run"]
        return await _relate_stored(bid, no, pb, results.Stored(folder, _read(folder / "meta.json", {})), client, cfg, say,
                                    only_incomplete)
    missing = ready(d)
    if missing:
        raise ValueError(f"document {no} is not ready: {', '.join(missing)}")
    try:
        found = store.find(d["sha256"], U.VERSION, d["doc_id"], pb.key)
        if found:
            say("extract", "reused", "stored result")
            if "RELATE" in pb.calls and not (found.folder / "relations.json").is_file():
                await _relate_stored(bid, no, pb, found, client, cfg, say)  # stored in another bid, or before RELATE
            mark(run=_run_path(found), status="extracted", error="")
            return found
        mark(status="extracting", error="")
        data = bid.data(d)
        say("cut", "running")
        how = cutters.reader(pb.cutter, d["file_name"], data)
        if how == "pdf":
            tagged = runs.tag_pdf(data, d["doc_id"], store.root)
        else:
            # an adviser who acts for the buyer speaks for the buyer: their units count as the buyer's (level 2)
            sides = {s["name"]: BUYER_ADVISER if s["side"] == "other" and s.get("acts_for") == "buyer" else s["side"]
                     for s in d["speakers"]}
            # another party's units name its organisation, so a reader sees whose words they are
            shown = {s["name"]: f"{s['name']} ({s['organisation']})" for s in d["speakers"]
                     if s["side"] == "other" and s.get("organisation")}
            cut = [
                dataclasses.replace(u, side=sides.get(u.speaker, "unknown"), speaker=shown.get(u.speaker, u.speaker)) if u.speaker else u
                for u in cutters.cut(how, data, d["file_name"])
            ]
            tagged, _ = document_from_units(d["doc_id"], cut)
        if not tagged.anchors:
            raise ValueError("the document has no text")
        say("cut", "done", f"{len(tagged.anchors)} units")
        say("extract", "running")
        cfg = dataclasses.replace(cfg or U.Config(votes=pb.votes), votes=votes or (cfg.votes if cfg else pb.votes))
        before = _previous_result(bid, d, pb)
        if before is not None:  # a reissued RFP: units that align to the previous version keep its votes
            result = await reissue.extract(
                tagged, before, client, pb, cfg, deal_id=bid.manifest()["deal_id"], run_id=runs.new_run_id(),
            )
        else:
            result = await U.extract(
                tagged, client, deal_id=bid.manifest()["deal_id"], cfg=cfg, run_id=runs.new_run_id(), playbook=pb,
                hold_section_refs="RELATE" in pb.calls,
            )
        for r in result.facts:
            apply_levels(r, pb)
        say("extract", "done", f"{len(result.facts)} facts")
        rel = None
        if "RELATE" in pb.calls:
            say("relate", "running")
            rel = await _relate(bid, d, pb, tagged, result.facts, client, cfg, result.section_units, result.held_refs)
            result.report["relate_calls"] = rel.pop("calls")
            result.facts = _with_held_q(rel, tagged, result.facts, result.report, pb)
            say("relate", "done", f"{len(rel['units'])} units, {len(rel['incomplete'])} left out")
        say("save", "running")
        saved = store.save(
            data, d["sha256"], U.VERSION, result, result.labels, playbook=pb.key, source_name=d["file_name"],
            units=tagged,
        )
        if rel is not None:
            _write_json(saved.folder / "relations.json", rel)
        if result.alignment:
            _write_json(saved.folder / "alignment.json", result.alignment)
        mark(run=_run_path(saved), status="extracted", error="")
        say("save", "done")
        return saved
    except BaseException as e:
        mark(status="failed", error=str(e) or type(e).__name__)
        say("extract", "failed", str(e))
        raise


# --- the bid's fact list ----------------------------------------------------------------

Records = list[dict]
# (bid, manifest, records in issue order, outputs) -> records. `outputs` collects what a step derives
# besides the records: `outputs["conflicts"]` are the conflicts raised for documents.
FactStep = Callable[["Bid", dict, Records, dict], Records]


def _stamp(bid: Bid, manifest: dict, records: Records, out: dict) -> Records:
    """Every fact says which document it is from and every citation which document, level and
    visibility; the fields the later steps fill are present and empty."""
    nos = doc_numbers(manifest)
    by_id = {d["doc_id"]: d for d in manifest["documents"]}
    for r in records:
        d = by_id[r["doc_id"]]
        pb = playbooks.load(d["playbook"])
        apply_levels(r, pb)
        r["doc_no"], r["playbook"] = nos[r["doc_id"]], pb.name
        for c in r.get("citations") or []:
            c["doc_id"] = c.get("doc_id") or r["doc_id"]
            c["doc_no"] = nos.get(c["doc_id"], r["doc_no"])
            c["level"] = citation_level(pb, c)
            c["visibility"] = pb.visibility
        r["relations"], r["replaced_by"], r["stale"] = [], "", ""
    return records


def _apply_reissues(bid: Bid, manifest: dict, records: Records, out: dict) -> Records:
    """The facts of a version that a reissued RFP replaces leave the current list: the ones the
    reissue carried are dropped (their counterpart in the new version continues), the rest stay,
    flagged `replaced`, with `stale` saying why. Reads each reissue's `alignment.json`.
    The report's `reissues` lists the changed, new and removed unit counts."""
    carried: dict[str, set[str]] = {}
    for d in issue_order(manifest):
        if d.get("playbook") != "reissued-rfp" or not d.get("run") or not d.get("previous"):
            continue
        a = reissue.read_alignment(bid.root / d["run"])
        if a:
            carried.setdefault(d["previous"], set()).update((a.get("facts") or {}).keys())
            out.setdefault("reissues", []).append({
                "doc_no": d["no"], "doc_id": d["doc_id"], "previous": d["previous"], "changed": len(a.get("changed") or []),
                "new": len(a.get("new") or []), "removed": len(a.get("removed") or []), "carried_facts": len(a.get("facts") or {}),
            })
    if not carried:
        return records
    kept = []
    for r in records:
        gone = carried.get(r["doc_id"])
        if gone is None:
            kept.append(r)
        elif r["fact_id"] not in gone:
            if "replaced" not in r["flags"]:
                r["flags"] = [*r["flags"], "replaced"]
            r["replaced_by"], r["stale"] = "", "not in the reissued RFP"
            kept.append(r)
    return kept


def _apply_relations(bid: Bid, manifest: dict, records: Records, out: dict) -> Records:
    """Apply every document's stored relations in issue order (`ladder.apply`). Reads the user's
    correction log for two things only: the relations the user rejected and the facts the user
    edited. Relations stored against other documents than the ones now before a document are
    applied as stored."""
    from .web.workspace import live_entries, read_jsonl  # no FastAPI behind it

    present = {r["doc_id"] for r in records}
    docs = [d for d in issue_order(manifest) if d["doc_id"] in present]
    by_doc: dict[str, Records] = {}
    for r in records:
        by_doc.setdefault(r["doc_id"], []).append(r)
    rels, units = {}, {}
    for d in docs:
        folder = bid.root / d["run"]
        rels[d["doc_id"]] = _read(folder / "relations.json", {})
        units[d["doc_id"]] = [
            {"id": u["id"], "kind": u.get("kind", ""), "side": u.get("side", ""), "text": u.get("text", "")}
            for u in _read(folder / "units.json", [])
        ]
    live = live_entries(read_jsonl(bid.folder / "workspace" / "corrections.jsonl"))
    rejected = {(e.get("fields") or {}).get("relation_id") for e in live if e.get("op") == "reject_relation"}
    ids = reissue.bid_map(bid.folder)  # a user edit on a fact of an older version belongs to its carried counterpart
    edited = {ids.get(e["fact_id"], e["fact_id"]) for e in live if e.get("op") == "edit" and not e.get("conflict_id")}
    applied = ladder.apply(
        docs, by_doc, rels, rejected, manifest.get("precedence"), units_by_doc=units, edited=edited,
    )
    out["conflicts"] = applied.conflicts
    return applied.facts


def _apply_groups(bid: Bid, manifest: dict, records: Records, out: dict) -> Records:
    """Apply the stored groups of the bid (`groups.json`, written by `settle`). Once a bid has
    them, they replace the groups each document came with. Group IDs hash the bid."""
    from . import bidgroup

    stored = _read(bid.folder / "groups.json", None)
    if stored:
        bidgroup.apply_stored_groups(records, stored, bid.bid_id)
    return records


def _apply_pairs(bid: Bid, manifest: dict, records: Records, out: dict) -> Records:
    """The conflicts and review flags the stored pair answers (`pairs.json`) give. Asks no model."""
    from . import bidgroup

    answers = _read(bid.folder / "pairs.json", None)
    if answers:
        order = [d["doc_id"] for d in issue_order(manifest)]
        out["conflicts"] = [*out.get("conflicts", []), *bidgroup.settle(
            bidgroup.pairs(records), answers, records, order, manifest.get("precedence"),
        )]
    return records


# later packages add their steps here, in order
FACT_STEPS: list[FactStep] = [_stamp, _apply_reissues, _apply_relations, _apply_groups, _apply_pairs]


def build(bid: Bid) -> Records:
    """Derive the bid's `facts.json` and `report.json` from the stored result of every extracted
    document, in issue order. Deterministic; calls no model. Returns the facts. A bid with no
    extracted document gets no files."""
    with bid.lock:
        manifest = bid.manifest()
        records: Records = []
        parts: list[dict] = []
        first_base: dict | None = None
        for d in issue_order(manifest):
            if not d.get("run"):
                continue
            folder = bid.root / d["run"]
            try:
                facts = json.loads((folder / "facts.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            facts = copy.deepcopy(facts)
            for f in facts:
                f["doc_id"] = d["doc_id"]
            records += facts
            parts.append({
                "doc_no": d["no"], "doc_id": d["doc_id"], "playbook": d["playbook"], "run": d["run"], "facts": len(facts),
            })
            if first_base is None and _role(d) == "base":
                first_base = d
        if not parts:
            return []
        out: dict = {"conflicts": []}
        for step in FACT_STEPS:
            records = step(bid, manifest, records, out)
        pages, summaries = 0, {}
        if first_base is not None:
            try:
                rep = json.loads((bid.root / first_base["run"] / "report.json").read_text(encoding="utf-8"))
                pages, summaries = rep.get("pages") or 0, rep.get("summaries") or {}
            except (OSError, ValueError):
                pass
        report = {
            "bid_id": bid.bid_id, "documents": parts, "facts": len(records), "pages": pages,
            "doc_id": bid.bid_id, "run_id": "bid", "summaries": summaries,
        }
        if out.get("reissues"):
            report["reissues"] = out["reissues"]
        _write_json(bid.folder / "report.json", report)
        _write_json(bid.folder / "conflicts.json", out["conflicts"])
        _write_json(bid.folder / "facts.json", records)
        return records


async def settle(bid: Bid, client, checker, cfg=None, on_step: Step | None = None) -> Records:
    """Run the bid-level model calls, store what they answer, and build the fact list again.
    GROUP runs over the bid's facts (a category already answered for the same facts is not asked
    again), then the pair check over the pairs code lists (a pair already answered is not asked
    again; one that was skipped is). `client` or `checker` may be None: that part is then not run
    (every pair is recorded as skipped). Steps are reported as document 0, steps `group` and `pairs`."""
    from . import bidgroup

    def say(step: str, status: str, detail: str = "") -> None:
        if on_step:
            on_step(0, step, status, detail)

    facts = build(bid)
    if not facts:
        return []
    say("group", "running")
    report = await bidgroup.group_bid(facts, bid.bid_id, client, cfg, _read(bid.folder / "groups.json", {}))
    with bid.lock:
        _write_json(bid.folder / "groups.json", report)
    say("group", "done", f"{len(report['asked'])} categories asked")
    facts = build(bid)  # with the groups: the pairs start from the ones whose values differ
    say("pairs", "running")
    found = bidgroup.pairs(facts)
    answers = await bidgroup.check_pairs(found, facts, checker, _read(bid.folder / "pairs.json", {}))
    with bid.lock:
        _write_json(bid.folder / "pairs.json", answers)
    say("pairs", "done", f"{sum(1 for p in found if not answers[p['id']]['skipped'])} of {len(found)} pairs answered")
    return build(bid)


__all__ = [
    "Bid", "create", "settle", "list_bids", "issue_order", "doc_numbers", "propose_speakers", "ready", "extract_document",
    "build", "level_of", "apply_levels", "slug", "citation_level",
]

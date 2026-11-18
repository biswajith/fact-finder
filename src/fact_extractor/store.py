"""In-memory fact store (spec section 9, MongoDB replaced by a dict)."""

from __future__ import annotations

import hashlib
import threading
from copy import deepcopy

from .merge import words
from .models import FLAGS, Fact, TaggedDocument


def fact_ids(doc_id: str, facts: list[Fact]) -> list[str]:
    """One ID per fact, the same on a rerun however the model words the fact.

    The ID is a hash of the document, the code and the main (first) cited ID, plus a
    counter when several facts share those, in list order. The wording is left out: the
    model never words a fact the same way twice, so an ID that hashed the text changed on
    about nine facts in ten between two runs (REVIEW.md, "Run-to-run stability").
    A Q fact is keyed on all its IDs, sorted: the two sides have no order. A fact with
    no IDs (kept as needs_review) falls back to its words.
    """
    out: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    for f in facts:
        if not f.ids:
            anchor = "text:" + " ".join(words(f.text))
        elif f.category == "Q":
            anchor = ",".join(sorted(f.ids))
        else:
            anchor = f.ids[0]
        n = seen[(f.category, anchor)] = seen.get((f.category, anchor), 0) + 1
        key = "|".join([doc_id, f.category, anchor] + ([str(n)] if n > 1 else []))
        out.append("f_" + hashlib.sha1(key.encode()).hexdigest()[:10])
    return out


def split_note(note: str) -> tuple[list[str], str]:
    """The note holds flags (prompt 10.1) and sometimes free text; keep both apart."""
    flags: list[str] = []
    rest: list[str] = []
    for part in (p.strip() for p in note.split(",")):
        if part.lower() in FLAGS:
            if part.lower() not in flags:
                flags.append(part.lower())
        elif part:
            rest.append(part)
    return flags, ", ".join(rest)


def to_record(fact: Fact, doc: TaggedDocument, deal_id: str, run_id: str, fid: str) -> dict:
    flags, note = split_note(fact.note)
    return {
        "fact_id": fid,
        "deal_id": deal_id,
        "doc_id": doc.doc_id,
        "run_id": run_id,
        "category": fact.category,
        "text": fact.text,
        "citations": [doc.anchors[i].citation() for i in fact.ids if i in doc.anchors],
        "unresolved_ids": [i for i in fact.ids if i not in doc.anchors],
        "flags": flags,
        "note": note,
        "status": fact.status,
        "source_call": fact.source_call,
        "problems": list(fact.problems),
        "conflicts": list(fact.conflicts),
    }


class InMemoryFactStore:
    """Thread-safe. Saving a run replaces earlier facts for the same deal and document."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._facts: dict[str, dict] = {}  # fact_id -> record
        self._runs: dict[str, dict] = {}  # run_id -> report

    def save_run(self, deal_id: str, doc_id: str, run_id: str, records: list[dict], report: dict) -> None:
        with self._lock:
            stale = [k for k, r in self._facts.items() if r["deal_id"] == deal_id and r["doc_id"] == doc_id]
            for k in stale:
                del self._facts[k]
            for r in records:
                self._facts[r["fact_id"]] = deepcopy(r)
            self._runs[run_id] = deepcopy(report)

    def get(self, fact_id: str) -> dict | None:
        with self._lock:
            r = self._facts.get(fact_id)
            return deepcopy(r) if r else None

    def find(
        self,
        deal_id: str | None = None,
        doc_id: str | None = None,
        category: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        want = {"deal_id": deal_id, "doc_id": doc_id, "category": category, "status": status}
        with self._lock:
            return [
                deepcopy(r)
                for r in self._facts.values()
                if all(v is None or r[k] == v for k, v in want.items())
            ]

    def run_report(self, run_id: str) -> dict | None:
        with self._lock:
            r = self._runs.get(run_id)
            return deepcopy(r) if r else None

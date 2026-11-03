"""In-memory fact store (spec section 9, MongoDB replaced by a dict)."""

from __future__ import annotations

import hashlib
import threading
from copy import deepcopy

from .merge import words
from .models import FLAGS, Fact, TaggedDocument


def fact_id(doc_id: str, fact: Fact) -> str:
    """Stable across reruns of the same document (REVIEW.md item 14)."""
    key = "|".join([doc_id, fact.category, ",".join(sorted(fact.ids)), " ".join(words(fact.text))])
    return "f_" + hashlib.sha1(key.encode()).hexdigest()[:10]


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


def to_record(fact: Fact, doc: TaggedDocument, deal_id: str, run_id: str) -> dict:
    flags, note = split_note(fact.note)
    return {
        "fact_id": fact_id(doc.doc_id, fact),
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

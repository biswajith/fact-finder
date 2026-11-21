"""Stored results (REVIEW.md, "A fact is a labelled source unit").

A document is extracted once. Its result is kept on disk under
`<root>/<doc_id>/<run_id>/` and found again by the PDF's content, the pipeline version
and the doc ID, so opening the same RFP shows the same facts: the model is not asked
twice. A new extraction happens only on request, is stored beside the old one, and
`diff` says what changed.

Files of one result: `facts.json`, `report.json`, `labels.json` (every unit with its
votes), `source.pdf`, and `meta.json` (the key, small enough to scan).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_name(name: str) -> str:
    out = _UNSAFE.sub("_", name)
    return out if out.strip(".") else "_"


def pdf_hash(pdf: str | Path | bytes) -> str:
    data = pdf if isinstance(pdf, bytes) else Path(pdf).read_bytes()
    return hashlib.sha256(data).hexdigest()


_TEXT_FROM_OLD = {"statement": "model", "source": "rfp"}


def upgrade_facts(facts: list[dict]) -> list[dict]:
    """Read results stored with the old `text_from` values ("statement", "source") as
    "model" and "rfp". Every loader of stored facts goes through here."""
    for r in facts:
        if isinstance(r, dict) and r.get("text_from") in _TEXT_FROM_OLD:
            r["text_from"] = _TEXT_FROM_OLD[r["text_from"]]
    return facts


@dataclass
class Stored:
    folder: Path
    meta: dict

    @property
    def facts_path(self) -> Path:
        return self.folder / "facts.json"

    def facts(self) -> list[dict]:
        return upgrade_facts(json.loads(self.facts_path.read_text(encoding="utf-8")))

    def report(self) -> dict:
        return json.loads((self.folder / "report.json").read_text(encoding="utf-8"))


class ResultStore:
    def __init__(self, root: str | Path = "runs") -> None:
        self.root = Path(root)

    def _all(self) -> list[Stored]:
        out = []
        for m in self.root.glob("*/*/meta.json"):
            try:
                meta = json.loads(m.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(meta, dict) and (m.parent / "facts.json").is_file():
                out.append(Stored(m.parent, meta))
        return sorted(out, key=lambda s: s.meta.get("created", ""), reverse=True)

    def find(self, sha256: str, pipeline: str, doc_id: str) -> Stored | None:
        """The newest result for this PDF content, pipeline version and doc ID."""
        for s in self._all():
            if (s.meta.get("pdf_sha256"), s.meta.get("pipeline"), s.meta.get("doc_id")) == (sha256, pipeline, doc_id):
                return s
        return None

    def latest(self, sha256: str, doc_id: str) -> Stored | None:
        """The newest result for this PDF and doc ID under any pipeline version."""
        for s in self._all():
            if (s.meta.get("pdf_sha256"), s.meta.get("doc_id")) == (sha256, doc_id):
                return s
        return None

    def save(self, pdf: str | Path | bytes, sha256: str, pipeline: str, result, labels: list[dict] | None = None) -> Stored:
        """Write one result. Nothing is left behind when a file cannot be written."""
        doc_id, run_id = result.report["doc_id"], result.run_id
        doc_dir = self.root / safe_name(doc_id)
        made = [d for d in (self.root, doc_dir) if not d.exists()]
        folder = doc_dir / safe_name(run_id)
        folder.mkdir(parents=True, exist_ok=False)
        meta = {
            "pdf_sha256": sha256, "pipeline": pipeline, "doc_id": doc_id, "run_id": run_id,
            "deal_id": result.report.get("deal_id", ""), "facts": len(result.facts),
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            (folder / "facts.json").write_text(json.dumps(result.facts, indent=2), encoding="utf-8")
            (folder / "report.json").write_text(json.dumps(result.report, indent=2), encoding="utf-8")
            if labels is not None:
                (folder / "labels.json").write_text(json.dumps(labels, indent=1), encoding="utf-8")
            if isinstance(pdf, bytes):
                (folder / "source.pdf").write_bytes(pdf)
            else:
                shutil.copyfile(pdf, folder / "source.pdf")
            (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        except BaseException:
            shutil.rmtree(made[0] if made else folder, ignore_errors=True)
            raise
        return Stored(folder, meta)


def diff(old: list[dict], new: list[dict]) -> dict:
    """What a new extraction changed, by fact ID (the ID is the source unit)."""
    a = {r["fact_id"]: r for r in old}
    b = {r["fact_id"]: r for r in new}
    both = set(a) & set(b)
    recoded = sorted(
        (f"{b[i]['citations'][0]['id'] if b[i]['citations'] else i}: {a[i]['category']} -> {b[i]['category']}")
        for i in both if a[i]["category"] != b[i]["category"]
    )
    return {
        "same": sum(a[i]["category"] == b[i]["category"] for i in both),
        "recoded": recoded,
        "added": len(set(b) - set(a)),
        "removed": len(set(a) - set(b)),
        "flags_changed": sum(a[i]["category"] == b[i]["category"] and sorted(a[i].get("flags", [])) != sorted(b[i].get("flags", [])) for i in both),
    }

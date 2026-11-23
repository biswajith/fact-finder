"""Stored results (REVIEW.md, "A fact is a labelled source unit").

A document is extracted once. Its result is kept on disk under
`<root>/<doc_id>/<run_id>/` and found again by the PDF's content, the pipeline version
and the doc ID, so opening the same RFP shows the same facts: the model is not asked
twice. A new extraction happens only on request, is stored beside the old one, and
`diff` says what changed.

Files of one result: `facts.json`, `report.json`, `labels.json` (every unit with its
votes), `units.json` (every unit as cut, so the document can be rebuilt without its source
file), the source file as uploaded (`source.pdf`, `source.json`, ...), and `meta.json` (the
key, small enough to scan). A result is found by content, pipeline version, doc ID and
playbook; a result stored before playbooks existed counts as `rfp@1`.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import Anchor, TaggedDocument

DEFAULT_PLAYBOOK = "rfp@1"
SOURCE_SUFFIXES = (".pdf", ".json", ".md", ".txt", ".csv", ".xlsx")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_name(name: str) -> str:
    out = _UNSAFE.sub("_", name)
    return out if out.strip(".") else "_"


def pdf_hash(pdf: str | Path | bytes) -> str:
    data = pdf if isinstance(pdf, bytes) else Path(pdf).read_bytes()
    return hashlib.sha256(data).hexdigest()


content_hash = pdf_hash  # the same hash, for sources that are not PDFs


def source_file_name(source_name: str | None) -> str:
    """`source.<ext>` for the stored copy of the uploaded file; `source.pdf` when the name says
    PDF or is not given, so callers that look for source.pdf still find it."""
    suffix = Path(source_name or "").suffix.lower()
    return "source" + (suffix if suffix in SOURCE_SUFFIXES else ".pdf" if not source_name else ".txt")


def unit_rows(doc: TaggedDocument) -> list[dict]:
    """Every unit of `doc` in document order. `line` is the text the model saw, kept so the
    tagged text can be rebuilt exactly without cutting the source again."""
    lines: dict[str, str] = {}
    for ln in doc.tagged_text.split("\n"):
        if ln.startswith("[") and "] " in ln:
            uid, _, rest = ln[1:].partition("] ")
            lines[uid] = rest
    return [
        {
            "id": a.id, "page": a.page, "page_label": a.page_label, "section": a.section, "text": a.text,
            "kind": a.kind, "bbox": list(a.bbox) if a.bbox else None, "speaker": a.speaker, "side": a.side,
            "line": lines.get(a.id, a.text),
        }
        for a in doc.anchors.values()
    ]


def load_document(folder: str | Path, doc_id: str) -> TaggedDocument | None:
    """The tagged document of a stored result, rebuilt from `units.json`; None when the result
    has none (stored before units were kept)."""
    folder = Path(folder)
    try:
        rows = json.loads((folder / "units.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(rows, list):
        return None
    anchors: dict[str, Anchor] = {}
    lines: list[str] = []
    for r in rows:
        bbox = r.get("bbox")
        anchors[r["id"]] = Anchor(
            doc_id, r["id"], int(r["page"]), str(r.get("page_label", "")), r.get("section", ""), r["text"],
            tuple(bbox) if bbox else None, r["kind"], r.get("speaker", ""), r.get("side", ""),
        )
        lines.append(f"[{r['id']}] {r.get('line', r['text'])}\n")
    pages = 0
    try:
        pages = int(json.loads((folder / "meta.json").read_text(encoding="utf-8")).get("pages") or 0)
    except (OSError, ValueError):
        pass
    return TaggedDocument(doc_id, anchors, "".join(lines), pages or max((a.page for a in anchors.values()), default=0))


@dataclass
class Stored:
    folder: Path
    meta: dict

    @property
    def facts_path(self) -> Path:
        return self.folder / "facts.json"

    def facts(self) -> list[dict]:
        return json.loads(self.facts_path.read_text(encoding="utf-8"))

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

    def find(self, sha256: str, pipeline: str, doc_id: str, playbook: str = DEFAULT_PLAYBOOK) -> Stored | None:
        """The newest result for this content, pipeline version, doc ID and playbook."""
        for s in self._all():
            if (s.meta.get("pdf_sha256"), s.meta.get("pipeline"), s.meta.get("doc_id")) != (sha256, pipeline, doc_id):
                continue
            if s.meta.get("playbook", DEFAULT_PLAYBOOK) == playbook:
                return s
        return None

    def latest(self, sha256: str, doc_id: str) -> Stored | None:
        """The newest result for this PDF and doc ID under any pipeline version."""
        for s in self._all():
            if (s.meta.get("pdf_sha256"), s.meta.get("doc_id")) == (sha256, doc_id):
                return s
        return None

    def save(
        self, pdf: str | Path | bytes, sha256: str, pipeline: str, result, labels: list[dict] | None = None,
        *, playbook: str = DEFAULT_PLAYBOOK, source_name: str | None = None, units: TaggedDocument | None = None,
    ) -> Stored:
        """Write one result. `pdf` is the source file's path or bytes, whatever its form. Nothing is
        left behind when a file cannot be written."""
        doc_id, run_id = result.report["doc_id"], result.run_id
        doc_dir = self.root / safe_name(doc_id)
        made = [d for d in (self.root, doc_dir) if not d.exists()]
        folder = doc_dir / safe_name(run_id)
        folder.mkdir(parents=True, exist_ok=False)
        source_file = source_file_name(source_name)
        meta = {
            "pdf_sha256": sha256, "pipeline": pipeline, "doc_id": doc_id, "run_id": run_id,
            "deal_id": result.report.get("deal_id", ""), "facts": len(result.facts),
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "playbook": playbook, "source_name": source_name or "source.pdf", "source_file": source_file,
        }
        if units is not None:
            meta["pages"] = units.page_count
        try:
            (folder / "facts.json").write_text(json.dumps(result.facts, indent=2), encoding="utf-8")
            (folder / "report.json").write_text(json.dumps(result.report, indent=2), encoding="utf-8")
            if labels is not None:
                (folder / "labels.json").write_text(json.dumps(labels, indent=1), encoding="utf-8")
            if units is not None:
                (folder / "units.json").write_text(json.dumps(unit_rows(units), indent=1), encoding="utf-8")
            if isinstance(pdf, bytes):
                (folder / source_file).write_bytes(pdf)
            else:
                shutil.copyfile(pdf, folder / source_file)
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

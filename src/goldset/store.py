"""The run folder: every stage writes its state here so a run can be inspected and audited.

runs/<name>/
  plan.json              tasks and the first todo list
  rounds/round_NN.json   tasks and items (with full attempt history) after each round
  cache/<stage>/*.json   one file per model call, replayed on re-run
  golden.jsonl           accepted records, with provenance
  needs_human.jsonl      items the loop could not settle, with their last candidate and reasons
  report.md, usage.json
"""

import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel


class RunStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    def write_json(self, name: str, obj: object) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_plain(obj), indent=2, ensure_ascii=False) + "\n")
        return path

    def write_jsonl(self, name: str, rows: Sequence[BaseModel]) -> Path:
        path = self.root / name
        path.write_text("".join(r.model_dump_json() + "\n" for r in rows))
        return path

    def write_text(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text)
        return path


def _plain(obj: object) -> object:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return obj

"""Core data types shared by every stage of the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["sentence", "heading", "table_row", "list_item"]

# Flags the model may write in the note field (prompt 10.1).
# post-award: the fact applies only to the bidder who wins (REVIEW.md, "Before the bid and after award").
FLAGS = ("mandatory", "desirable", "risk", "unclear", "replaced", "post-award", "tentative", "precedence", "both-sides")

# Fact categories (spec section 5).
CATEGORIES: dict[str, str] = {
    "B": "buyer information",
    "C": "contract details",
    "G": "go/no-go gate",
    "X": "disqualification criterion",
    "D": "date",
    "S": "submission delivery",
    "E": "evaluation criterion",
    "R": "requirement",
    "Q": "contradiction",
    "PRIORITY": "buyer priority",
    "DECIDER": "decider or influencer",
    "BUDGET": "buyer budget",
    "QUESTION": "open question",
    "COMPETITOR": "competitor intelligence",
    "ACTION": "action for our team",
}


@dataclass(frozen=True)
class Anchor:
    """One tagged unit of the source document (spec 4.3). The model never sees this."""

    doc_id: str
    id: str
    page: int
    page_label: str
    section: str
    text: str
    bbox: tuple[float, float, float, float] | None
    kind: Kind

    def citation(self) -> dict:
        return {
            "id": self.id,
            "page": self.page,
            "page_label": self.page_label,
            "section": self.section,
            "text": self.text,
            "bbox": list(self.bbox) if self.bbox else None,
        }


@dataclass
class TaggedDocument:
    doc_id: str
    anchors: dict[str, Anchor]  # insertion order = document order
    tagged_text: str
    page_count: int

    def ids_on_page(self, page: int) -> list[str]:
        return [a.id for a in self.anchors.values() if a.page == page]


@dataclass
class OutputLine:
    """One raw line written by the model, split into fields."""

    raw: str
    code: str
    fact: str
    ids: list[str]
    note: str
    field_count: int


@dataclass(frozen=True)
class CallSpec:
    """One planned model call (spec section 5)."""

    name: str
    codes: tuple[str, ...]  # allowed codes, Q included
    task: str  # the per-call task message
    effort: str = "low"


@dataclass
class Usage:
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0


@dataclass
class CallRecord:
    """What happened on one call, for the run report."""

    name: str
    kind: str
    # incomplete: the model answered, but not for every unit it was given (units.py)
    status: Literal["ok", "partial", "failed", "incomplete"] = "ok"
    seconds: float = 0.0  # wall time for the call, queueing and retries included
    queue_seconds: float = 0.0  # waiting for a free slot under the concurrency limit
    ttft_seconds: float | None = None  # last attempt: request sent to first text
    model_seconds: float = 0.0  # last attempt: request sent to last text
    usage: Usage = field(default_factory=Usage)
    lines: int = 0
    retries: int = 0
    log: list[str] = field(default_factory=list)
    output: str = ""  # raw model text, for debugging

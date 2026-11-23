"""Typed library entry point: label a caller's own units and get typed facts back.

The caller supplies units of text it already has (sentences, headings, table rows, list
items), with its own keys. The extractor gives each unit a short ID of its own, runs the
unit-labelling pipeline (units.py, the one `fact-extractor extract` runs) and returns facts
that cite the caller's keys. Nothing is read from or written to disk.

    from fact_extractor.api import SourceUnit, label_units
    result = await label_units("rfp-1", units, client, votes=3)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from . import units as _units
from .llm import LLMClient
from .models import Anchor, Kind, TaggedDocument
from .tagging import _escape

# A caller page with more units than this is cut into several pages for the model's IDs, so
# that a document with no pages (everything on page 1) is still sent in calls of a sensible size.
MAX_UNITS_PER_PAGE = 40

_STATUSES: tuple[Literal["valid", "needs_review", "conflict"], ...] = ("valid", "needs_review", "conflict")


@dataclass(frozen=True)
class SourceUnit:
    key: str  # caller's ID for the unit, returned unchanged
    text: str
    kind: Literal["sentence", "heading", "table_row", "list_item"]
    page: int  # 1-based; 1 for formats with no pages
    page_label: str
    section: str
    speaker: str = ""
    side: str = ""


@dataclass(frozen=True)
class LabelledFact:
    category: str  # one of models.CATEGORIES
    text: str
    unit_keys: tuple[str, ...]  # the units it cites, main unit first
    flags: tuple[str, ...]
    status: Literal["valid", "needs_review", "conflict"]
    problems: tuple[str, ...]
    conflicts_with: tuple[int, ...]  # indexes of contradiction facts in the same result


@dataclass(frozen=True)
class LabelResult:
    facts: tuple[LabelledFact, ...]
    calls: int
    failed_calls: tuple[str, ...]
    input_tokens: int
    output_tokens: int


def document_from_units(doc_id: str, units: Sequence[SourceUnit]) -> tuple[TaggedDocument, dict[str, str]]:
    """Tagged text and anchors for `units`, and the map from short ID to the caller's key.

    One unit is one anchor: the text is never split (as tag_pages splits sentences) or merged.
    Units with no text are skipped. Units are taken in the order given; each run of units on
    the same `page` is one page, and a long run is cut into pages of MAX_UNITS_PER_PAGE. The
    short IDs use that page number (p3.7, p3.h1, p3.t1r2); the anchor's `page` is the same
    number, its `page_label` and `section` are the caller's.
    """
    anchors: dict[str, Anchor] = {}
    lines: list[str] = []
    id_to_key: dict[str, str] = {}
    seen_keys: set[str] = set()

    page_no = 0
    run_page: int | None = None
    in_page = 0
    n_sent = n_head = n_table = n_row = 0
    prev_was_row = False

    for u in units:
        text = u.text.strip()
        if not text:
            continue
        if u.key in seen_keys:
            raise ValueError(f"duplicate unit key {u.key!r}")
        seen_keys.add(u.key)

        if u.page != run_page or in_page >= MAX_UNITS_PER_PAGE:
            page_no += 1
            run_page = u.page
            in_page = 0
            n_sent = n_head = n_table = n_row = 0
            prev_was_row = False
        in_page += 1

        kind: Kind = u.kind
        model_text = text
        if kind == "heading":
            n_head += 1
            id_ = f"p{page_no}.h{n_head}"
            prev_was_row = False
        elif kind == "table_row":
            if not prev_was_row:
                n_table += 1
                n_row = 0
            n_row += 1
            id_ = f"p{page_no}.t{n_table}r{n_row}"
            model_text = text.replace(" | ", " ; ")
            prev_was_row = True
        else:  # sentence, list_item
            n_sent += 1
            id_ = f"p{page_no}.{n_sent}"
            prev_was_row = False

        section = " ".join(u.section.split())
        if kind == "heading" and not section:
            section = " ".join(text.split())
        anchors[id_] = Anchor(doc_id, id_, page_no, u.page_label, section, text, None, kind, u.speaker, u.side)
        lines.append(f"[{id_}] {_escape(model_text)}")
        id_to_key[id_] = u.key

    tagged = TaggedDocument(doc_id, anchors, "".join(f"{ln}\n" for ln in lines), page_no)
    return tagged, id_to_key


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _texts(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


async def label_units(
    doc_id: str, units: Sequence[SourceUnit], client: LLMClient, *, votes: int = 3
) -> LabelResult:
    """Run the unit-labelling pipeline over `units` with the caller's model client.

    The pipeline and its settings are those of `fact-extractor extract` (units.Config with
    `votes` labelling passes), except that the second-round presentation calls (the buyer
    summaries and the grouping of repeated facts) are not made: their output is not part of
    the result. A model call that fails is retried once and then recorded in `failed_calls`;
    it does not raise.
    """
    doc, id_to_key = document_from_units(doc_id, units)
    if not doc.anchors:
        return LabelResult((), 0, (), 0, 0)
    cfg = _units.Config(votes=votes, brief=False, grouping=False)
    run = await _units.extract(doc, client, deal_id=doc_id, cfg=cfg)

    records: list[Mapping[str, object]] = [r for r in run.facts]
    index_of = {_text(r.get("fact_id")): n for n, r in enumerate(records)}
    facts: list[LabelledFact] = []
    for r in records:
        keys: list[str] = []
        problems = _texts(r.get("problems"))
        for c in _mappings(r.get("citations")):
            key = id_to_key.get(_text(c.get("id")))
            if key is None:
                if "cited an unknown unit" not in problems:
                    problems.append("cited an unknown unit")
            elif key not in keys:
                keys.append(key)
        status = _text(r.get("status"))
        status = status if status in _STATUSES else "needs_review"
        if not keys:
            status = "needs_review"
        conflicts = tuple(index_of[f] for f in _texts(r.get("conflicts")) if f in index_of)
        facts.append(
            LabelledFact(
                category=_text(r.get("category")),
                text=_text(r.get("text")),
                unit_keys=tuple(keys),
                flags=tuple(_texts(r.get("flags"))),
                status="valid" if status == "valid" else ("conflict" if status == "conflict" else "needs_review"),
                problems=tuple(problems),
                conflicts_with=conflicts,
            )
        )

    calls = _mappings(run.report.get("calls"))
    input_tokens = sum(_int(_as_map(c.get("usage")).get("input_tokens")) for c in calls)
    return LabelResult(
        facts=tuple(facts),
        calls=len(calls),
        failed_calls=tuple(_texts(run.report.get("failed_calls"))),
        input_tokens=input_tokens,
        output_tokens=_int(run.report.get("output_tokens")),
    )


def _as_map(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}

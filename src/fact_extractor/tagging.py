"""Parse and tag (spec section 4).

Turns pages of blocks into ID-tagged text plus the anchor map. The PDF reader
in `pdf.py` produces the blocks; tests and other chunkers can build them
directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Anchor, Kind, TaggedDocument

BBox = tuple[float, float, float, float]

LONG_SENTENCE_WORDS = 60


@dataclass
class Span:
    """A piece of text with its position. Paragraphs are lists of spans (lines)."""

    text: str
    bbox: BBox | None = None


@dataclass
class Heading:
    text: str
    bbox: BBox | None = None


@dataclass
class Paragraph:
    spans: list[Span]
    list_item: bool = False

    @classmethod
    def of(cls, text: str, bbox: BBox | None = None, list_item: bool = False) -> "Paragraph":
        return cls([Span(text, bbox)], list_item)


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]
    row_bboxes: list[BBox | None] = field(default_factory=list)


Block = Heading | Paragraph | Table


@dataclass
class Page:
    number: int  # printed page number of the PDF file, 1-based
    label: str  # footer label
    blocks: list[Block]


# --- sentence splitting -----------------------------------------------------

_ABBREV = {
    "mr", "mrs", "ms", "dr", "no", "nos", "inc", "ltd", "co", "corp", "llc", "jr", "sr",
    "st", "e.g", "i.e", "etc", "vs", "approx", "dept", "est", "fig", "sec", "art",
    "u.s", "u.s.a", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec", "p.m", "a.m", "ref", "para", "min", "max", "attn", "ph", "tel",
}
_BOUNDARY = re.compile(r"[.!?][\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character ranges of sentences in `text`."""
    out: list[tuple[int, int]] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        before = text[start : m.start() + 1]
        word = re.search(r"([A-Za-z.]+)\.$", before)
        if word and word.group(1).lower().rstrip(".") in _ABBREV:
            continue
        # "Section 4." followed by "2" never happens with \s+, but "4.2" is safe: no space.
        # A single capital initial ("J. Smith") is not a boundary.
        if re.search(r"(?:^|\s)[A-Z]\.$", before):
            continue
        # A list marker ("1.", "a.", "iv.") is part of the item, not a sentence.
        if re.fullmatch(r"\s*\(?(?:\d{1,3}|[a-z]|[ivx]{1,4})[.)]", before, re.I):
            continue
        out.append((start, m.start() + 1))
        start = m.end()
    if text[start:].strip():
        out.append((start, len(text)))
    return [(s, e) for s, e in ((_lstrip(text, s), _rstrip(text, e)) for s, e in out) if e > s]


def _lstrip(t: str, s: int) -> int:
    while s < len(t) and t[s].isspace():
        s += 1
    return s


def _rstrip(t: str, e: int) -> int:
    while e > 0 and t[e - 1].isspace():
        e -= 1
    return e


def split_long(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split a sentence over 60 words at semicolons (spec 4.1)."""
    if len(text[start:end].split()) <= LONG_SENTENCE_WORDS or ";" not in text[start:end]:
        return [(start, end)]
    parts: list[tuple[int, int]] = []
    s = start
    for m in re.finditer(";", text[start:end]):
        e = start + m.end()
        parts.append((_lstrip(text, s), e))
        s = e
    parts.append((_lstrip(text, s), end))
    return [(a, b) for a, b in parts if text[a:b].strip()]


# --- tagging ----------------------------------------------------------------


def _escape(text: str) -> str:
    # Source text must never look like an ID tag (REVIEW.md item 5).
    return " ".join(text.replace("[", "(").replace("]", ")").split())


def _union(boxes: list[BBox]) -> BBox | None:
    if not boxes:
        return None
    return (
        round(min(b[0] for b in boxes), 1),
        round(min(b[1] for b in boxes), 1),
        round(max(b[2] for b in boxes), 1),
        round(max(b[3] for b in boxes), 1),
    )


def table_row_text(header: list[str], row: list[str]) -> str:
    """Header names next to each cell (spec 4.1). Original text for the anchor map."""
    cells = []
    for i, cell in enumerate(row):
        name = header[i].strip() if i < len(header) and header[i] else f"Column {i + 1}"
        cells.append(f"{name}: {' '.join((cell or '').split())}")
    return " | ".join(cells)


def tag_pages(doc_id: str, pages: list[Page]) -> TaggedDocument:
    anchors: dict[str, Anchor] = {}
    lines: list[str] = []
    section = ""
    prev_table_header: list[str] | None = None

    def add(id_: str, page: Page, text: str, bbox: BBox | None, kind: Kind, model_text: str | None = None) -> None:
        anchors[id_] = Anchor(doc_id, id_, page.number, page.label, section, text, bbox, kind)
        lines.append(f"[{id_}] {_escape(model_text if model_text is not None else text)}")

    for page in pages:
        n_sent = n_head = n_table = 0
        for bi, block in enumerate(page.blocks):
            if isinstance(block, Heading):
                n_head += 1
                section = " ".join(block.text.split())
                add(f"p{page.number}.h{n_head}", page, section, block.bbox, "heading")
            elif isinstance(block, Paragraph):
                text, offsets = _join_spans(block.spans)
                kind: Kind = "list_item" if block.list_item else "sentence"
                # A list item is split like any paragraph; its first sentence is the item.
                for k, (s0, e0) in enumerate(split_sentences(text)):
                    if k:
                        kind = "sentence"
                    for s, e in split_long(text, s0, e0):
                        n_sent += 1
                        boxes = [b for (a, z, b) in offsets if b and a < e and z > s]
                        add(f"p{page.number}.{n_sent}", page, text[s:e].strip(), _union(boxes), kind)
            elif isinstance(block, Table):
                n_table += 1
                header = block.header
                # A table continued from the previous page without its own header.
                if not any(h.strip() for h in header) and prev_table_header and bi == 0:
                    header = prev_table_header
                prev_table_header = header
                for r, row in enumerate(block.rows, start=1):
                    if not any((c or "").strip() for c in row):
                        continue
                    text = table_row_text(header, row)
                    bbox = block.row_bboxes[r - 1] if r - 1 < len(block.row_bboxes) else None
                    add(
                        f"p{page.number}.t{n_table}r{r}", page, text, bbox, "table_row",
                        model_text=text.replace(" | ", " ; "),
                    )
    return TaggedDocument(doc_id, anchors, "\n".join(lines) + "\n", len(pages))


def _join_spans(spans: list[Span]) -> tuple[str, list[tuple[int, int, BBox | None]]]:
    parts: list[str] = []
    offsets: list[tuple[int, int, BBox | None]] = []
    pos = 0
    for sp in spans:
        t = sp.text.strip()
        if not t:
            continue
        if parts:
            # Re-join words hyphenated over a line break: "manage-" + "ment", "Self-" + "Insurance".
            if parts[-1].endswith("-") and t[:1].isalpha():
                if t[:1].islower():
                    parts[-1] = parts[-1][:-1]
                    pos -= 1
            else:
                parts.append(" ")
                pos += 1
        parts.append(t)
        offsets.append((pos, pos + len(t), sp.bbox))
        pos += len(t)
    return "".join(parts), offsets

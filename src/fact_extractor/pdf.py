"""Read a text PDF into tagging blocks with PyMuPDF.

Headings are found by font size or bold short lines; tables by PyMuPDF's
table finder. Page labels and running headers/footers are removed from the body text.
Scanned pages (no text layer) are out of scope (spec section 14).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import pymupdf

from .tagging import BBox, Heading, Page, Paragraph, Span, Table

_LABEL = re.compile(r"^[-\u2013\s]*(?:page\s+)?([ivxlcdm]+|\d+|[A-Z]-\d+)(?:\s+of\s+\d+)?[-\u2013\s]*$", re.I)
_BULLET = re.compile(r"^(?:[\u2022\u25cf\u25aa\uf0b7]\s*|[\u2013\-*]\s+|\(?[a-z0-9]{1,3}[.)]\s+)", re.I)
_NUMBERED_HEADING = re.compile(r"^(?:section\s+|article\s+|part\s+)?\d+(?:\.\d+)*\.?\s+\S", re.I)
EDGE = 0.2  # top/bottom share of the page where running headers and footers live
REPEAT_SHARE = 0.4  # a line on this share of pages (at least 3) is a running header


@dataclass
class _Line:
    text: str
    bbox: BBox
    size: float
    bold: bool


def read_pdf(path: str) -> list[Page]:
    doc = pymupdf.open(path)
    raw = []
    for page in doc:
        try:
            tables = list(page.find_tables().tables)
        except Exception:  # table finder is best effort
            tables = []
        raw.append((page, tables, _lines(page, [pymupdf.Rect(t.bbox) for t in tables])))


    # Running headers and footers: the same line (digits ignored) near the edge of many pages.
    seen: Counter[str] = Counter()
    for page, _, lines in raw:
        h = page.rect.height
        seen.update({_key(ln.text) for ln in lines if _at_edge(ln, h)})
    min_pages = max(3, int(len(raw) * REPEAT_SHARE))
    running = {k for k, n in seen.items() if n >= min_pages}

    return [_read_page(page, i + 1, tables, lines, running) for i, (page, tables, lines) in enumerate(raw)]


def _body_size(lines: list[_Line]) -> float:
    """The size most characters on the page are set in. Per page: RFPs mix body sizes."""
    weight: Counter[float] = Counter()
    for ln in lines:
        weight[ln.size] += len(ln.text)
    return weight.most_common(1)[0][0] if weight else 10.0


def _key(text: str) -> str:
    return re.sub(r"\d+", "#", " ".join(text.lower().split()))


def _at_edge(ln: _Line, height: float) -> bool:
    return ln.bbox[3] < height * EDGE or ln.bbox[1] > height * (1 - EDGE)


def _lines(page: pymupdf.Page, table_rects: list) -> list[_Line]:
    """Text lines outside tables, with pieces on the same baseline joined ("1.0" + "PURPOSE")."""
    pieces = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0 or any(pymupdf.Rect(b["bbox"]).intersects(r) for r in table_rects):
            continue
        for line in b["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if spans:
                pieces.append((line["bbox"], spans))
    pieces.sort(key=lambda p: (round(p[0][1]), p[0][0]))
    out: list[_Line] = []
    group: list = []

    def close() -> None:
        if not group:
            return
        spans = [s for _, sp in group for s in sp]
        text = "  ".join("".join(s["text"] for s in sp).strip() for _, sp in group)
        box = tuple(round(v, 1) for v in (
            min(g[0][0] for g in group), min(g[0][1] for g in group),
            max(g[0][2] for g in group), max(g[0][3] for g in group),
        ))
        size = round(max(s["size"] for s in spans), 1)
        bold = all(s["flags"] & 16 or "Bold" in s["font"] for s in spans)
        out.append(_Line(" ".join(text.split()), box, size, bold))  # type: ignore[arg-type]

    for p in pieces:
        if group and abs(p[0][1] - group[-1][0][1]) < 2 and p[0][0] >= group[-1][0][2] - 1:
            group.append(p)
        else:
            close()
            group = [p]
    close()
    return out


def _read_page(
    page: pymupdf.Page, number: int, tables: list, lines: list[_Line], running: set[str]
) -> Page:
    height = page.rect.height
    body_size = _body_size(lines)
    label = page.get_label() or ""
    items: list[tuple[float, object]] = []
    para: list[Span] = []
    para_is_item = False
    para_y = 0.0
    prev_line: BBox | None = None

    def flush() -> None:
        nonlocal para, para_is_item
        if para:
            items.append((para_y, Paragraph(para, para_is_item)))
        para, para_is_item = [], False

    for ln in lines:
        text, bbox = ln.text, ln.bbox
        y0 = bbox[1]
        if _at_edge(ln, height):
            m = _LABEL.match(text)
            if m:
                if not page.get_label():
                    label = m.group(1)
                continue  # page numbers are not content
            if _key(text) in running:
                continue  # running headers and footers are not content
        words = len(text.split())
        letters = [c for c in text if c.isalpha()]
        upper = len(letters) >= 3 and all(c.isupper() for c in letters)
        is_heading = words <= 14 and not text.endswith((".", ",", ";")) and (
            ln.size >= body_size * 1.15 or (ln.bold and (bool(_NUMBERED_HEADING.match(text)) or upper))
        )
        if _BULLET.match(text):
            flush()
            para_is_item = True
            para_y = y0
            para.append(Span(text, bbox))
            prev_line = bbox
            continue
        if is_heading:
            flush()
            items.append((y0, Heading(text, bbox)))
            prev_line = None
            continue
        # A new paragraph starts after a vertical gap larger than about half a line;
        # PDF text blocks alone are not reliable paragraph boundaries.
        if para and prev_line is not None:
            line_h = prev_line[3] - prev_line[1]
            if y0 - prev_line[3] > line_h * 0.6:
                flush()
        if not para:
            para_y = y0
        para.append(Span(text, bbox))
        prev_line = bbox
    flush()

    for t in tables:
        data = t.extract()
        if not data:
            continue
        header = [c or "" for c in (t.header.names if t.header and not t.header.external else data[0])]
        rows = data if (t.header and t.header.external) else data[1:]
        row_boxes = [tuple(round(v, 1) for v in r.bbox) for r in t.rows]
        if not (t.header and t.header.external):
            row_boxes = row_boxes[1:]
        items.append((t.bbox[1], Table(header, [[c or "" for c in r] for r in rows], row_boxes)))  # type: ignore[arg-type]

    items.sort(key=lambda it: it[0])
    return Page(number, str(label or number), [blk for _, blk in items])  # type: ignore[misc]

"""Readers: turn any file into the units the labelling pipeline reads.

How a file is read depends only on its format, never on the document type: an RFP may come as a
PDF, a Word file or a sheet, and a call as a PDF or plain text. What a document is (its type) and
how its content is organised (who speaks, which part is a heading) is for the model to say, not
for the reader to assume. A reader only keeps what the format itself makes plain: pages, headings
and tables.

- PDF: `web.runs.tag_pdf`, which reads the layout and boxes (see `read_document`).
- Word (.docx): paragraphs in order, a heading style as a heading, a table as table rows.
- Sheet (.csv, .xlsx): one sheet a page, each row a table row under the first row.
- JSON: its text values in order, one record a line.
- Anything else: text, with markdown headings, lists and tables kept when they are there.

Each reader returns `api.SourceUnit` rows (keys unique, in reading order); `api.document_from_units`
gives them their short IDs and anchors.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime
from pathlib import Path

from .api import SourceUnit
from .tagging import split_sentences, table_row_text

FORMS = ("pdf", "word", "sheet", "json", "text")


def form_of(name: str, data: bytes) -> str:
    """The file's format, from its extension and its first bytes."""
    ext = Path(name).suffix.lower()
    if ext == ".pdf" or data[:5] == b"%PDF-":
        return "pdf"
    if ext == ".docx":
        return "word"
    if ext in (".csv", ".xlsx"):
        return "sheet"
    if ext == ".json":
        return "json"
    return "text"


def read(data: bytes, name: str) -> list[SourceUnit]:
    """The units of any file that is not a PDF."""
    form = form_of(name, data)
    if form == "word":
        return read_word(data)
    if form == "sheet":
        return cut_sheet(data, name)
    if form == "json":
        return read_json(data)
    if form == "text":
        return cut_notes(data.decode("utf-8-sig", errors="replace"))
    raise ValueError("pdf units come from runs.tag_pdf; use read_document")


def read_document(data: bytes, name: str, doc_id: str, runs_root: str | Path):
    """The tagged document of any file: a PDF with its layout, anything else from `read`."""
    if form_of(name, data) == "pdf":
        from .web import runs

        return runs.tag_pdf(data, doc_id, runs_root)
    from .api import document_from_units

    return document_from_units(doc_id, read(data, name))[0]


def plain_text(data: bytes, name: str, words: int | None = None, pages: int | None = None) -> str:
    """The text of any file, one unit (or PDF line) a line, up to `words` words and, for a PDF, its
    first `pages` pages: what the model reads to say what a document is. Empty for a file that
    cannot be read."""
    try:
        if form_of(name, data) == "pdf":
            import pymupdf

            with pymupdf.open(stream=data, filetype="pdf") as doc:
                count = doc.page_count if pages is None else min(pages, doc.page_count)
                lines = "\n".join(doc[i].get_text() for i in range(count)).splitlines()
        else:
            lines = [u.text for u in read(data, name)]
    except Exception:  # an unreadable file is still a document the user can classify by hand
        return ""
    out, left = [], words
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if left is None:
            out.append(" ".join(parts))
            continue
        out.append(" ".join(parts[:left]))
        left -= len(parts)
        if left <= 0:
            break
    return "\n".join(out)


# --- Word -----------------------------------------------------------------------------


def read_word(data: bytes) -> list[SourceUnit]:
    """A .docx: body paragraphs and tables in order. A paragraph whose style is a heading (or the
    title) is a heading and sets the section; a list paragraph is a list item; other paragraphs are
    split into sentences. A table's first row is its header, each later row a table row. A heading
    of the first level starts a new page, labelled with its text."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    out: list[SourceUnit] = []
    state = {"page": 1, "label": "1", "section": ""}

    def add(text: str, kind: str) -> None:
        text = " ".join(text.split())
        if text:
            out.append(SourceUnit(f"w{len(out) + 1}", text, kind, state["page"], state["label"], state["section"]))  # type: ignore[arg-type]

    for block in doc.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(block, doc)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name if para.style is not None else "").lower()
            if style.startswith("heading") or style == "title":
                level = re.search(r"\d+", style)
                if out and (style == "title" or (level and level.group(0) == "1")):
                    state["page"] += 1
                if style == "title" or (level and level.group(0) == "1"):
                    state["label"] = text[:40]
                state["section"] = text
                add(text, "heading")
            elif "list" in style or para._p.pPr is not None and para._p.pPr.numPr is not None:
                add(text, "list_item")
            else:
                for a, b in split_sentences(text) or [(0, len(text))]:
                    add(text[a:b], "sentence")
        elif tag == "tbl":
            rows = [[" ".join(c.text.split()) for c in r.cells] for r in Table(block, doc).rows]
            rows = [r for r in rows if any(r)]
            if not rows:
                continue
            header = rows[0]
            if len(rows) == 1:
                add(" | ".join(c for c in header if c), "table_row")
            for r in rows[1:]:
                filled = [c for c in r if c]
                add(filled[0], "sentence") if len(set(filled)) == 1 else add(table_row_text(header, r), "table_row")
    return out


# --- JSON -----------------------------------------------------------------------------


def read_json(data: bytes) -> list[SourceUnit]:
    """JSON: the text values in document order, whatever the keys. A record's text values go on one
    line as `key: value; key: value`, so the words keep what the record says about them; a record with
    one value that reads as words is just those words. Numbers and true/false are left out. Text that is not JSON is read
    as text."""
    text = data.decode("utf-8-sig", errors="replace")
    try:
        obj = json.loads(text)
    except ValueError:
        return cut_notes(text)
    lines: list[str] = []

    def walk(v: object, key: str = "") -> None:
        if isinstance(v, dict):
            flat = [(k, x.strip()) for k, x in v.items() if isinstance(x, str) and x.strip()]
            if flat:
                lone = flat[0][1] if len(flat) == 1 else ""
                # a lone value that reads as words stands alone; an ID or a code keeps its key
                lines.append(lone if lone and (" " in lone or lone[-1:] in ".!?") else "; ".join(f"{k}: {x}" for k, x in flat))
            for x in v.values():
                if isinstance(x, (dict, list)):
                    walk(x)
        elif isinstance(v, list):
            if v and all(isinstance(x, str) for x in v):
                lines.append(", ".join(x.strip() for x in v if x.strip()))
            else:
                for x in v:
                    walk(x)
        elif isinstance(v, str) and v.strip():
            lines.append(v.strip())

    walk(obj)
    return cut_notes("\n\n".join(ln for ln in lines if ln))


# --- notes ----------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+(.*)$")
_SEPARATOR = re.compile(r"^:?-{2,}:?$")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _lines_to_paragraphs(lines: list[str]) -> list[str]:
    """Join the lines of one block where a line only wraps the one before it: the line before has no
    closing punctuation and this one starts in lower case. Any other line break is kept, so lines
    that each say something of their own (a speaker's turn, a log entry) are not run together."""
    out: list[str] = []
    for line in lines:
        if out and not re.search(r"[.!?:;\"')\]]$", out[-1]) and line[:1].islower():
            out[-1] += " " + line
        else:
            out.append(line)
    return out


def cut_notes(text: str) -> list[SourceUnit]:
    """Markdown or plain notes. A heading is a heading unit and sets the section; a list item is one
    unit; a table row is one unit `header: value | header: value`; a paragraph is split into
    sentences. Each `##` section starts a new page, labelled with its number (0 for the part
    before the first one)."""
    out: list[SourceUnit] = []
    state = {"page": 1, "label": "0", "section": "", "n": 0}
    paragraph: list[str] = []
    item: list[str] = []
    header: list[str] | None = None

    def add(text: str, kind: str) -> None:
        text = " ".join(text.split())
        if text:
            state["n"] += 1
            out.append(SourceUnit(f"n{state['n']}", text, kind, state["page"], state["label"], state["section"]))  # type: ignore[arg-type]

    def flush() -> None:
        if paragraph:
            for joined in _lines_to_paragraphs(paragraph):
                for s, e in split_sentences(joined) or [(0, len(joined))]:
                    add(joined[s:e], "sentence")
            paragraph.clear()
        if item:
            add(" ".join(item), "list_item")
            item.clear()

    sections = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush()
            header = None
            continue
        h = _HEADING.match(stripped)
        if h:
            flush()
            header = None
            title = h.group(2).strip()
            if len(h.group(1)) == 2:
                sections += 1
                if out:  # the part before the first ## is a page of its own
                    state["page"] += 1
                state["label"] = str(sections)
            state["section"] = title
            add(title, "heading")
            continue
        if stripped.startswith("|"):
            flush()
            cells = _cells(stripped)
            if all(_SEPARATOR.match(c) for c in cells if c) and any(cells):
                continue
            if header is None:
                header = cells
                continue
            add(table_row_text(header, cells), "table_row")
            continue
        header = None
        m = _ITEM.match(line)
        if m:
            flush()
            item.append(m.group(1))
        elif item and line[:1] in (" ", "\t"):
            item.append(stripped)  # a wrapped list item
        else:
            if item:
                flush()
            paragraph.append(stripped.lstrip("> ").strip() if stripped.startswith(">") else stripped)
    flush()
    return out


# --- sheets ---------------------------------------------------------------------------


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())


def _sheet_rows(data: bytes, name: str) -> list[tuple[str, list[list[str]]]]:
    if name.lower().endswith(".xlsx"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ValueError("xlsx needs openpyxl") from None
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        try:
            return [(ws.title, [[_cell(c) for c in row] for row in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
        finally:
            wb.close()
    text = data.decode("utf-8-sig", errors="replace")
    return [("1", [[_cell(c) for c in row] for row in csv.reader(io.StringIO(text))])]


def cut_sheet(data: bytes, name: str) -> list[SourceUnit]:
    """A `.csv` or `.xlsx`. One sheet is one page, its first non-empty row the header. Each later
    row with a value is one table row (`header: value | ...`, blank cells left out); a row with
    one value only is a sentence (an instruction or a title)."""
    out: list[SourceUnit] = []
    page = 0
    for title, rows in _sheet_rows(data, name):
        header: list[str] | None = None
        started = False
        for r, row in enumerate(rows, start=1):
            if not any(row):
                continue
            if header is None:
                header = row
                continue
            if not started:
                page += 1
                started = True
            filled = [c for c in row if c]
            key = f"s{page}r{r}"
            if len(filled) == 1:
                out.append(SourceUnit(key, filled[0], "sentence", page, title, ""))
            else:
                out.append(SourceUnit(key, table_row_text(header, row), "table_row", page, title, ""))
    return out

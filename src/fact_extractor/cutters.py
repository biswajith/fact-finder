"""Cutters: turn a file that is not a PDF into the units the labelling pipeline reads.

Each cutter returns `api.SourceUnit` rows (keys unique, in reading order); `api.document_from_units`
gives them their short IDs and anchors. A transcript turn, a notes section or a sheet is a "page":
the pipeline labels in batches of pages, and a citation shows the page label.

PDFs are not cut here: `web.runs.tag_pdf` reads them with their layout and boxes.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime

from .api import SourceUnit
from .tagging import split_sentences, table_row_text

FORMS = ("pdf", "transcript", "notes", "sheet")

_TURN = re.compile(r"^\[(\d{1,2}):(\d{2}):(\d{2})\]\s*([^:]+?)\s*:\s*(.*)$")
_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"), start=1)}
_DATE_TEXT = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


# --- which cutter ---------------------------------------------------------------------


def form_of(name: str, data: bytes) -> str:
    """Guess `pdf | transcript | notes | sheet` from the extension and, for `.json` and `.txt`, the content."""
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext == "pdf" or data[:5] == b"%PDF-":
        return "pdf"
    if ext in ("csv", "xlsx"):
        return "sheet"
    if ext == "json":
        try:
            obj = json.loads(data.decode("utf-8-sig"))
        except ValueError:
            return "notes"
        return "transcript" if _gong_calls(obj) else "notes"
    if ext == "txt":
        lines = data.decode("utf-8-sig", errors="replace").splitlines()
        return "transcript" if sum(bool(_TURN.match(ln.strip())) for ln in lines) >= 3 else "notes"
    return "notes"


def reader(cutter: str, name: str, data: bytes) -> str:
    """How to read this file under a playbook whose cutter is `cutter`. The file decides how it is read,
    the playbook only what is extracted: a PDF is read as a PDF and a sheet as a sheet whatever the
    document type; a text file is read the way the playbook says when that way reads text (a
    transcript or notes), else by its own form."""
    form = form_of(name, data)
    if form in ("pdf", "sheet"):
        return form
    return cutter if cutter in ("transcript", "notes") else form


def cut(form: str, data: bytes, name: str) -> list[SourceUnit]:
    """The units of a file of this form."""
    if form == "transcript":
        return cut_transcript(data, name)[0]
    if form == "notes":
        return cut_notes(data.decode("utf-8-sig", errors="replace"))
    if form == "sheet":
        return cut_sheet(data, name)
    raise ValueError("pdf units come from runs.tag_pdf, not a cutter" if form == "pdf" else f"unknown form {form!r}")


# --- transcripts ----------------------------------------------------------------------


def _gong_calls(obj: object) -> bool:
    """Whether `obj` has the two Gong responses: a call with a transcript."""
    try:
        return bool(obj["transcript"]["callTranscripts"][0]["transcript"])  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return False


def _phone(value: str) -> str:
    """One spelling for a dial-in number, so a spoken-form line and a Gong party agree:
    `+1 845 555 0142` and `+1 845-555-0142` both give `+1 845-555-0142`."""
    digits = re.sub(r"\D", "", value)
    if value.strip().startswith("+") and len(digits) == 11 and digits[0] == "1":
        return f"+1 {digits[1:4]}-{digits[4:7]}-{digits[7:]}"
    return value.strip()


def _clock(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _turn_units(turns: list[tuple[str, str, str, str]]) -> list[SourceUnit]:
    """`turns` = (speaker, hh:mm:ss, section, text). One turn is one page, one sentence one unit."""
    out: list[SourceUnit] = []
    for n, (speaker, label, section, text) in enumerate(turns, start=1):
        spans = split_sentences(text) or ([(0, len(text))] if text.strip() else [])
        for k, (s, e) in enumerate(spans, start=1):
            out.append(SourceUnit(f"t{n}.{k}", text[s:e].strip(), "sentence", n, label, section, speaker))
    return out


def cut_transcript(data: bytes, name: str) -> tuple[list[SourceUnit], dict]:
    """A call transcript: a Gong export (JSON with `extensive` and `transcript`) or plain text with
    `[hh:mm:ss] Name: text` lines. Returns the units and the call's info
    `{"title", "date", "speakers": [{"id", "name", "email", "title", "affiliation", "organisation",
    "note"}]}`; the speakers are those who spoke, in order of first speech. `organisation` is the email's
    domain for a Gong party, and for plain text what the header's attendee list says."""
    text = data.decode("utf-8-sig", errors="replace")
    if name.lower().endswith(".json") or text.lstrip().startswith("{"):
        try:
            obj = json.loads(text)
        except ValueError as e:
            raise ValueError(f"not a Gong export: {e}") from None
        if not _gong_calls(obj):
            raise ValueError("not a Gong export: no transcript found")
        return _cut_gong(obj)
    return _cut_text(text)


def _cut_gong(obj: dict) -> tuple[list[SourceUnit], dict]:
    call = ((obj.get("extensive") or {}).get("calls") or [{}])[0]
    meta = call.get("metaData") or {}
    parties = {p["speakerId"]: p for p in call.get("parties") or [] if p.get("speakerId")}

    def speaker_name(sid: str) -> str:
        p = parties.get(sid) or {}
        return (p.get("name") or "").strip() or _phone(p.get("phoneNumber") or "") or f"Speaker {sid}"

    turns: list[tuple[str, str, str, str]] = []
    spoke: dict[str, None] = {}
    for mono in obj["transcript"]["callTranscripts"][0]["transcript"]:
        sentences = [s for s in mono.get("sentences") or [] if str(s.get("text", "")).strip()]
        if not sentences:
            continue
        sid = str(mono.get("speakerId", ""))
        spoke[sid] = None
        start = int(sentences[0].get("start") or 0) // 1000
        turns.append((speaker_name(sid), _clock(start), mono.get("topic") or "",
                      " ".join(str(s["text"]).strip() for s in sentences)))
    speakers = []
    for sid in spoke:
        p = parties.get(sid) or {}
        speakers.append({
            "id": sid, "name": speaker_name(sid), "email": p.get("emailAddress") or "",
            "title": p.get("title") or "", "affiliation": p.get("affiliation") or "",
            "organisation": _domain(p.get("emailAddress") or ""), "note": "",
        })
    info = {"title": meta.get("title") or "", "date": str(meta.get("started") or "")[:10], "speakers": speakers}
    return _turn_units(turns), info


def _domain(email: str) -> str:
    """The part of an email address after `@`, as written; empty when there is none."""
    return email.rpartition("@")[2].strip() if "@" in email else ""


_NOTE = re.compile(r"\s*\(([^()]*)\)\s*$")


def _attendee(line: str) -> dict | None:
    """One attendee line of a plain-text header: `Name - Organisation, Title (note)`. Organisation,
    title and note are each optional; a dial-in is a number, perhaps with a note. None for a line
    that is not a person (a blank line or a label such as `Attendees:`)."""
    line = line.strip().lstrip("-*\u2022 ").strip()
    if not line or line.endswith(":"):
        return None
    note = ""
    m = _NOTE.search(line)
    if m:
        note, line = m.group(1).strip(), line[: m.start()].strip()
    name, sep, rest = line.partition(" - ")
    name = name.strip()
    if not name:
        return None
    if name.startswith("+"):
        name = _phone(name)
    organisation, _, title = rest.partition(",") if sep else ("", "", "")
    return {"name": name, "organisation": organisation.strip(), "title": title.strip(), "note": note}


def _attendees(header: list[str]) -> dict[str, dict]:
    """The people the header lists after an `Attendees:` line (up to the next blank line or label), by name."""
    out: dict[str, dict] = {}
    inside = False
    for raw in header:
        line = raw.strip()
        if re.match(r"^(attendees|participants)\s*:?\s*$", line, re.I):
            inside = True
            continue
        if not inside:
            continue
        if not line or re.match(r"^[A-Za-z ]{2,20}:\s", line):
            break
        who = _attendee(line)
        if who:
            out.setdefault(who["name"].casefold(), who)
    return out


def _text_date(header: str) -> str:
    m = _DATE_ISO.search(header)
    if m:
        return m.group(0)
    m = _DATE_TEXT.search(header)
    if m:
        return f"{int(m.group(3)):04d}-{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    return ""


def _cut_text(text: str) -> tuple[list[SourceUnit], dict]:
    header: list[str] = []
    turns: list[list] = []  # [speaker, label, text]
    for raw in text.splitlines():
        line = raw.strip()
        m = _TURN.match(line)
        if m:
            h, mi, s, who, said = m.groups()
            who = _phone(who) if who.strip().startswith("+") else who.strip()
            if turns and turns[-1][0] == who:  # Gong holds one speaker's run as one monologue
                turns[-1][2] += " " + said.strip()
            else:
                turns.append([who, _clock(int(h) * 3600 + int(mi) * 60 + int(s)), said.strip()])
        elif not turns:
            header.append(line)
        elif line:
            turns[-1][2] += " " + line  # a wrapped line belongs to the turn above
    head = "\n".join(header)
    title = next((h.split(":", 1)[1].strip() for h in header if h.lower().startswith(("meeting:", "title:"))), "")
    date_line = next((h for h in header if h.lower().startswith("date:")), head)
    seen: dict[str, None] = dict.fromkeys(t[0] for t in turns)
    listed = _attendees(header)

    def person(n: str) -> dict:
        who = listed.get(n.casefold()) or {}
        return {"id": n, "name": n, "email": "", "title": who.get("title", ""), "affiliation": "",
                "organisation": who.get("organisation", ""), "note": who.get("note", "")}

    info = {"title": title, "date": _text_date(date_line), "speakers": [person(n) for n in seen]}
    return _turn_units([(t[0], t[1], "", t[2]) for t in turns if t[2].strip()]), info


# --- notes ----------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+(.*)$")
_SEPARATOR = re.compile(r"^:?-{2,}:?$")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


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
            joined = " ".join(paragraph)
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

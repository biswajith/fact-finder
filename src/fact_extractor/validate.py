"""Parse output lines and validate them (spec sections 6.1 and 7)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import CATEGORIES, FLAGS, CallSpec, OutputLine, TaggedDocument
from .normalize import missing_values

_ID = re.compile(r"^p\d+\.(?:h\d+|t\d+r\d+|\d+)$")


class LineBuffer:
    """Collect streamed text and hand back complete lines."""

    def __init__(self) -> None:
        self._buf = ""
        self.lines: list[str] = []

    def feed(self, text: str) -> list[str]:
        self._buf += text
        *done, self._buf = self._buf.split("\n")
        new = [ln.strip() for ln in done if ln.strip()]
        self.lines.extend(new)
        return new

    def close(self) -> list[str]:
        rest = self._buf.strip()
        self._buf = ""
        if rest:
            self.lines.append(rest)
            return [rest]
        return []


def _looks_like_ids(field: str) -> bool:
    parts = [p.strip().strip("[]") for p in field.split(",") if p.strip()]
    return bool(parts) and all(_ID.match(p) for p in parts)


def parse_line(raw: str) -> OutputLine:
    fields = raw.split("|")
    # "S|END|39": the END line with a stray code in front.
    if len(fields) >= 3 and fields[1].strip().upper() == "END" and fields[2].strip().isdigit():
        fields = fields[1:]
    # "D|Proposal due|2026-08-28|p3.3|": a | inside the fact. When the IDs field is
    # not IDs but a later field is, the fields between are the fact.
    if len(fields) >= 4 and not _looks_like_ids(fields[2]):
        for k in range(3, len(fields)):
            if _looks_like_ids(fields[k]):
                fact = ": ".join(f.strip() for f in fields[1:k] if f.strip())
                fields = [fields[0], fact, fields[k], "|".join(fields[k + 1 :])]
                break
    code = fields[0].strip().upper()
    fact = fields[1].strip() if len(fields) > 1 else ""
    ids = [i.strip().strip("[]") for i in fields[2].split(",")] if len(fields) > 2 else []
    ids = [i for i in ids if i]
    note = fields[3].strip() if len(fields) > 3 else ""
    # "R|...|p9.13,mandatory|": a flag written into the IDs field belongs in the note.
    stray = [i for i in ids if i.lower() in FLAGS]
    if stray:
        ids = [i for i in ids if i.lower() not in FLAGS]
        note = ", ".join(dict.fromkeys([n.strip() for n in note.split(",") if n.strip()] + [s.lower() for s in stray]))
    return OutputLine(raw, code, fact, ids, note, len(fields))


@dataclass
class Checked:
    line: OutputLine
    reasons: list[str] = field(default_factory=list)  # empty = passed
    log: list[str] = field(default_factory=list)  # kept, but worth a note

    @property
    def ok(self) -> bool:
        return not self.reasons


@dataclass
class CallOutput:
    checked: list[Checked]
    end_count: int | None  # None = no END line: output was cut
    none_ids: list[str]  # sweep: IDs answered with NONE
    dropped: list[OutputLine]  # repair: DROP lines
    body_lines: int = 0  # every line before END

    @property
    def failed(self) -> list[Checked]:
        return [c for c in self.checked if not c.ok]


def check_line(line: OutputLine, call: CallSpec, doc: TaggedDocument) -> Checked:
    c = Checked(line)
    # 7.1 Format. A missing empty note at the end ("Q|x|p1.2") is accepted.
    if line.field_count not in (3, 4):
        c.reasons.append(f"expected 4 fields separated by |, got {line.field_count}")
    if line.code not in CATEGORIES:
        c.reasons.append(f"unknown code {line.code!r}")
    elif line.code not in call.codes:
        c.log.append(f"code {line.code} is not allowed in call {call.name}; kept")
    if not line.fact:
        c.reasons.append("empty fact")
    if not line.ids:
        c.reasons.append("no IDs")
    # 7.2 IDs exist.
    unknown = [i for i in line.ids if i not in doc.anchors]
    if unknown:
        c.reasons.append(f"IDs not in the RFP: {', '.join(unknown)}")
    # 7.3 Numbers match the cited text (and the section headings of the cited IDs).
    known = [doc.anchors[i] for i in line.ids if i in doc.anchors]
    if known and line.fact:
        sources = [a.text for a in known] + [a.section for a in known]
        missing = missing_values(line.fact, sources)
        if missing:
            shown = ", ".join(sorted(m.removeprefix("date:").removeprefix("time:") for m in missing))
            c.reasons.append(f"numbers not in the cited text: {shown}")
    if call.page_range and known and line.code == "R":
        start, end = call.page_range
        if not start <= known[0].page <= end:
            c.log.append(f"main ID {known[0].id} is outside pages {start}-{end}")
    if len(line.fact.split()) >= 30:
        c.log.append("fact has 30 words or more")
    return c


def check_output(lines: list[str], call: CallSpec, doc: TaggedDocument) -> CallOutput:
    checked: list[Checked] = []
    none_ids: list[str] = []
    dropped: list[OutputLine] = []
    end_count: int | None = None
    body = 0
    for raw in lines:
        if raw.startswith("```"):
            continue
        line = parse_line(raw)
        if line.code == "END":
            try:
                end_count = int(line.fact)
            except ValueError:
                end_count = -1
            break
        body += 1
        if line.code == "NONE" and call.kind == "sweep":
            none_ids.extend(i for i in line.ids if i in doc.anchors)
            continue
        if line.code == "DROP" and call.kind == "repair":
            dropped.append(line)
            continue
        checked.append(check_line(line, call, doc))
    return CallOutput(checked, end_count, none_ids, dropped, body)

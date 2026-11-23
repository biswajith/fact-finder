"""CLASSIFY: what kind of document is this, which issue is it, and when was it issued?

Two ways to answer, and the user confirms either one before anything is read:
- `by_rules` looks at the file's form and the words on its first page. It needs no model.
- `by_model` asks the model one closed question and checks every part of the answer in code
  against the text it was shown; a part that fails keeps the rules' value.

Both return `{"playbook", "issue_number", "issue_date", "by", "checked"}`.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence

from . import cutters, normalize, playbooks
from .llm import CallFailed, LLMClient, RateLimited, Request

FIRST_WORDS = 3000  # how much of the document the model reads
_ADDENDUM = re.compile(r"\b(?:addendum|amendment)\b", re.I)
_QA = re.compile(r"questions\s+and\s+answers|\bq\s*&\s*a\b", re.I)
_NUMBER = re.compile(r"\b(?:addendum|amendment)\s*(?:no\.?|number|#)?\s*(\d+)\b", re.I)
_EXPORTED = re.compile(r"\bexport(?:ed)?\b(.*)$", re.I | re.M)
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def first_date(text: str) -> str | None:
    """The first date in `text` that `normalize.values` reads, as YYYY-MM-DD."""
    best: tuple[int, str] | None = None
    for pat in normalize._DATE_PATTERNS:
        for m in pat.finditer(text):
            token = next((v for v in normalize.values(m.group(0)) if v.startswith("date:")), None)
            if token and (best is None or m.start() < best[0]):
                best = (m.start(), token.removeprefix("date:"))
    return best[1] if best else None


def first_page_text(data: bytes) -> str:
    """The text of the first page of a PDF; empty when it cannot be read."""
    try:
        import pymupdf

        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return doc[0].get_text() if doc.page_count else ""
    except Exception:  # an unreadable PDF is still a document the user can classify by hand
        return ""


def first_text(units: Sequence, words: int = FIRST_WORDS) -> str:
    """The first `words` words of a document's units (anything with a `.text`), one unit per line."""
    out: list[str] = []
    left = words
    for u in units:
        parts = u.text.split()
        if not parts:
            continue
        out.append(" ".join(parts[:left]))
        left -= len(parts)
        if left <= 0:
            break
    return "\n".join(out)


def by_rules(file_name: str, data: bytes) -> dict:
    """The proposal that needs no model: from the form of the file and its first page."""
    form = cutters.form_of(file_name, data)
    number: int | None = None
    date: str | None = None
    if form == "pdf":
        text = first_page_text(data)
        if _ADDENDUM.search(text):
            name = "qa-addendum" if _QA.search(text) else "change-addendum"
        else:
            name = "rfp"
        m = _NUMBER.search(text)
        number = int(m.group(1)) if m else None
        date = first_date(text)
    elif form == "transcript":
        name = "call-transcript"
        try:
            date = cutters.cut_transcript(data, file_name)[1]["date"] or None
        except ValueError:
            date = None
    elif form == "notes":
        name = "deal-notes"
        m = _EXPORTED.search(data.decode("utf-8-sig", errors="replace"))
        date = first_date(m.group(1)) if m else None
    else:
        name = "fill-in-template"
    return {"playbook": name, "issue_number": number, "issue_date": date, "by": "rules", "checked": True}


def system() -> str:
    """The CLASSIFY system prompt: every playbook with its description."""
    kinds = "\n".join(f"- {pb.name}: {pb.description}" for pb in playbooks.all())
    return f"""You sort the documents of one bid. You are shown the start of one document and say what kind it is.

KINDS OF DOCUMENT
{kinds}

Answer with one line and nothing else, in this format:
PLAYBOOK|issue number or -|date as YYYY-MM-DD or -
PLAYBOOK is one kind from the list, written exactly as above. The issue number is the number the document gives itself within a series (for example the number of an addendum); write - when it states none. The date is the date the document says it was issued or written; write - when it states none. Use only what the text says. Do not guess."""


async def _ask(client: LLMClient, req: Request) -> str | None:
    """One call, retried once; None when both fail."""
    for _ in range(2):
        try:
            return (await asyncio.wait_for(client.complete(req, lambda _t: None), 60)).text
        except (CallFailed, RateLimited, asyncio.TimeoutError):
            continue
    return None


async def by_model(file_name: str, first_text: str, client: LLMClient, *, rules: dict | None = None) -> dict | None:
    """The CLASSIFY call. `first_text` is the start of the document. Code keeps the playbook only
    if it exists, the number only if it is on the pages read, the date only if `normalize.values`
    finds that date in the text read. A part that fails keeps the value in `rules` (what
    `by_rules` gave) and sets `checked` false. None when the call fails."""
    rules = rules or {}
    task = f"TASK CLASSIFY\nFile name: {file_name}\nSay what kind of document this is.\nFormat: PLAYBOOK|issue number or -|date as YYYY-MM-DD or -"
    text = await _ask(client, Request(system(), first_text, task, "low", 300))
    if text is None:
        return None
    line = next((ln for ln in text.splitlines() if ln.count("|") >= 2), "")
    parts = [p.strip() for p in line.split("|")] + ["", "", ""]
    name, number, date = parts[0].lower(), parts[1], parts[2]
    checked = bool(line)
    out = {
        "playbook": rules.get("playbook"), "issue_number": rules.get("issue_number"),
        "issue_date": rules.get("issue_date"), "by": "model",
    }
    if name in playbooks.names():
        out["playbook"] = name
    else:
        checked = False
    if number != "-":
        if number.isdigit() and re.search(rf"(?<!\d){int(number)}(?!\d)", first_text):
            out["issue_number"] = int(number)
        else:
            checked = False
    if date != "-":
        if _ISO.match(date) and f"date:{date}" in normalize.values(first_text):
            out["issue_date"] = date
        else:
            checked = False
    out["checked"] = checked
    return out

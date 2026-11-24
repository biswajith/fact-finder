"""CLASSIFY: what kind of document is this, which issue is it, and when was it issued?

Two ways to answer, and the user confirms either one before anything is read:
- `by_rules` looks only at the words at the start of the document, whatever its file format. It needs
  no model, and it only tells an addendum by its own words; anything else it calls an RFP.
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


RULES_WORDS = 400  # the start of a document that is not a PDF the rules read (about one page)


def by_rules(file_name: str, data: bytes) -> dict:
    """The proposal that needs no model, from the start of the document (a PDF's first page, else its
    first words) in any file format: an addendum, and a Q&A addendum, by their own words; anything
    else an RFP. The first date there is the issue date. The model's CLASSIFY or the user corrects it."""
    text = cutters.plain_text(data, file_name, RULES_WORDS, pages=1)
    if _ADDENDUM.search(text):
        name = "qa-addendum" if _QA.search(text) else "change-addendum"
    else:
        name = "rfp"
    m = _NUMBER.search(text)
    return {"playbook": name, "issue_number": int(m.group(1)) if m else None, "issue_date": first_date(text),
            "by": "rules", "checked": True}


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
    finds that date in the text read, or the text writes it as YYYY-MM-DD (also inside a time stamp). A part that fails keeps the value in `rules` (what
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
        if _ISO.match(date) and (f"date:{date}" in normalize.values(first_text) or re.search(rf"(?<!\d){date}(?!\d)", first_text)):
            out["issue_date"] = date
        else:
            checked = False
    out["checked"] = checked
    return out

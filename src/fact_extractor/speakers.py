"""Who speaks each line of a call, and which side is each person on: the buyer's, ours, or another
party's (an advisor, a partner)?

A call comes in any layout (a PDF, a Word file, a chat export, JSON from a call system), so code does
not look for speaker labels. `find_voices` asks the model, in batches of numbered lines, who speaks
each line, and keeps a name only if the document writes it. `by_model` then asks which side each
person is on; the rules in `bid.propose_speakers` add the team list and the buyer's facts. The user
confirms every side before the call is read.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Sequence

from . import classify
from .llm import LLMClient, Request

SIDES = ("buyer", "ours", "other", "unknown")
OPENING_WORDS = 1500  # how much of the call the model reads
WHO_BATCH = 80  # lines per WHO call
WHO_CONTEXT = 6  # lines before a batch shown for who was speaking
WHO_OPENING = 300  # words of the document's start shown with every batch

WHO_SYSTEM = """You are given numbered lines of a document that records people speaking: a call, a meeting or an interview, saved in whatever layout the tool that made it uses. For each numbered line, say who speaks the words on it.

- Write the person's name as the document writes it, in the fullest form the document gives, and the same form every time.
- A line that carries on what someone was saying is theirs, also after a page break.
- A line that no one speaks (a title, a date, an attendee list, a time stamp alone, a page header or footer) gets -.
- When the document does not show who speaks a line, write -. Do not guess from what is said.

Answer with one line per numbered line and nothing else, in this format:
ID|name or -
Then a last line: END|n, where n is the number of lines above."""
_REASON_MAX = 120

SYSTEM = """You are given the people on a call about a bid. For each one, say which side they are on:
- BUYER: works for the organisation that issued the RFP and will buy.
- OURS: works for the bidder whose team is preparing this bid.
- OTHER: works for any other organisation: an advisor to either side, a partner, a subcontractor, a competitor.
- UNKNOWN: nothing shows it.

Use the attendee list's organisations and notes first, then the team list, then what people say in the opening of the call. People from the same organisation are on the same side. An adviser hired by the buyer is OTHER, not BUYER, and the reason says whom they act for. Do not guess from a name alone.

Answer with one line per person and nothing else, in this format:
ID|SIDE|organisation|acts for (BUYER, OURS or -)|reason in under 15 words
Then a last line: END|n, where n is the number of lines above. Write the organisation as the attendee list or the call gives it, or - when none is shown."""


def opening_text(units: Sequence, words: int = OPENING_WORDS) -> str:
    """The start of a call as `Speaker name: sentence` lines (a line no one speaks as it is), up to `words` words."""
    out: list[str] = []
    left = words
    for u in units:
        parts = u.text.split()
        if not parts:
            continue
        words = " ".join(parts[:left])
        out.append(f"{u.speaker}: {words}" if u.speaker else words)
        left -= len(parts)
        if left <= 0:
            break
    return "\n".join(out)


def _cell(value: str) -> str:
    return " ".join(str(value or "").replace("|", "/").split()) or "-"


def _message(info: dict, opening: str, context: dict) -> tuple[str, str]:
    """The user message and the attendee list text it holds."""
    attendees = "\n".join(
        " | ".join(_cell(s.get(k, "")) for k in ("id", "name", "organisation", "title", "note", "email"))
        for s in info.get("speakers", [])
    )
    text = (
        f"Bid: {context.get('bid_name') or '-'}\n"
        f"Our team: {', '.join(context.get('team') or []) or '-'}\n"
        f"Phrases from the buyer's own documents:\n" + "\n".join(f"- {t}" for t in context.get("buyer_names") or []) + "\n"
        f"Other documents of the bid: {', '.join(context.get('other_documents') or []) or '-'}\n\n"
        f"ATTENDEES (ID | name | organisation | title | note | email)\n{attendees}\n\n"
        f"OPENING OF THE CALL\n{opening}"
    )
    return text, attendees


async def by_model(info: dict, opening: str, context: dict, client: LLMClient) -> dict[str, dict] | None:
    """The speaker call. `info` is `Bid.call_info`, `opening` the first words of the call. Code keeps a
    line only if its ID is a speaker given and its side is one of the four; an organisation only if it
    appears in the attendee list or the opening (else the one already known stands). Returns
    `{speaker id: {"side", "organisation", "acts_for", "reason"}}`, or None when the call fails."""
    speakers = {str(s.get("id")): s for s in info.get("speakers", []) if s.get("id")}
    if not speakers:
        return {}
    document, attendees = _message(info, opening, context)
    task = "TASK SPEAKERS\nSay which side each person is on.\nFormat: ID|SIDE|organisation|acts for (BUYER, OURS or -)|reason"
    request = Request(SYSTEM, document, task, effort="low", max_output_tokens=min(2000, 150 + 90 * len(speakers)))
    text = await classify._ask(client, request)
    if text is None:
        return None
    haystack = f"{attendees}\n{opening}".casefold()
    out: dict[str, dict] = {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|", 4)]
        if len(parts) < 5 or parts[0] not in speakers:
            continue
        side = parts[1].lower()
        if side not in SIDES:
            continue
        given = "" if parts[2] in ("", "-") else parts[2]
        organisation = given if given and given.casefold() in haystack else speakers[parts[0]].get("organisation") or ""
        acts_for = parts[3].lower() if parts[3].lower() in ("buyer", "ours") else ""
        out[parts[0]] = {"side": side, "organisation": organisation, "acts_for": acts_for, "reason": parts[4][:_REASON_MAX]}
    return out


def _who_message(lines: list[tuple[str, str]], start: int, end: int, opening: str) -> str:
    before = "\n".join(f"[{i}] {t}" for i, t in lines[max(0, start - WHO_CONTEXT):start])
    these = "\n".join(f"[{i}] {t}" for i, t in lines[start:end])
    return (f"THE START OF THE DOCUMENT\n{opening}\n\n"
            + (f"THE LINES JUST BEFORE (do not answer for these)\n{before}\n\n" if before else "")
            + f"LINES\n{these}")


async def find_voices(doc, client: LLMClient) -> dict[str, str] | None:
    """Who speaks each unit of the tagged document `doc`: `{anchor id: name}` for the units someone
    speaks, in document order. Code keeps an answer only for an ID it asked about and a name the
    document writes (any case). None when a call fails twice."""
    lines = [(a.id, " ".join(a.text.split())) for a in doc.anchors.values()]
    if not lines:
        return {}
    opening = classify.first_text(list(doc.anchors.values()), WHO_OPENING)
    haystack = " ".join(t for _i, t in lines).casefold()

    async def batch(start: int) -> dict[str, str] | None:
        end = min(start + WHO_BATCH, len(lines))
        ids = {i for i, _t in lines[start:end]}
        task = (f"TASK WHO\nSay who speaks each line from {lines[start][0]} to {lines[end - 1][0]}.\n"
                "Format: ID|name or -")
        req = Request(WHO_SYSTEM, _who_message(lines, start, end, opening), task, effort="low",
                      max_output_tokens=200 + 25 * (end - start))
        text = await classify._ask(client, req)
        if text is None:
            return None
        got: dict[str, str] = {}
        for line in text.splitlines():
            parts = [p.strip() for p in line.strip().strip("[]").split("|", 1)]
            if len(parts) < 2 or parts[0].strip("[]") not in ids:
                continue
            name = " ".join(parts[1].split())
            if name and name != "-" and name.casefold() in haystack:
                got[parts[0].strip("[]")] = name
        return got

    answers = await asyncio.gather(*(batch(k) for k in range(0, len(lines), WHO_BATCH)))
    if any(a is None for a in answers):
        return None
    found: dict[str, str] = {}
    for a in answers:
        found.update(a or {})
    return {i: found[i] for i, _t in lines if i in found}


async def read_voices(bid, no: int, client: LLMClient) -> dict | None:
    """Find who speaks each line of document `no` and keep it on the document (`Bid.set_voices`), which
    proposes the speakers. The document entry afterwards, or None when the model did not answer."""
    d = bid.document(no)
    voices = await find_voices(await asyncio.to_thread(bid.read, d), client)
    if voices is None:
        return None
    return bid.set_voices(no, voices)


async def suggest(bid, no: int, client: LLMClient) -> dict | None:
    """Ask the model about the speakers of document `no` and keep its answer on the document
    (`Bid.set_speaker_model`). The document entry afterwards, or None when the model did not answer."""
    d = bid.document(no)
    info = bid.call_info(d)
    if not info["speakers"]:
        return None
    tagged = await asyncio.to_thread(bid.read, d)
    voices = d.get("voices") or {}
    units = [dataclasses.replace(a, speaker=voices.get(a.id, "")) for a in tagged.anchors.values()]
    answer = await by_model(info, opening_text(units), bid.speakers_context(no), client)
    if answer is None:
        return None
    return bid.set_speaker_model(no, answer)

"""Which side is each person on a call? The buyer's, ours, or another party's (an advisor, a partner).

The rules in `bid.propose_speakers` know the team list, the buyer's facts and a call system's
affiliation. A plain-text transcript has none of that, but its header says who each person works for.
`by_model` asks the model one small closed question about that and checks every line of the answer
in code; the user still confirms every side before the call is read.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import classify
from .llm import LLMClient, Request

SIDES = ("buyer", "ours", "other", "unknown")
OPENING_WORDS = 1500  # how much of the call the model reads
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
    """The start of a call as `Speaker name: sentence` lines, up to `words` words."""
    out: list[str] = []
    left = words
    for u in units:
        parts = u.text.split()
        if not parts:
            continue
        out.append(f"{u.speaker or 'Unknown'}: {' '.join(parts[:left])}")
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
    """The speaker call. `info` is the cutter's info, `opening` the first words of the call. Code keeps a
    line only if its ID is a speaker given and its side is one of the four; an organisation only if it
    appears in the attendee list or the opening (else the cutter's organisation stands). Returns
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


async def suggest(bid, no: int, client: LLMClient) -> dict | None:
    """Ask the model about the speakers of document `no` and keep its answer on the document
    (`Bid.set_speaker_model`). The document entry afterwards, or None when the model did not answer."""
    from . import cutters

    d = bid.document(no)
    units, info = cutters.cut_transcript(bid.data(d), d["file_name"])
    answer = await by_model(info, opening_text(units), bid.speakers_context(no), client)
    if answer is None:
        return None
    return bid.set_speaker_model(no, answer)

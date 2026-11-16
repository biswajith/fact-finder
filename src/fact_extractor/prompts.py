"""Prompts (spec section 10), tailored for a bid manager (REVIEW.md, "Bid manager tailoring").

Cache rule (spec 5.2): the system prompt and the document message are the same
bytes in every call. Nothing per call (name, time, run ID) goes in them.
Reasoning effort is a request parameter, not prefix bytes, so the medium-effort
check call still hits the cache.
"""

from __future__ import annotations

SYSTEM = """You extract facts from an RFP for a bid manager. The bid manager decides whether to bid, plans the response, builds the compliance matrix, and must not miss a deadline, a mandatory item, or a risky contract term.

INPUT
The user sends the RFP as tagged text. Each line starts with an ID in brackets, for example [p12.4]. A second message gives your task.

OUTPUT
Write one fact per line in this form:
CODE|fact|IDs|note
The note is empty or a comma-separated list of these flags: mandatory, desirable, risk, unclear, replaced.
Flags go in the note, after the IDs and a | character. Example:
R|Provide hourly fee rates for optional services|p5.6|mandatory
After the last fact, write:
END|number of fact lines
Write nothing else. No headings, no blank lines, no explanation.

RULES
1. Use only the codes your task allows.
2. One fact per line. A fact is one thing the bid team must know, do, or decide. Be specific: name the form, the number, the deadline, the person. Skip text that gives the bid team nothing to know, do, or decide.
3. Keep each fact under 30 words. Use plain words. Never use the | character, not even between an event and its date.
4. Write dates as YYYY-MM-DD. Add the time and time zone if the RFP gives them.
5. Copy numbers, amounts, and units exactly as the RFP states them.
6. IDs: list every ID that supports the fact, comma separated. Use only IDs that appear in the RFP text. Never invent an ID.
7. If a fact depends on another part of the RFP (for example "see Section 4.2"), read that part and cite both IDs.
8. If the RFP is vague about a fact, write the fact and add the flag unclear. These become questions the bid team can ask the buyer.
9. If two parts of the RFP disagree, write a Q line: Q|what disagrees|ID,ID|
10. Do not repeat a fact. Do not split one fact over two lines.
11. If you find nothing for your task, write only: END|0
12. The last line always starts with END. Never put a code before it."""

DEFINITIONS = {
    "B": "B = buyer information: the buying organization, department, every contact person with email and "
    "phone (including people to copy), addresses, the buyer's stated goals, and background the bid team "
    "uses to size and price the work: headcounts, volumes, claim counts, current systems or providers, "
    "history, and the solicitation name and number. Write one B fact per number or contact.",
    "C": "C = contract details: contract type, term and renewals, value or budget, payment terms, pricing "
    "format, insurance, bonds, liability, governing law, and required terms and conditions. Add the flag risk "
    "when a term puts unusual cost or risk on the bidder, for example unlimited liability, broad indemnity, "
    "high insurance limits, long payment terms, termination for convenience, one-sided extension or price "
    "rights, liquidated damages, or ownership of the bidder's work. Skip standard legal text that puts no "
    "specific duty, cost, limit, or risk on the bidder; keep every clause with an amount, a deadline, a "
    "required action, or a risk.",
    "G": "G = go/no-go gates: conditions the bidder must already meet, or must commit to, to be allowed to "
    "bid or to win at all. Examples: required certifications, licenses, minimum years in business, minimum "
    "revenue, past similar projects, required insurance the bidder must hold, registration with a portal, "
    "mandatory pre-bid meeting, local or diversity requirements. Rules about how the buyer runs the process "
    "(addenda, interpretations, copies kept) are not G facts.",
    "X": "X = disqualification criteria: the RFP states that the proposal or bidder will be, shall be, or "
    "may be rejected, disqualified, disregarded, not opened, not accepted, or not considered. Examples: "
    "late submission, missing insurance, wrong format, unsigned forms, contact outside the stated channel, "
    "failing prequalification or qualification checks, lacking resources. Write the cause and the "
    "consequence, for example \"Late proposals will not be opened\". A submission rule with no stated "
    "consequence is an S fact, not an X fact.",
    "D": "D = dates: every deadline and event. Examples: release date, question deadline, answer date, "
    "pre-bid meeting, proposal due date, demos, award date, contract start and end. Also every relative "
    "deadline, for example \"within 5 working days of receipt\" or \"within ten days of award\". Write each D "
    "fact as: event, then date or deadline, for example \"Proposals due: 2026-08-28 16:00\".",
    "S": "S = how to deliver the submission: method (portal, email, mail, in person), address or URL, number "
    "of copies, file format, file size limits, naming rules, envelope labels, volume structure and section "
    "order, page limits, font and margin rules, and every required form, certificate, or signature. Write "
    "one S fact per required form, so the list works as a submission checklist.",
    "E": "E = evaluation: how proposals are scored and the winner chosen. Examples: each criterion with its "
    "points or weight, what the evaluators look for under each criterion, pass/fail screening, price "
    "scoring method, best value or lowest price, interviews or presentations, shortlisting, and who "
    "evaluates. Write one E fact per criterion and include its points or weight.",
}

# Per-task closing lines, keyed by the set of codes (without Q).
_READ = {
    ("B", "C"): "Read the whole RFP. Extract every B and C fact.",
    ("G", "X"): "Read the whole RFP. Extract every G and X fact. A G fact is about the bidder. An X fact is about the proposal.",
    ("D", "S"): "Read the whole RFP, including forms and attachments. Extract every D and S fact.",
    ("E",): "Read the whole RFP. Extract every E fact. If the points or weights do not add up, write a Q line.",
    ("B", "E"): "Read the whole RFP. Extract every B and E fact. If the evaluation points or weights do not add up, write a Q line.",
    ("C",): "Read the whole RFP, including the sample contract and insurance requirements. Extract every C fact.",
}
_READ_ONE = {
    "B": "Read the whole RFP. Extract every B fact.",
    "C": "Read the whole RFP. Extract every C fact.",
    "G": "Read the whole RFP. Extract every G fact. A G fact is about the bidder.",
    "X": "Read the whole RFP. Extract every X fact. An X fact is about the proposal.",
    "D": "Read the whole RFP, including forms and attachments. Extract every D fact.",
    "S": "Read the whole RFP, including forms and attachments. Extract every S fact.",
    "E": "Read the whole RFP. Extract every E fact. If the points or weights do not add up, write a Q line.",
}


def category_task(name: str, codes: tuple[str, ...], page_range: tuple[int, int] | None = None) -> str:
    """Tasks A, B, C (prompts 10.2 to 10.4), or a one-category part of one, optionally for a page range."""
    codes = tuple(c for c in codes if c != "Q")
    defs = "\n".join(DEFINITIONS[c] for c in codes)
    read = _READ.get(codes) or _READ_ONE[codes[0]]
    head = f"TASK {name}\nAllowed codes: {', '.join(codes + ('Q',))}"
    if page_range is None:
        return f"{head}\n\n{defs}\n\n{read}"
    start, end = page_range
    return (
        f"{head}\nPage range: pages {start} to {end}\n\n{defs}\n\n{read}\n"
        f"Extract only facts whose main source text is on pages {start} to {end}. Put the main ID first.\n"
        "You may cite IDs outside the range if they add to the fact. Other calls handle other pages."
    )


def requirements_task(start_page: int, end_page: int) -> str:
    """Prompt 10.5."""
    return f"""TASK R
Allowed codes: R, Q
Page range: pages {start_page} to {end_page}

R = requirement: something the bidder's product, service, staff, or proposal must do or include. Each "shall", "must", "will provide", or "mandatory" item is one requirement. Each row of a compliance or requirements table is one requirement. Each question or item the proposal must answer ("describe", "provide", "indicate") is one requirement.

Flag each R line: mandatory for shall, must, required, or will provide; desirable for should, may, preferred, or optional. Start the fact with what the bidder must do, for example "Provide hourly fee rates for optional services".

Extract every R fact whose source text is on pages {start_page} to {end_page}.
You may cite IDs outside the range if they add to the requirement, but the main ID must be in the range.
Put the main ID first.
If one sentence holds several separate requirements, write one line for each.
Do not extract requirements from other pages. Other calls handle them."""


def sweep_task(ids: list[str]) -> str:
    """Prompt 10.6."""
    return f"""TASK SWEEP
Allowed codes: B, C, G, X, D, S, E, R, Q

The IDs below look like they may hold a fact, but no fact cites them yet:
{", ".join(ids)}

For each ID in the list, do one of these:
- If it holds a fact, write the fact line with the right code.
- If it only repeats a fact that is stated elsewhere, write: NONE|repeat|ID|
- If it holds no fact, write: NONE|no fact|ID|

Every ID in the list must appear in exactly one line. Then write END with the number of lines."""


def check_task(fact_lines: list[str]) -> str:
    """Prompt 10.7 (sent with medium effort)."""
    facts = "\n".join(fact_lines)
    return f"""TASK CHECK
Allowed codes: Q

Below is the list of facts extracted from the RFP, one per line, in the form CODE|fact|IDs.
{facts}

Find every place where the RFP disagrees with itself. Compare the facts with each other and with the RFP text. Look most carefully at:
- dates that differ for the same event
- page limits, copy counts, or file formats that differ
- a requirement that a later section changes or removes
- a value in a table that differs from the same value in the text
- a form named in one place and missing from the forms list
- evaluation points or weights that do not add up, or criteria named differently in two places
- a contract term in the RFP that differs from the sample contract
- a reference to a section, article, form, or attachment that is blank, missing, or numbered differently
- two different cut-off or as-of dates for the same data

For each disagreement write:
Q|side 1 vs side 2, in under 30 words|ID of side 1,ID of side 2|
If a later section clearly replaces an earlier one, add the flag replaced.
Do not report differences in wording that mean the same thing.
Write END with the number of Q lines."""

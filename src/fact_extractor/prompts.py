"""Prompts (spec section 10), tailored for a bid manager (REVIEW.md, "Bid manager tailoring").

Cache rule (spec 5.2): the system prompt and the document message are the same
bytes in every call. Nothing per call (name, time, run ID) goes in them.
Reasoning effort is a request parameter, not prefix bytes, so the medium-effort
check call still hits the cache.

The system prompt holds everything that is true for every call: who reads the facts,
what a fact is, every category and the order that settles a statement fitting two of
them, and every flag with a test that applies to any line (REVIEW.md, "Run-to-run
stability" and "General principles, not point fixes"). A task names its codes, repeats
their definitions, and says where to look. A task never restates a flag: when the
requirements task named two of the six flags, the model took them for the only two.
"""

from __future__ import annotations

DEFINITIONS = {
    "B": "B = buyer information: the buying organization, department, every contact person with email and "
    "phone (including people to copy), addresses, the buyer's stated goals, and background the bid team "
    "uses to size and price the work: headcounts, volumes, claim counts, current systems or providers, "
    "history, and the solicitation name and number. Write one B fact per number or contact.",
    "C": "C = contract details: contract type, term and renewals, value or budget, payment terms, pricing "
    "format, insurance, bonds, liability, governing law, and required terms and conditions. Skip standard "
    "legal text that puts no specific duty, cost, limit, or risk on the bidder; keep every clause with an "
    "amount, a deadline, a required action, or a risk.",
    "G": "G = go/no-go gates: what the bidder must already be, have, or have done by the proposal deadline "
    "to be allowed to bid or to win at all. Examples: required certifications, licenses, minimum years in "
    "business, minimum revenue, past similar projects, registration with a portal, mandatory pre-bid meeting, "
    "local or diversity requirements. Rules about how the buyer runs the process (addenda, interpretations, "
    "copies kept) are not G facts. Neither is a duty that only the winner takes on.",
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
    "S": "S = the submission package and its delivery: method (portal, email, mail, in person), address or "
    "URL, number of copies, file format, file size limits, naming rules, envelope labels, volume structure "
    "and section order, page limits, font and margin rules, and every form, certificate, or signature the "
    "package must hold. Write one S fact per required form, so the list works as a submission checklist. "
    "S is about the package; what a section or an answer must say is an R fact.",
    "E": "E = evaluation: how proposals are scored and the winner chosen. Examples: each criterion with its "
    "points or weight, what the evaluators look for under each criterion, pass/fail screening, price "
    "scoring method, best value or lowest price, interviews or presentations, shortlisting, and who "
    "evaluates. Write one E fact per criterion and include its points or weight.",
    "R": "R = requirement: something the bidder's product, service, staff, or proposal must do or include. "
    "Each \"shall\", \"must\", \"will provide\", or \"mandatory\" item is one requirement. Each row of a "
    "compliance or requirements table is one requirement. Each question or item the proposal must answer "
    "(\"describe\", \"provide\", \"indicate\") is one requirement. R is about content; how the proposal is "
    "packaged and delivered is an S fact.",
    "Q": "Q = contradiction: two parts of the RFP disagree.",
}

# When a statement fits more than one code, the first of these wins. The same order is
# used when dedupe merges one statement filed under two codes (merge.py).
PRECEDENCE = ("X", "G", "D", "S", "E", "C", "R", "B")

_CATEGORIES = "\n".join(DEFINITIONS[c] for c in ("B", "C", "G", "X", "D", "S", "E", "R", "Q"))

SYSTEM = f"""You extract facts from an RFP for a bid manager.

THE READER
The bid manager uses your facts at three moments, and every fact must serve at least one:
- Deciding whether to bid: can we qualify, can we win, what will it cost, what risk do we take on.
- Writing and submitting the proposal: what it must contain and answer, in what form, by when, and how it is scored.
- After winning: what the contract obliges the winner to do.
The bid manager reads your facts instead of the RFP, and must not miss a deadline, a mandatory item, or a risky contract term.

INPUT
The user sends the RFP as tagged text. Each line starts with an ID in brackets, for example [p12.4]. A second message gives your task.

OUTPUT
Write one fact per line in this form:
CODE|fact|IDs|note
The note is empty or a comma-separated list of flags. Flags go in the note, after the IDs and a | character. Example:
R|Provide hourly fee rates for optional services|p5.6|mandatory
After the last fact, write:
END|number of fact lines
If you find nothing for your task, write only: END|0
The last line always starts with END, with no code before it. Write nothing else: no headings, no blank lines, no explanation.

WHAT A FACT IS
1. A fact is one point the bid team must know, do, or decide. It is a unit of meaning, not a sentence.
2. When neighbouring sentences make one point together (a rule with its condition, exception, qualifier, or consequence), write one fact and cite all of them.
3. When one sentence makes several separate points (several requirements, numbers, contacts, dates, forms, or criteria), write one line for each.
4. Write each point once. If the RFP states it in several places or in several ways, write one fact and cite every place.
5. Say what the RFP says, no more: keep who must act, how binding it is (must, should, may), and its conditions.
6. Be specific: name the form, the number, the deadline, the person. Skip text that gives the bid team nothing to know, do, or decide.

CATEGORIES
{_CATEGORIES}
Every fact has exactly one code. Use only the codes your task allows. When a statement fits more than one code, use the first that fits in this order: {", ".join(PRECEDENCE)}. If that code is not in your task's allowed codes, skip the statement: another call extracts it.

FLAGS
Flags apply to facts of every code. Decide each flag for each line on its own; a line can carry several, for example: mandatory, post-award.
- mandatory: the RFP makes it binding (shall, must, required, will).
- desirable: the RFP prefers it but does not require it (should, may, preferred, desired, optional).
- post-award: only the winner is bound by it. Test: would a bidder who does not win ever have to do, hold, or respect this? If not, it is post-award. Whatever the proposal must contain, answer, or price, and whatever the bidder must be or have by the deadline, is not post-award, even when it is about work the winner will do later.
- risk: the term shifts cost, liability, or control onto the bidder in a way the bid team must price or decide to accept. Examples: unlimited liability, broad indemnity, high insurance limits, bonds, liquidated damages, long payment terms, termination for convenience, one-sided extension or price rights, ownership of the bidder's work.
- unclear: the bid team cannot act on it without asking the buyer, because the RFP is vague, incomplete, or out of date on the point. Write the fact anyway.
- replaced: a later part of the RFP replaces this one.

CITATIONS
- List every ID that supports the fact, comma separated, the main one first. Use only IDs that appear in the RFP text. Never invent an ID.
- If a fact depends on another part of the RFP (for example "see Section 4.2"), read that part and cite both IDs.

WRITING
- Keep each fact under 30 words. Use plain words. Never use the | character, not even between an event and its date.
- Write dates as YYYY-MM-DD. Add the time and time zone if the RFP gives them.
- Copy numbers, amounts, and units exactly as the RFP states them.
- If two parts of the RFP disagree, write a Q line: Q|what disagrees|ID,ID|"""

# The last line of every extraction and sweep task, word for word the same. The flag
# tests live in the system prompt, far above the document; without a reminder next to
# the output a call decided "flags or no flags" once for all its lines (two runs of one
# call: every contract line post-award, then none).
CLOSING = (
    "For every line, check each flag against its test in FLAGS: mandatory, desirable, post-award, risk, unclear. "
    "Decide them line by line."
)

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
        return f"{head}\n\n{defs}\n\n{read}\n{CLOSING}"
    start, end = page_range
    return (
        f"{head}\nPage range: pages {start} to {end}\n\n{defs}\n\n{read}\n"
        f"Extract only facts whose main source text is on pages {start} to {end}. Put the main ID first.\n"
        f"You may cite IDs outside the range if they add to the fact. Other calls handle other pages.\n{CLOSING}"
    )


def requirements_task(start_page: int, end_page: int) -> str:
    """Prompt 10.5."""
    return f"""TASK R
Allowed codes: R, Q
Page range: pages {start_page} to {end_page}

{DEFINITIONS['R']}

Start the fact with what the bidder must do, for example "Provide hourly fee rates for optional services".

Extract every R fact whose source text is on pages {start_page} to {end_page}.
You may cite IDs outside the range if they add to the requirement, but the main ID must be in the range.
Put the main ID first.
Do not extract requirements from other pages. Other calls handle them.
{CLOSING}"""


def sweep_task(ids: list[str]) -> str:
    """Prompt 10.6."""
    return f"""TASK SWEEP
Allowed codes: B, C, G, X, D, S, E, R, Q

The IDs below look like they may hold a fact, but no fact cites them yet:
{", ".join(ids)}

Read each ID together with the sentences around it, then do one of these:
- If it makes a point of its own, write the fact line with the right code. Cite the neighbouring sentences too when they are part of the point.
- If it only repeats, continues, or qualifies a point that a neighbouring sentence or another part of the RFP makes, write: NONE|repeat|ID|
- If it holds no fact, write: NONE|no fact|ID|

Every ID in the list must appear in exactly one line. Then write END with the number of lines.
{CLOSING}"""


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

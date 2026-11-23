"""Category definitions, their precedence, and the extraction system prompt.

DEFINITIONS, PRECEDENCE and FLAG_TESTS are shared by the unit-label pipeline (units.py)
and the golden-dataset builder (golden.py), so goldset reads the categories and the flags
the same way as the extractor. SYSTEM, the system prompt of the earlier pipeline (removed
2026-11-21), is read only by golden.py, for its reader, fact and writing rules; its own
FLAGS section is no longer used. Its bytes are pinned in tests/test_golden.py.
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

# When a statement fits more than one code, the first of these wins. golden.py uses the
# same order when one unit is accepted under two codes.
PRECEDENCE = ("X", "G", "D", "S", "E", "C", "R", "B")

# The tests for the flags the model decides. units.SYSTEM and the golden-dataset prompts
# (golden.py) are both built from these, so the reference reads the flags as the extractor does.
FLAG_TESTS = {
    "post-award": "post-award: only the winner is bound by it. Test: would a bidder who does not win ever have "
    "to do, hold, or respect this? If not, it is post-award. Whatever the proposal must contain, answer, or "
    "price, and whatever the bidder must be or have by the deadline, is not post-award, even when it is about "
    "work the winner will do later.",
    "risk": "risk: the term shifts cost, liability, or control onto the bidder in a way the bid team must price "
    "or decide to accept.",
    "unclear": "unclear: the bid team cannot act on it without asking the buyer, because the RFP is vague, "
    "incomplete, or out of date on the point.",
}

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

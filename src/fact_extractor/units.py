"""Unit-label pipeline (REVIEW.md, "A fact is a labelled source unit").

The PDF is cut into numbered units (sentences, list items, table rows, headings) by
code, the same way every time. The model writes no list of facts. For every unit it
answers a closed question: which category, or none. So the list of candidate facts,
and the identity of each fact, do not depend on the model.

One round of calls, all in parallel, all on the same cached prefix (system prompt +
document):

- LABEL, `votes` times: a label and flags for every unit. Majority wins; a split vote
  is recorded on the fact.
- STATE, once: a one-line statement for every unit, used as the fact's text when its
  numbers are in the unit. Otherwise the fact shows the RFP's own words.
- CHECK, once: places where the RFP disagrees with itself (Q facts).
- XREF, once: every reference to another part of the document, an attachment or an outside
  source, with the unit it points at. The model only finds them; code verifies each one
  (xref.py) and writes a Q fact only for what it can show is wrong.

Then a short second round, GROUP, one small call per category over the finished facts
(no document attached): which facts state the same point, and which are items of one
list. Groups change how facts are shown, never which facts exist.

A fact is one coded unit plus the units labelled as its continuation. Its ID is a hash
of the document and the unit ID: it does not change with the code, the wording or the
run. `mandatory` and `desirable` are read from the unit's own wording in code.

Two runs still differ on the code of about one unit in ten (trial, 2026-11-18): a
document's result is stored and shown again (results.py), not regenerated.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from . import prompts, xref
from .llm import CallFailed, LLMClient, RateLimited, Request
from .models import CallRecord, CallSpec, TaggedDocument
from .normalize import missing_values, values
from .playbooks import Playbook, definition, load
from .validate import check_output

# Part of the key a stored result is found by. Change it whenever the prompts or the way
# the PDF is cut into units change: a result stored under another version is not reused.
# units-2: table cells are read word by word (spaces kept, wrapped rows joined).
# units-3: facts carry groups (same point restated, items of one list).
# units-4: an incomplete label or statement answer is retried; the buyer brief is stored.
# units-5: a cross-reference call (XREF) finds the references; code verifies them (Q facts).
VERSION = "units-5"

_RFP = load("rfp")  # the reading rules of an RFP: playbooks/rfp.md
CODES = _RFP.codes
PRECEDENCE = _RFP.precedence
MODEL_FLAGS = _RFP.flags  # judged by the model, by majority
CONTINUES, NOTHING, NO_ANSWER = "=", "-", "?"
CONTINUATION_REACH = 3  # a continuation attaches to a coded unit at most this many units back

SYSTEM = _RFP.system()


def label_task(ids: list[str], pb: Playbook | None = None) -> str:
    flags = (pb or _RFP).flags
    return f"""TASK LABEL
Write exactly one line for each of these {len(ids)} units, in this order:
{", ".join(ids)}

Line format: ID|LABEL|flags
LABEL is one of:
- a category code, when the unit states a point;
- {CONTINUES} when the unit only continues, qualifies, or repeats the point of a unit shortly before it;
- {NOTHING} when the unit states no point.
A unit that makes two separate points of two categories gets both codes joined by +, the main one first, for example X+D. This is rare.
flags is empty or a comma-separated list of: {", ".join(flags)}. Decide each flag for each unit on its own. Units labelled {CONTINUES} or {NOTHING} carry no flags.
Read each unit with the units around it before you label it.
After the last line write: END|number of lines"""


def state_task(ids: list[str], pb: Playbook | None = None) -> str:
    noun = (pb or _RFP).noun
    return f"""TASK STATE
Write exactly one line for each of these {len(ids)} units, in this order:
{", ".join(ids)}

Line format: ID|statement
The statement says the unit's point in plain words, under 30 words, for a reader who will not see {noun}. Say what {noun} says, no more: keep who must act, how binding it is (must, should, may), and its conditions. Name the form, the number, the deadline, the person. Copy numbers, amounts, and units exactly. Write dates as YYYY-MM-DD, with the time and time zone if {noun} gives them. Start a requirement with what the bidder must do. A statement is a sentence only: no category code, no flag, and never the | character.
If the unit only continues or qualifies the unit before it, state the whole point the two make together.
If the unit states no point, write: ID|{NOTHING}
After the last line write: END|number of lines"""


CHECK_TASK = """TASK CHECK
Find every place where the RFP disagrees with itself. Look most carefully at:
- dates that differ for the same event
- page limits, copy counts, or file formats that differ
- a requirement that a later section changes or removes
- a value in a table that differs from the same value in the text
- a form named in one place and missing from the forms list
- evaluation points or weights that do not add up, or criteria named differently in two places
- a contract term in the RFP that differs from the sample contract
- a reference to a section, article, form, or attachment that is blank, missing, or numbered differently
- two different cut-off or as-of dates for the same data

For each disagreement write one line:
Q|side 1 vs side 2, in under 30 words|ID of side 1,ID of side 2|
Do not report differences in wording that mean the same thing.
After the last line write: END|number of lines. If there is none, write only: END|0"""


GROUP_SYSTEM = """You tidy a list of facts taken from an RFP for a bid manager, who reads them as a list.

The list is hard to read for two reasons:
- The same point appears more than once, because the RFP states it in more than one place.
- The items of one list or table appear as separate lines that differ only in the item.

You group such lines. You never rewrite, drop, or add a fact.

INPUT
Lines in the form: number|page|fact. All are facts of one category.

OUTPUT
One line per group:
SAME|numbers
LIST|title|numbers
numbers is a comma-separated list of line numbers, at least two.
- SAME: the lines state one and the same point. Any one of them could stand for the others with nothing lost: same parties, same dates, same amounts, same conditions.
- LIST: the lines are items of one list. They share a frame and differ in the item named. The title says what the list is, in under 8 words, for example: Required insurance coverages.
A line belongs to at most one group. Do not group lines only because they share a topic. A line that stands alone is not written.
After the last group write: END|number of groups. If there is none, write only: END|0"""


# --- section summaries for the Overview page ----------------------------------------------
#
# One short summary per section, written by the model from that section's facts and from
# nothing else. Every summary has fixed rows, always the same and in the same order, so
# the screen has the same shape for every RFP. Each row cites the facts it rests on.

@dataclass(frozen=True)
class Section:
    key: str
    title: str
    codes: tuple[str, ...]  # the facts the summary is written from
    about: str
    rows: tuple[tuple[str, str], ...]  # (row name, what goes in it)
    unclear_too: bool = False  # also give it the facts flagged unclear, whatever their code


SECTIONS = (
    Section("buyer", "Buyer information", ("B",), "the buyer of an RFP", (
        ("Buyer", "the organization and department buying."),
        ("Solicitation", "its name and number."),
        ("What they are buying", "the product or service, in one sentence."),
        ("Why", "the buyer's stated goals or reasons."),
        ("Scale", "the numbers that size the work (people, users, sites, volumes, budget)."),
        ("Current situation", "what the buyer uses or does today, and what was already decided."),
        ("Contacts", "who to contact and how."),
    )),
    Section("submission", "Submission instructions", ("S", "D"), "how to submit a proposal for an RFP", (
        ("Deadline", "when the proposal is due, with time and time zone."),
        ("How to submit", "the method and the address, portal, or email to send it to."),
        ("Format", "file format, copies, page limits, layout rules, and how the proposal is structured."),
        ("What to include", "the parts and documents the proposal must contain."),
        ("Required forms", "every form, certificate, or signature that must be in the package, by name."),
        ("Questions", "how and until when to ask the buyer questions."),
    )),
    Section("gates", "Go/no-go gates", ("G", "X"), "whether a bidder may bid on an RFP and what gets a proposal rejected", (
        ("Who may bid", "what the bidder must already be or hold: status, licences, registrations, approvals."),
        ("Experience required", "past projects, years in business, references, or size the bidder must show."),
        ("Before the deadline", "steps the bidder must have taken by then, such as a meeting or a registration."),
        ("Rejected if", "what causes a proposal or bidder to be rejected or disqualified."),
    )),
    Section("scoring", "Scoring criteria", ("E",), "how proposals for an RFP are scored and the winner chosen", (
        ("Method", "how the winner is chosen: best value, lowest price, points, pass or fail."),
        ("Criteria", "each scoring criterion, with its points or weight when the RFP gives one."),
        ("Price", "how price or cost is scored or weighed."),
        ("Stages", "shortlisting, presentations, interviews, or negotiations after the first evaluation."),
        ("Who decides", "who evaluates and who makes the award."),
    )),
    Section("questions", "Clarifications", ("Q",), "points in an RFP to raise with the buyer", (
        ("Contradictions", "where the RFP disagrees with itself, each as one question to the buyer."),
        ("Unclear points", "what is vague, incomplete, or out of date, each as one question to the buyer."),
    ), unclear_too=True),
)
SECTION = {sec.key: sec for sec in SECTIONS}


def brief_system(sec: Section) -> str:
    rows = "\n".join(f"{name}|text|fact numbers" for name, _ in sec.rows)
    guide = "\n".join(f"- {name}: {what}" for name, what in sec.rows)
    return f"""You write a short summary about {sec.about}, for a bid manager deciding whether and how to bid.

INPUT
Numbered facts taken from the RFP. Use nothing else: no outside knowledge, no guesses.

OUTPUT
Exactly these rows, in this order, one line each:
{rows}
{guide}
text is plain words, under 60 words, with names, numbers, dates and addresses copied exactly. Separate several items with semicolons. Never use the | character in it.
fact numbers is a comma-separated list of the facts the text rests on.
When the facts say nothing for a row, write: Row|not stated|
After the last row write: END|{len(sec.rows)}"""


def section_facts(sec: Section, records: list[dict]) -> list[dict]:
    return [
        r for r in records
        if r["category"] in sec.codes or (sec.unclear_too and "unclear" in r["flags"])
    ]


def brief_task(facts: list[dict]) -> str:
    lines = "\n".join(f"{n}|{f['text'].replace('|', '/')}" for n, f in enumerate(facts, start=1))
    return f"TASK BRIEF\n\n{lines}"


def parse_brief(text: str, facts: list[dict], rows: tuple[str, ...]) -> list[dict]:
    """The section's rows, always. A row is `checked` when it cites facts and every number in
    it is in those facts; the screen shows the cited facts themselves for a row that is
    not, so a figure the model made up is never shown as the RFP's."""
    got: dict[str, dict] = {}
    names = {r.lower(): r for r in rows}
    for line in text.splitlines():
        p = [x.strip() for x in line.split("|")]
        row = names.get(p[0].lower())
        if row is None or row in got or len(p) < 2:
            continue
        body = " ".join(p[1].split())
        cited = []
        for x in (p[2] if len(p) > 2 else "").split(","):
            x = x.strip()
            if x.isdigit() and 1 <= int(x) <= len(facts) and facts[int(x) - 1] not in cited:
                cited.append(facts[int(x) - 1])
        stated = bool(body) and body.lower() != "not stated"
        sources = [f["text"] for f in cited] + [f.get("source_text", "") for f in cited]
        got[row] = {
            "row": row, "text": body if stated else "",
            "fact_ids": [f["fact_id"] for f in cited] if stated else [],
            "checked": stated and bool(cited) and not missing_values(body, sources),
        }
    return [got.get(r, {"row": r, "text": "", "fact_ids": [], "checked": False}) for r in rows]


def group_task(code: str, facts: list[dict], doc_labels: dict[str, str] | None = None) -> str:
    """The GROUP task. `doc_labels` (fact ID -> "d2") is given across a bid: page numbers repeat
    from one document to the next, so each line's page field then starts with its document."""
    def page(f: dict) -> str:
        label = f["citations"][0]["page_label"] if f["citations"] else ""
        if doc_labels is None:
            return label
        return " ".join(x for x in (doc_labels.get(f["fact_id"], ""), f"p.{label}" if label else "") if x)

    lines = "\n".join(
        f"{n}|{page(f)}|{f['text'].replace('|', '/')}" for n, f in enumerate(facts, start=1)
    )
    return f"TASK GROUP\nCategory: {definition(code).split(':', 1)[0]}\n\n{lines}"


def parse_groups(text: str, count: int) -> list[tuple[str, str, list[int]]]:
    """(kind, title, 1-based line numbers) per group. A line stays in the first group that
    names it; a group left with fewer than two lines is dropped."""
    out: list[tuple[str, str, list[int]]] = []
    taken: set[int] = set()
    for line in text.splitlines():
        p = [x.strip() for x in line.split("|")]
        kind = p[0].upper()
        if kind == "SAME" and len(p) >= 2:
            title, numbers = "", p[1]
        elif kind == "LIST" and len(p) >= 3:
            title, numbers = " ".join(p[1].split()), p[2]
        else:
            continue
        members = []
        for x in numbers.split(","):
            x = x.strip()
            if x.isdigit() and 1 <= int(x) <= count and int(x) not in taken and int(x) not in members:
                members.append(int(x))
        if len(members) >= 2 and (kind == "SAME" or title):
            taken.update(members)
            out.append((kind.lower(), title, members))
    return out


def apply_groups(records: list[dict], groups: list[tuple[str, str, list[dict]]], doc_id: str) -> None:
    """Write group_id, group_kind and group_title on the member facts.

    A "same" group whose members do not hold the same numbers and dates is not the same
    point: it is kept as a list, so nothing is hidden behind another fact.
    """
    for r in records:
        r.update({"group_id": "", "group_kind": "", "group_title": ""})
    for kind, title, members in groups:
        if kind == "same" and len({frozenset(values(m["text"])) for m in members}) > 1:
            kind, title = "list", "Related statements"
        gid = "g_" + hashlib.sha1(
            "|".join([doc_id, kind] + sorted(m["fact_id"] for m in members)).encode()
        ).hexdigest()[:10]
        for m in members:
            m.update({"group_id": gid, "group_kind": kind, "group_title": title or members[0]["text"]})


# --- mandatory and desirable, from the unit's own words ----------------------------------

_MANDATORY = re.compile(r"\b(shall|must|required|requires?|mandatory|will not be (?:considered|accepted|opened))\b", re.I)
_DESIRABLE = re.compile(r"\b(should|preferred|preferably|prefers?|desires?|desired|desirable|encouraged?|optional|recommended)\b", re.I)
_BINDS_BIDDER = ("R", "S", "G", "C", "X")  # categories where a modal verb is about the bidder


def modal_flags(code: str, text: str) -> list[str]:
    """`mandatory` or `desirable`, read from the wording. The same text gives the same flag."""
    if code not in _BINDS_BIDDER:
        return []
    if _MANDATORY.search(text):
        return ["mandatory"]
    if _DESIRABLE.search(text):
        return ["desirable"]
    return []


# --- config, plan ------------------------------------------------------------------------


@dataclass
class Config:
    votes: int = 3
    units_per_label_call: int = 60
    units_per_state_call: int = 40
    max_parallel: int = 48  # every call of the one round at once on a ~50-page RFP
    label_max_output_tokens: int = 4000
    state_max_output_tokens: int = 6000
    check_max_output_tokens: int = 8000
    call_timeout: float = 120.0
    warmup_timeout: float = 10.0  # wait at most this long for the first call to stream
    rate_limit_retries: int = 5
    backoff_base: float = 1.0
    statements: bool = True
    check: bool = True
    xref: bool = True  # the cross-reference call; its facts are checked in code
    xref_max_output_tokens: int = 12000  # reasoning counts against it; 8000 was cut once on a long document
    brief: bool = True  # second round: the section summaries for the Overview page
    brief_max_output_tokens: int = 2500
    grouping: bool = True  # second round: group repeated points and list items
    group_max_output_tokens: int = 4000
    group_min_facts: int = 4  # a category with fewer facts is not worth a call


def chunks(doc: TaggedDocument, size: int) -> list[list[str]]:
    """Whole pages, in order, about `size` units per call."""
    out: list[list[str]] = [[]]
    page = None
    for a in doc.anchors.values():
        if a.page != page and len(out[-1]) >= size:
            out.append([])
        page = a.page
        out[-1].append(a.id)
    return [c for c in out if c]


# --- parsing -----------------------------------------------------------------------------

Label = tuple[tuple[str, ...], tuple[str, ...]]  # (codes or one of = - , flags)


def parse_labels(text: str, ids: list[str], pb: Playbook | None = None) -> dict[str, Label]:
    pb = pb or _RFP
    want = set(ids)
    out: dict[str, Label] = {}
    for line in text.splitlines():
        p = [x.strip() for x in line.split("|")]
        uid = p[0].strip("[]")
        if len(p) < 2 or uid not in want:
            continue
        codes = tuple(c for c in p[1].upper().replace(" ", "").split("+") if c)
        special = set(codes) & {CONTINUES, NOTHING}
        if not codes or len(codes) > 2 or (special and len(codes) > 1) or not all(c in pb.codes or c in special for c in codes):
            continue
        flags = tuple(f for f in pb.flags if f in {x.strip().lower() for x in (p[2] if len(p) > 2 else "").split(",")})
        out[uid] = (codes, flags if codes[0] in pb.codes else ())
    return out


# "X: The City may reject...", "R, post-award: The City will verify...": a label written in
# front of the statement. The label comes from the votes, never from here.
_LEAKED_LABEL = re.compile(r"^[BCGXDSERQ](?:\s*[,+]\s*[A-Za-z-]+)*\s*:\s+(?=[A-Z0-9\"“(])")


def has_end(text: str) -> bool:
    """The END line every label and statement task asks for as its last line."""
    return any(ln.strip().upper().startswith("END|") for ln in text.splitlines())


def stated_ids(text: str, ids: list[str]) -> set[str]:
    """The units a STATE answer has a line for, "no point" lines included."""
    want = set(ids)
    out = set()
    for line in text.splitlines():
        uid, sep, rest = line.partition("|")
        uid = uid.strip().strip("[]")
        if sep and uid in want and rest.strip().rstrip("|").strip():
            out.add(uid)
    return out


def parse_statements(text: str, ids: list[str]) -> dict[str, str]:
    want = set(ids)
    out: dict[str, str] = {}
    for line in text.splitlines():
        uid, sep, rest = line.partition("|")
        uid = uid.strip().strip("[]")
        statement = rest.strip().rstrip("|").strip()
        statement = _LEAKED_LABEL.sub("", statement)
        if sep and uid in want and statement and statement != NOTHING:
            out[uid] = " ".join(statement.split())
    return out


# --- votes -> facts ----------------------------------------------------------------------


@dataclass
class Voted:
    label: str  # a code, "=", "-" or "?"
    also: str | None
    flags: list[str]
    votes: list[str]

    @property
    def agreed(self) -> bool:
        return len(set(self.votes)) == 1


def _rank(label: str, pb: Playbook | None = None) -> int:
    order = (pb or _RFP).precedence
    return order.index(label) if label in order else len(order) + (CONTINUES, NOTHING, NO_ANSWER).index(label)


def vote(passes: list[dict[str, Label]], units: list[str], pb: Playbook | None = None) -> dict[str, Voted]:
    """Majority per unit on the main label. With no majority the unit is kept, under the
    code that comes first in the playbook's precedence: a missed fact costs more than an extra one."""
    pb = pb or _RFP
    out: dict[str, Voted] = {}
    for u in units:
        got = [p.get(u) for p in passes]
        mains = [g[0][0] if g else NO_ANSWER for g in got]
        count = Counter(mains).most_common()
        main = min((m for m, n in count if n == count[0][1]), key=lambda m: _rank(m, pb))
        same = [g for g in got if g and g[0][0] == main]
        seconds = Counter(g[0][1] for g in same if len(g[0]) > 1).most_common(1)
        also = seconds[0][0] if seconds and seconds[0][1] * 2 > len(same) else None
        flags = [f for f in pb.flags if sum(f in g[1] for g in same) * 2 > len(same)]
        out[u] = Voted(main, also, flags if main in pb.codes else [], mains)
    return out


@dataclass
class Group:
    """One fact: a coded unit and the continuation units after it."""

    main: str
    ids: list[str]
    voted: Voted


def group(voted: dict[str, Voted], units: list[str], pb: Playbook | None = None) -> list[Group]:
    codes = (pb or _RFP).codes
    out: list[Group] = []
    at = -CONTINUATION_REACH - 1
    for n, u in enumerate(units):
        v = voted[u]
        if v.label in codes:
            out.append(Group(u, [u], v))
            at = n
        elif v.label == CONTINUES and out and n - at <= CONTINUATION_REACH:
            out[-1].ids.append(u)
            at = n  # a run of continuations stays attached
    return out


def fact_id(doc_id: str, unit_id: str) -> str:
    """The fact is the unit: the ID holds no code and no wording."""
    return "f_" + hashlib.sha1(f"{doc_id}|{unit_id}".encode()).hexdigest()[:10]


def _statement(g: Group, doc: TaggedDocument, statements: dict[str, str]) -> tuple[str, str]:
    """The fact's text and where it came from: the model's statement when every number in
    it is in the fact's units, else the RFP's own words.
    """
    source = " ".join(doc.anchors[i].text for i in g.ids)
    s = statements.get(g.main)
    if s:
        texts = [doc.anchors[i].text for i in g.ids] + [doc.anchors[i].section for i in g.ids]
        if not missing_values(s, texts):
            return s, "model"
    return source, "rfp"


def to_records(
    groups: list[Group], doc: TaggedDocument, statements: dict[str, str], deal_id: str, run_id: str,
    pb: Playbook | None = None,
) -> list[dict]:
    pb = pb or _RFP
    records = []
    for g in groups:
        v = g.voted
        source = " ".join(doc.anchors[i].text for i in g.ids)
        text, text_from = _statement(g, doc, statements)
        tally = Counter(v.votes)
        records.append({
            "fact_id": fact_id(doc.doc_id, g.main),
            "deal_id": deal_id, "doc_id": doc.doc_id, "run_id": run_id,
            "category": v.label, "also": v.also,
            "text": text, "text_from": text_from, "source_text": source,
            "citations": [doc.anchors[i].citation() for i in g.ids],
            "unresolved_ids": [],
            # From the main unit alone, so the flag does not move when a continuation joins or leaves.
            "flags": modal_flags(v.label, doc.anchors[g.main].text) + v.flags,
            "note": "",
            "status": "valid",
            "votes": v.votes, "agreement": f"{tally[v.label]}/{len(v.votes)}",
            "source_call": "LABEL", "playbook": pb.name,
            "problems": [], "conflicts": [],
        })
    return records


# --- the run -----------------------------------------------------------------------------


@dataclass
class RunResult:
    run_id: str
    facts: list[dict]
    report: dict
    labels: list[dict] = field(default_factory=list)  # every unit with its votes, coded or not
    held_refs: list[dict] = field(default_factory=list)  # {unit, text, rule}: section references held back for RELATE
    section_units: list[str] = field(default_factory=list)  # units with a reference to a section (candidates for RELATE)


class _Run:
    def __init__(self, doc: TaggedDocument, client: LLMClient, cfg: Config, pb: Playbook | None = None) -> None:
        self.doc, self.client, self.cfg = doc, client, cfg
        self.pb = pb or _RFP
        self.system = self.pb.system()
        self.sem = asyncio.Semaphore(cfg.max_parallel)
        self.calls: list[CallRecord] = []
        self.cache_key = "fx-" + hashlib.sha256((self.system + doc.tagged_text).encode()).hexdigest()[:24]

    async def call(self, name: str, kind: str, task: str, cap: int, effort: str = "low",
                   started: asyncio.Event | None = None, system: str | None = None,
                   covered: Callable[[str], int] | None = None, expected: int = 0) -> str:
        """One model call; retried once on an error, with backoff on rate limits. Returns
        the text, or "" when it failed (the units it covered then have one vote fewer).

        `covered` counts the units an answer covers, of `expected`. An answer covering
        fewer units than it was given is not a success: the model stopped early or wrote
        something else (on Durham, one label call answered 12 of 74 units and filled the
        rest with its own notes, and was logged as ok). Such a call is sent once more;
        the answer covering more units is kept, and a call that is still short is
        recorded as "incomplete", not "ok". A missing END line alone is only logged.
        """
        rec = CallRecord(name, kind)
        self.calls.append(rec)
        if system is None:
            req = Request(self.system, self.doc.tagged_text, task, effort, cap, self.cache_key)
        else:  # a call about the facts, not the document: nothing to cache, nothing to attach
            req = Request(system, "", task, effort, cap)
        t0 = time.monotonic()
        errors = limited = 0
        short: tuple[int, str, object] | None = None  # the best incomplete answer so far
        try:
            while True:
                first: list[float] = []

                def on_text(_: str) -> None:
                    if not first:
                        first.append(time.monotonic())
                    if started is not None:
                        started.set()

                try:
                    q0 = time.monotonic()
                    async with self.sem:
                        sent = time.monotonic()
                        rec.queue_seconds += sent - q0
                        resp = await asyncio.wait_for(self.client.complete(req, on_text), self.cfg.call_timeout)
                    rec.model_seconds = round(time.monotonic() - sent, 3)
                    if first:
                        rec.ttft_seconds = round(first[0] - sent, 3)
                    text = resp.text
                    if covered is not None:
                        n = covered(text)
                        # Only missing units are worth a second call. With every unit answered, a
                        # missing END line costs nothing (two statement calls did that on Durham,
                        # and retrying them added about ten seconds for the same answer).
                        if n < expected and short is None and not resp.truncated:
                            what = f"answered {n} of {expected} units" + ("" if has_end(text) else ", no END line")
                            short = (n, text, resp)
                            rec.retries += 1
                            rec.log.append(f"incomplete ({what}); asking once more")
                            continue
                        if short is not None and short[0] > n:  # the first answer covered more: keep that one
                            n, text, resp = short  # type: ignore[assignment]
                        if n < expected and not resp.truncated:
                            rec.status = "incomplete"
                            rec.log.append(
                                f"still incomplete after one retry; kept the answer covering {n} of {expected} units"
                            )
                        elif not has_end(text) and not resp.truncated:
                            rec.log.append("every unit answered, but no END line")
                    rec.usage, rec.output = resp.usage, text
                    rec.lines = sum(1 for ln in text.splitlines() if ln.strip())
                    if resp.truncated:
                        rec.status = "partial"
                        rec.log.append("output cut at the token cap; kept the lines written")
                    return text
                except RateLimited:
                    limited += 1
                    rec.retries += 1
                    if limited > self.cfg.rate_limit_retries:
                        raise CallFailed("rate limited too many times")
                    await asyncio.sleep(self.cfg.backoff_base * 2 ** (limited - 1))
                except (CallFailed, asyncio.TimeoutError) as e:
                    errors += 1
                    rec.retries += 1
                    if errors > 1:
                        raise CallFailed(str(e) or "timeout") from e
                    rec.log.append(f"retrying after error: {e or 'timeout'}")
        except CallFailed as e:
            if short is not None:  # the retry of an incomplete answer failed: the answer is still worth its lines
                rec.status = "incomplete"
                rec.log.append(f"retry failed ({e}); kept the first answer, covering {short[0]} of {expected} units")
                rec.usage, rec.output = short[2].usage, short[1]  # type: ignore[attr-defined]
                rec.lines = sum(1 for ln in short[1].splitlines() if ln.strip())
                return short[1]
            rec.status = "failed"
            rec.log.append(f"call failed: {e}")
            return ""
        finally:
            rec.seconds = round(time.monotonic() - t0, 3)
            if started is not None:
                started.set()


async def extract(
    doc: TaggedDocument, client: LLMClient, *, deal_id: str, cfg: Config | None = None, run_id: str | None = None,
    playbook: Playbook | None = None, hold_section_refs: bool = False,
) -> RunResult:
    """`hold_section_refs`: a reference to a section that has no target in this document is not
    written as a Q fact but returned on `RunResult.held_refs`, for a document that points at
    earlier documents (an addendum); RELATE answers for it later."""
    pb = playbook or _RFP
    cfg = cfg or Config()
    run_id = run_id or f"run_{datetime.now(timezone.utc):%Y_%m_%d}_{uuid.uuid4().hex[:6]}"
    run = _Run(doc, client, cfg, pb)
    units = list(doc.anchors)
    label_parts = chunks(doc, cfg.units_per_label_call)
    state_parts = chunks(doc, cfg.units_per_state_call) if cfg.statements and "STATE" in pb.calls else []
    t0 = time.monotonic()

    async def label(vote_no: int, k: int, ids: list[str], started: asyncio.Event | None = None) -> dict[str, Label]:
        text = await run.call(
            f"LABEL{k}#{vote_no}", "label", label_task(ids, pb), cfg.label_max_output_tokens, started=started,
            covered=lambda t: len(parse_labels(t, ids, pb)), expected=len(ids),
        )
        return parse_labels(text, ids, pb)

    async def state(k: int, ids: list[str]) -> dict[str, str]:
        text = await run.call(
            f"STATE{k}", "state", state_task(ids, pb), cfg.state_max_output_tokens,
            covered=lambda t: len(stated_ids(t, ids)), expected=len(ids),
        )
        return parse_statements(text, ids)

    async def check() -> list[dict]:
        if not cfg.check or "CHECK" not in pb.calls:
            return []
        spec = CallSpec("CHECK", ("Q",), CHECK_TASK, effort="medium")
        text = await run.call("CHECK", "check", CHECK_TASK, cfg.check_max_output_tokens, effort="medium")
        out = check_output([ln.strip() for ln in text.splitlines() if ln.strip()], spec, doc)
        return [
            {"text": c.line.fact, "ids": c.line.ids, "problems": list(c.reasons), "source_call": "CHECK"}
            for c in out.checked if c.line.code == "Q" and c.line.ids and all(i in doc.anchors for i in c.line.ids)
        ]

    async def cross_references() -> xref.Result:
        """The model finds the references, code verifies them. Never raises: a run without
        XREF facts is still a run, and the report says why there are none."""
        if not cfg.xref or "XREF" not in pb.calls:
            return xref.Result()
        text = await run.call("XREF", "xref", xref.TASK, cfg.xref_max_output_tokens, effort="medium")
        try:
            return xref.analyse(doc, text)
        except Exception as e:  # a bug in verification must not cost the run
            return xref.Result(status="error", error=f"{type(e).__name__}: {e}")

    # One call first, so the document is in the provider's cache before the rest are sent.
    started = asyncio.Event()
    first = asyncio.create_task(label(1, 1, label_parts[0], started))
    try:
        await asyncio.wait_for(started.wait(), cfg.warmup_timeout)
    except asyncio.TimeoutError:
        pass
    label_jobs = [
        (v, k, asyncio.create_task(label(v, k, ids)) if (v, k) != (1, 1) else first)
        for v in range(1, cfg.votes + 1) for k, ids in enumerate(label_parts, start=1)
    ]
    state_jobs = [asyncio.create_task(state(k, ids)) for k, ids in enumerate(state_parts, start=1)]
    check_job = asyncio.create_task(check())
    xref_job = asyncio.create_task(cross_references())
    passes: list[dict[str, Label]] = [{} for _ in range(cfg.votes)]
    for v, _, job in label_jobs:
        passes[v - 1].update(await job)
    statements: dict[str, str] = {}
    for job in state_jobs:
        statements.update(await job)
    q_lines = await check_job
    xres = await xref_job
    held: list[dict] = []
    if hold_section_refs:
        keep_p = [p for p in xres.problems if not (p.kind == "section" and p.rule in ("absent", "missing"))]
        held = [{"unit": p.ids[0], "text": p.terms[0] if p.terms else "", "rule": p.rule}
                for p in xres.problems if p not in keep_p]
        xres.problems = keep_p

    voted = vote(passes, units, pb)
    groups = group(voted, units, pb)
    records = to_records(groups, doc, statements, deal_id, run_id, pb)
    first_round = time.monotonic() - t0

    # Second round, about the finished facts and without the document: the buyer brief,
    # and the groups, one small call per category.
    async def brief(sec: Section, facts: list[dict]) -> list[dict]:
        names = tuple(n for n, _ in sec.rows)
        if not facts:
            return parse_brief("", facts, names)
        text = await run.call(f"BRIEF.{sec.key}", "brief", brief_task(facts), cfg.brief_max_output_tokens,
                              system=brief_system(sec))
        return parse_brief(text, facts, names)

    # Q facts exist only now; the summaries are written from every fact, Q included.
    sections = [sec for sec in SECTIONS if sec.key in pb.sections]
    q_records = _q_records(q_lines, xres, doc, deal_id, run_id)
    with_q = records + q_records
    brief_jobs = [asyncio.create_task(brief(sec, section_facts(sec, with_q))) for sec in sections] if cfg.brief else []
    found: list[tuple[str, str, list[dict]]] = []
    if cfg.grouping:
        async def group_category(code: str, facts: list[dict]) -> list[tuple[str, str, list[dict]]]:
            text = await run.call(f"GROUP.{code}", "group", group_task(code, facts), cfg.group_max_output_tokens,
                                  system=GROUP_SYSTEM)
            return [(k, t, [facts[n - 1] for n in ns]) for k, t, ns in parse_groups(text, len(facts))]

        by_code = {c: [r for r in records if r["category"] == c] for c in pb.codes}
        jobs = [group_category(c, fs) for c, fs in by_code.items() if len(fs) >= cfg.group_min_facts]
        found = [g for gs in await asyncio.gather(*jobs) for g in gs]
    apply_groups(records, found, doc.doc_id)
    briefs = {sec.key: await job for sec, job in zip(sections, brief_jobs)}
    seconds = time.monotonic() - t0

    records += q_records
    _mark_conflicts(records)

    labels = [
        {"id": u, "page": doc.anchors[u].page_label, "section": doc.anchors[u].section, "text": doc.anchors[u].text,
         "label": voted[u].label, "also": voted[u].also, "flags": voted[u].flags, "votes": voted[u].votes,
         "speaker": doc.anchors[u].speaker, "side": doc.anchors[u].side}
        for u in units
    ]
    report = _report(run, doc, deal_id, run_id, records, voted, groups, statements, seconds, cfg)
    report["playbook"] = pb.key
    report["seconds"] = {
        "label_state_check": round(first_round, 2), "group_and_summaries": round(seconds - first_round, 2),
        "total": round(seconds, 2),
    }
    report["xref"] = xres.report()
    report["xref_conflicts"] = len(xres.problems)
    report["summaries"] = briefs
    report["groups"] = dict(Counter(k for k, _, _ in found))
    report["facts_in_groups"] = sum(bool(r.get("group_id")) for r in records)
    return RunResult(run_id, records, report, labels, held, list(xres.section_units))


def _q_records(q_lines: list[dict], xres: xref.Result, doc: TaggedDocument, deal_id: str, run_id: str) -> list[dict]:
    """Contradictions: the model's CHECK lines and the cross-reference problems verified in
    code. One Q fact per set of IDs."""
    seen: dict[frozenset, dict] = {}
    order = {i: n for n, i in enumerate(doc.anchors)}
    checks = [dict(q) for q in q_lines]
    found = []
    # A cross-reference problem about the same thing as a CHECK line is one fact: the CHECK wording,
    # the units of both in document order, source CHECK,XREF.
    matched = xref.match_problems([(q["ids"], q["text"]) for q in checks], xres.problems)
    for pi, p in enumerate(xres.problems):
        if pi in matched:
            c = checks[matched[pi]]
            c["ids"] = sorted(set(c["ids"]) | set(p.ids), key=order.__getitem__)
            if "XREF" not in c["source_call"].split(","):
                c["source_call"] += ",XREF"
        else:
            found.append({"text": p.text, "ids": list(p.ids), "problems": [], "source_call": "XREF"})
    for q in checks + found:
        key = frozenset(q["ids"])
        if key in seen:
            if q["source_call"] not in seen[key]["source_call"].split(","):
                seen[key]["source_call"] += "," + q["source_call"]
            continue
        seen[key] = {
            "fact_id": "f_" + hashlib.sha1(f"{doc.doc_id}|Q|{','.join(sorted(q['ids']))}".encode()).hexdigest()[:10],
            "deal_id": deal_id, "doc_id": doc.doc_id, "run_id": run_id,
            "category": "Q", "also": None, "text": q["text"], "text_from": "model",
            "source_text": " / ".join(doc.anchors[i].text for i in q["ids"]),
            "citations": [doc.anchors[i].citation() for i in q["ids"]], "unresolved_ids": [],
            "flags": [], "note": "", "status": "needs_review" if q["problems"] else "valid",
            "votes": [], "agreement": "", "source_call": q["source_call"],
            "problems": list(q["problems"]), "conflicts": [],
            "group_id": "", "group_kind": "", "group_title": "",
        }
    return list(seen.values())


def _mark_conflicts(records: list[dict]) -> None:
    """Facts that share a unit with a Q fact get status conflict and the Q fact's ID."""
    def cited(r: dict) -> set[tuple[str, str]]:
        # a unit is the pair (document, ID): two documents of a bid both have a p1.1
        return {(c.get("doc_id") or r.get("doc_id") or "", c["id"]) for c in r["citations"]}

    qs = [(r["fact_id"], cited(r)) for r in records if r["category"] == "Q"]
    for r in records:
        if r["category"] == "Q":
            continue
        ids = cited(r)
        r["conflicts"] = [qid for qid, q_ids in qs if ids & q_ids]
        if r["conflicts"] and r["status"] == "valid":
            r["status"] = "conflict"


def _report(run: _Run, doc, deal_id, run_id, records, voted, groups, statements, seconds, cfg) -> dict:
    # Only the calls that send the document share its cache key; GROUP and BRIEF send no document.
    doc_calls = [c for c in run.calls if c.kind not in ("group", "brief")]
    later = [c for c in doc_calls[1:] if c.usage.input_tokens]
    cache_in = sum(c.usage.input_tokens for c in later)
    facts = [r for r in records if r["category"] != "Q"]
    return {
        "pipeline": VERSION, "run_id": run_id, "deal_id": deal_id, "doc_id": doc.doc_id,
        "pages": doc.page_count, "ids": len(doc.anchors),
        "facts": len(records),
        "by_category": dict(Counter(r["category"] for r in records)),
        "by_status": dict(Counter(r["status"] for r in records)),
        "votes": cfg.votes,
        "units_coded": sum(v.label in run.pb.codes for v in voted.values()),
        "units_continuing": sum(len(g.ids) - 1 for g in groups),
        "units_without_a_point": sum(v.label in (NOTHING, NO_ANSWER) for v in voted.values()),
        "units_unanswered_votes": sum(v == NO_ANSWER for x in voted.values() for v in x.votes),
        "facts_votes_agreed": sum(g.voted.agreed for g in groups),
        "facts_votes_split": sum(not g.voted.agreed for g in groups),
        "facts_with_statement": sum(r["text_from"] == "model" for r in facts),
        "facts_in_rfp_words": sum(r["text_from"] == "rfp" for r in facts),
        "seconds": {"total": round(seconds, 2)},
        "cache_hit_calls_2_to_n": round(sum(c.usage.cached_tokens for c in later) / cache_in, 3) if cache_in else None,
        "output_tokens": sum(c.usage.output_tokens for c in run.calls),
        "failed_calls": [c.name for c in run.calls if c.status == "failed"],
        "cut_calls": [c.name for c in run.calls if c.status == "partial"],
        "incomplete_calls": [c.name for c in run.calls if c.status == "incomplete"],
        "retried_calls": [c.name for c in run.calls if c.retries],
        "calls": [asdict(c) for c in run.calls],
    }

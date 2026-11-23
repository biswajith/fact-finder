"""Playbooks: the standing rules for reading one kind of document.

A playbook is a markdown file `<name>.md`: a header between `---` lines that code reads
(the cutter, the allowed codes and flags, which calls run, the allowed relation kinds, votes,
level, visibility, summary sections, version), then a body that the model reads. The header
is `key: value`, lists are `[a, b]`, `#` starts a comment, and an indented line continues the
value above it. There is no YAML dependency.

A body is one of two things. The `rfp` and `reissued-rfp` bodies are the whole system prompt,
with `{categories}`, `{precedence}` and `{flag_tests}` standing where code inserts the
category definitions, the order and the flag tests. Every other body holds only the reading
rules; `system()` puts the opening, the reader and the input paragraph before it and the
categories and flags after it. The header key `reads` names what is being read.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from .. import prompts

CUTTERS = ("pdf", "transcript", "notes", "sheet")
AUTHORITIES = ("buyer", "speaker", "notes")
ROLES = ("base", "change", "context")
CALLS = ("LABEL", "STATE", "CHECK", "XREF", "RELATE")
RELATIONS = ("REPLACES", "REMOVES", "ADDS", "CLARIFIES", "CONFIRMS", "DISAGREES", "NONE")
VISIBILITIES = ("external", "internal")
RELATE_TO = ("", "buyer documents")

# The codes only the transcript and notes playbooks use; the others are in prompts.DEFINITIONS.
DEFINITIONS = {
    "PRIORITY": "PRIORITY = buyer priority: what the buyer says matters most to them, what they want "
    "weighed heavily, and what they would trade away or give up.",
    "DECIDER": "DECIDER = who decides or influences: who makes, signs off, or sways the buying decision, "
    "and what role each person has in it.",
    "BUDGET": "BUDGET = money the buyer has or expects: a budget, a ceiling, a funding source, or a price "
    "the buyer expects or has been quoted.",
    "QUESTION": "QUESTION = an open question to settle: something the bid team does not yet know and must "
    "ask or find out before it can bid or answer.",
    "COMPETITOR": "COMPETITOR = competitor intelligence: who else is bidding or incumbent, and what is "
    "known about their offer, price, strengths, or standing with the buyer.",
    "ACTION": "ACTION = something our team must do: a task, follow-up, or commitment with or without an owner "
    "and a date.",
}

# Flag tests the RFP playbook does not use. The tests for the flags the RFP uses stay in prompts.FLAG_TESTS.
FLAG_TESTS = {
    **prompts.FLAG_TESTS,
    "tentative": "tentative: the source gives it as a guess, a hope, an estimate, or a possibility, not as "
    "settled. Test: would the speaker or writer stand behind it as fact? If not, it is tentative.",
    "precedence": "precedence: the unit says which document wins when documents disagree. Test: does it "
    "order documents against each other, rather than state a term itself?",
}

_KEYS = {
    "name", "description", "reads", "version", "cutter", "authority", "role", "codes", "flags", "precedence",
    "calls", "relations", "relate_to", "votes", "level", "visibility", "sections",
}
_LISTS = {"codes", "flags", "precedence", "calls", "relations", "sections"}
_INTS = {"version", "votes"}
_REQUIRED = ("name", "description", "cutter", "authority", "role", "codes", "calls")
_RFP_WORDING = ("rfp", "reissued-rfp")  # the two playbooks that keep the exact RFP wording


def definition(code: str) -> str:
    """The one-line definition of a category code, from the shared set or the new codes."""
    return prompts.DEFINITIONS.get(code) or DEFINITIONS[code]


@dataclass(frozen=True)
class Playbook:
    name: str
    description: str
    version: int
    cutter: str
    authority: str
    role: str
    codes: tuple[str, ...]
    flags: tuple[str, ...]
    precedence: tuple[str, ...]
    calls: tuple[str, ...]
    relations: tuple[str, ...]
    relate_to: str
    votes: int
    level: str
    visibility: str
    sections: tuple[str, ...]
    body: str
    reads: str = ""

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def noun(self) -> str:
        """How the task texts name the document: the RFP wording is kept byte for byte."""
        return "the RFP" if self.name in _RFP_WORDING else "the document"

    def system(self) -> str:
        """The system prompt of the label round."""
        categories = "\n".join(definition(c) for c in self.codes)
        flag_tests = "\n".join("- " + FLAG_TESTS[f] for f in self.flags)
        if "{categories}" in self.body:
            return (
                self.body.replace("{categories}", categories)
                .replace("{precedence}", ", ".join(self.precedence))
                .replace("{flag_tests}", flag_tests)
            )
        return f"""You read {self.reads} for a bid manager, unit by unit.

THE READER
The bid manager uses your work at three moments:
- Deciding whether to bid: can we qualify, can we win, what will it cost, what risk do we take on.
- Writing and submitting the proposal: what it must contain and answer, in what form, by when, and how it is scored.
- After winning: what the contract obliges the winner to do.
The bid manager reads your work instead of the source, and must not miss a deadline, a mandatory item, or a risky contract term.

INPUT
The user sends {self.reads} as tagged text. Each line is one unit and starts with its ID in brackets, for example [p12.4]. A second message gives your task and its output format. Write nothing but that output.

{self.body}

CATEGORIES
{categories}
When a point fits more than one code, use the first that fits in this order: {", ".join(self.precedence)}.

FLAGS
{flag_tests}

Judge every unit by the same standard, whatever the units around it got."""


def _value(key: str, raw: str, where: str):
    raw = raw.strip()
    if key in _LISTS:
        if not (raw.startswith("[") and raw.endswith("]")):
            raise ValueError(f"{where}: {key} must be a list like [a, b]")
        return tuple(x.strip() for x in raw[1:-1].split(",") if x.strip())
    if key in _INTS:
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"{where}: {key} must be a whole number, not {raw!r}") from None
    return raw


def parse(text: str, where: str = "playbook") -> Playbook:
    """Read one playbook file. Anything the header gets wrong raises ValueError naming `where`."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{where}: the file must start with a --- header line")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError(f"{where}: the header has no closing --- line") from None
    raw: dict[str, str] = {}
    last = ""
    for ln in lines[1:end]:
        ln = "" if ln.lstrip().startswith("#") else ln.split(" #", 1)[0]
        if not ln.strip():
            continue
        if ln[0] in " \t":
            if not last:
                raise ValueError(f"{where}: a continuation line with no key above it")
            raw[last] += " " + ln.strip()
            continue
        key, sep, rest = ln.partition(":")
        key = key.strip()
        if not sep or key not in _KEYS:
            raise ValueError(f"{where}: unknown header key {key!r}")
        if key in raw:
            raise ValueError(f"{where}: header key {key!r} given twice")
        raw[key], last = rest.strip(), key
    for key in _REQUIRED:
        if key not in raw:
            raise ValueError(f"{where}: header key {key!r} is missing")
    v = {k: _value(k, r, where) for k, r in raw.items()}
    body = "\n".join(lines[end + 1:]).strip("\n")

    def check(key: str, got, allowed: tuple[str, ...]) -> None:
        bad = [g for g in (got if isinstance(got, tuple) else (got,)) if g not in allowed]
        if bad:
            raise ValueError(f"{where}: unknown {key} {bad[0]!r}; allowed: {', '.join(allowed) or 'none'}")

    check("cutter", v["cutter"], CUTTERS)
    check("authority", v["authority"], AUTHORITIES)
    check("role", v["role"], ROLES)
    check("calls", v["calls"], CALLS)
    check("relations", v.get("relations", ()), RELATIONS)
    check("relate_to", v.get("relate_to", ""), RELATE_TO)
    check("visibility", v.get("visibility", "external"), VISIBILITIES)
    check("flags", v.get("flags", ()), tuple(FLAG_TESTS))
    try:
        for c in v["codes"]:
            definition(c)
    except KeyError as e:
        raise ValueError(f"{where}: unknown category code {e.args[0]!r}") from None
    precedence = v.get("precedence", v["codes"])
    if sorted(precedence) != sorted(v["codes"]):
        raise ValueError(f"{where}: precedence must list exactly the codes")
    if "RELATE" in v["calls"] and not v.get("relations"):
        raise ValueError(f"{where}: RELATE needs a relations list")
    if "{categories}" not in body and not v.get("reads"):
        raise ValueError(f"{where}: a body without {{categories}} needs a reads: key")
    return Playbook(
        name=v["name"], description=v["description"], version=v.get("version", 1), cutter=v["cutter"],
        authority=v["authority"], role=v["role"], codes=v["codes"], flags=v.get("flags", ()),
        precedence=precedence, calls=v["calls"], relations=v.get("relations", ()),
        relate_to=v.get("relate_to", ""), votes=v.get("votes", 3), level=v.get("level", "1"),
        visibility=v.get("visibility", "external"), sections=v.get("sections", ()), body=body,
        reads=v.get("reads", ""),
    )


def _files() -> dict[str, resources.abc.Traversable]:
    root = resources.files(__package__)
    return {p.name[:-3]: p for p in root.iterdir() if p.name.endswith(".md")}


def names() -> list[str]:
    return sorted(_files())


@lru_cache(maxsize=None)
def load(name: str) -> Playbook:
    files = _files()
    if name not in files:
        raise ValueError(f"no playbook named {name!r}; known: {', '.join(sorted(files))}")
    pb = parse(files[name].read_text(encoding="utf-8"), f"{name}.md")
    if pb.name != name:
        raise ValueError(f"{name}.md: the name in the header is {pb.name!r}")
    return pb


def all() -> list[Playbook]:  # noqa: A001 - the name is the contract
    return [load(n) for n in names()]

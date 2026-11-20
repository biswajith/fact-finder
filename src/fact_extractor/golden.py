"""Reference ("gold") fact lists from the golden-dataset builder, instead of by hand.

Recall (`score`) is measured against a reference list, one `CODE|fact|IDs|flags` line per
fact. Writing that list by hand is the slow part. `goldset` (src/goldset) builds checked
cases for a prompt over a source: a worker writes the expected output with verbatim-quote
evidence, code and a gate check it, and what fails is corrected or handed to a human. This
module feeds it the tagged RFP and turns what it accepts back into a gold file.

How the pieces fit:
- The source is the tagged text, one unit per line, `[id] text`, with page markers and blank
  lines placed so goldset's chunker only cuts at page and section boundaries (`source_text`).
- There is one prompt per category. The case input is the ID of one unit; the expected output
  is that unit's gold line(s) in exactly the gold format, or NONE. The wording shares the
  extractor's definitions: the category from `prompts.DEFINITIONS`, the fact rules and the
  flag tests from `prompts.SYSTEM`, read, never changed (`prompt_text`).
- `mandatory` and `desirable` are never asked of the model; code sets them from the cited
  unit's own wording (`units.modal_flags`), the same as in the extractor.
- `to_gold` parses and checks every accepted case again, drops what cannot be a gold line,
  and merges one unit filed under two categories into one line with alternates (`C/R`).

The result is a checked sample, not every fact in the RFP: goldset writes a budgeted number
of cases per category and the planner picks which units to cover. `score` measures recall
against whatever the list holds, so that is a valid yardstick, but a high recall on it is not
"found every fact". goldset's coverage figure says how much of the document the cases touch
(for a text source: the share of its page and section chunks), not how many facts were found.

Not in this version: Q (contradictions). A contradiction cites two places, so its case needs
a different shape (two unit IDs in, one line out).

goldset is imported inside the functions, so this module imports without the `evals` extra.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Callable

from . import prompts
from .models import TaggedDocument
from .results import safe_name
from .tagging import tag_pages
from .units import modal_flags

CODES = "BCGXDSER"  # every category goldset builds a reference for; Q is skipped (see above)
MODEL_FLAGS = ("risk", "unclear", "post-award")  # what the model may write; the rest is code's
DEFAULT_CASES = 30
_UNIT = re.compile(r"^\[([^\]]+)\] ")

# --- the source ------------------------------------------------------------------------


def source_text(doc: TaggedDocument, max_block: int = 3000) -> str:
    """The tagged document as a goldset text source.

    goldset's chunker works on blocks: runs of lines between blank lines and `#` headings.
    It cuts only between blocks, when a chunk is full or, at a `## ` heading, once half full.
    So a page starts with `## Page N`, a heading unit starts a new block, and no block grows
    past `max_block` characters (half goldset's default chunk). A unit is one line, so it is
    never cut, and a quote from inside a unit is found verbatim in this text.
    """
    out: list[str] = []
    page, size = None, 0
    for line in doc.tagged_text.splitlines():
        m = _UNIT.match(line)
        anchor = doc.anchors.get(m[1]) if m else None
        if anchor is not None and anchor.page != page:
            page, size = anchor.page, 0
            out += ["", f"## Page {page}"]
        elif anchor is not None and (anchor.kind == "heading" or size + len(line) > max_block):
            out.append("")
            size = 0
        out.append(line)
        size += len(line) + 1
    return "\n".join(out).lstrip("\n") + "\n"


# --- the prompts -----------------------------------------------------------------------


def _section(title: str) -> str:
    """One section of `prompts.SYSTEM`, from the line after its title to the next blank line."""
    marker = f"\n{title}\n"
    start = prompts.SYSTEM.index(marker) + len(marker)
    end = prompts.SYSTEM.find("\n\n", start)
    return prompts.SYSTEM[start : len(prompts.SYSTEM) if end < 0 else end]


def _flag_tests() -> str:
    """The extractor's tests for the flags the model decides, word for word."""
    lines = _section("FLAGS").splitlines()
    return "\n".join(ln for ln in lines if any(ln.startswith(f"- {f}:") for f in MODEL_FLAGS))


def _writing_rules() -> str:
    return "\n".join(ln for ln in _section("WRITING").splitlines() if "Q line" not in ln)


def prompt_text(code: str, cases: int) -> str:
    """The goldset prompt for one category: front matter, then the task."""
    if code not in CODES:
        raise ValueError(f"no reference prompt for category {code!r}; choose from {', '.join(CODES)}")
    order = ", ".join(prompts.PRECEDENCE)
    body = f"""You write the reference ("gold") facts of category {code} for an RFP fact extractor. The reference list is
what the extractor is scored against, so each line must be a fact the extractor should find, and a unit
with no fact of this category must get none.

THE READER
{_section("THE READER")}

THE SOURCE
The source is an RFP cut into units, one per line, each starting with its ID in brackets: [ID] text.
Lines that start with ## Page are page markers, not units. Blank lines mean nothing.

THE CASE
The input is the ID of one unit (the text between its brackets). The output is the gold line(s) for that unit.
Pick units across the whole source. Include units that state a fact of category {code}, and some that look
similar but state none (the output is NONE), so the list shows what to leave out.

CATEGORY
{prompts.DEFINITIONS[code]}

WHAT A FACT IS
{_section("WHAT A FACT IS")}

OUTPUT
Write one line per fact whose main source is the input unit, in exactly this form:
{code}|fact|IDs|flags
- The first field is {code}. Nothing else is allowed there, no alternates.
- IDs: comma-separated unit IDs without brackets. The first (main) ID is the input unit. Add a neighbouring
  unit's ID only when the fact needs it (a condition, exception, or consequence in the next sentence). Use only
  IDs that are in the source.
- flags: empty, or a comma-separated list of risk, unclear, post-award. Decide each on its own with the tests
  below. Never write mandatory or desirable: code sets them from the unit's own wording. Never write replaced.
- Write NONE, alone, when the unit states no fact of category {code}, or when it only repeats, continues, or
  qualifies a point whose main unit is a neighbouring unit.
- A statement can fit more than one category. Write the line when it fits {code}, even if a category that comes
  earlier in this order also fits: {order}. A prompt for each category is run, and the lines are merged.
- Nothing else: no headings, no explanation, no END line.

FLAG TESTS
{_flag_tests()}

WRITING
{_writing_rules()}

EVIDENCE
Quote, character for character, the passage of each unit the line rests on, without the [ID] prefix. For NONE,
quote the unit itself, so the case is checked against what it says."""
    return f"---\noutput_format: text\ncases: {cases}\n---\n{body}\n"


# --- accepted cases to gold lines --------------------------------------------------------


def _unit_id(text: str) -> str:
    return text.strip().strip("[]").strip()


def _parse(line: str, code: str, case_id: str, doc: TaggedDocument) -> tuple[list[str], str, list[str]] | str:
    """(ids, fact, model flags) of one output line, or the reason it is not a gold line."""
    parts = line.split("|")
    if len(parts) > 4:
        return "the fact contains the | character"
    if len(parts) < 3:
        return "not in the form CODE|fact|IDs|flags"
    if parts[0].strip().upper() != code:
        return f"code {parts[0].strip()!r} is not the prompt's code {code}"
    fact = parts[1].strip()
    if not fact:
        return "the fact text is empty"
    ids = [_unit_id(i) for i in parts[2].split(",") if _unit_id(i)]
    if not ids:
        return "no IDs"
    unknown = [i for i in ids if i not in doc.anchors]
    if unknown:
        return f"ID not in the document: {', '.join(unknown)}"
    if case_id in doc.anchors and ids[0] != case_id:
        return f"the main ID {ids[0]} is not the case's unit {case_id}"
    given = [f.strip().lower() for f in (parts[3] if len(parts) > 3 else "").split(",")]
    return ids, fact, [f for f in MODEL_FLAGS if f in given]


def to_gold(records: list[dict], doc: TaggedDocument, codes: str = CODES) -> tuple[list[str], list[dict]]:
    """Gold lines from golden records (accepted cases), and the lines that were refused, each with its reason.

    A line is refused when its code is not the prompt's, its IDs are missing or not in the document,
    its main ID is not the case's unit, or its fact is empty or holds a `|`. Model flags other than
    risk, unclear and post-award are dropped; mandatory and desirable come from the main unit's text.
    One unit accepted under two codes becomes one line with alternates, the main code chosen by
    `prompts.PRECEDENCE`; that merge applies when each code has a single line for the unit, and
    otherwise the lines stay separate. Lines are in document order.
    """
    order = {i: n for n, i in enumerate(doc.anchors)}
    found: dict[str, dict[str, list[tuple[str, list[str], list[str]]]]] = {}  # main ID -> code -> lines
    rejected: list[dict] = []
    for rec in records:
        code = str(rec.get("prompt_id", "")).upper()
        for raw in str(rec.get("expected_output", "")).splitlines():
            line = raw.strip()
            if not line or line.upper() == "NONE":
                continue
            got = _parse(line, code, _unit_id(str(rec.get("case_input", ""))), doc) if code in codes else "category not requested"
            if isinstance(got, str):
                rejected.append({"id": rec.get("id", ""), "line": line, "reason": got})
                continue
            ids, fact, model_flags = got
            flags = modal_flags(code, doc.anchors[ids[0]].text) + model_flags
            found.setdefault(ids[0], {}).setdefault(code, []).append((fact, ids, flags))
    out: list[tuple[int, int, str]] = []
    for main, by_code in found.items():
        ranked = sorted(by_code, key=lambda c: prompts.PRECEDENCE.index(c) if c in prompts.PRECEDENCE else len(prompts.PRECEDENCE))
        if len(ranked) > 1 and all(len(v) == 1 for v in by_code.values()):
            ranked_lines = [by_code[c][0] for c in ranked]
            fact, ids, flags = ranked_lines[0]
            for _, more_ids, more_flags in ranked_lines[1:]:
                ids = ids + [i for i in more_ids if i not in ids]
                flags = flags + [f for f in more_flags if f not in flags]
            out.append((order[main], 0, f"{'/'.join(ranked)}|{fact}|{','.join(ids)}|{','.join(flags)}"))
            continue
        for rank, c in enumerate(ranked):
            for fact, ids, flags in by_code[c]:
                out.append((order[main], rank, f"{c}|{fact}|{','.join(ids)}|{','.join(flags)}"))
    return [line for _, _, line in sorted(out, key=lambda t: t[:2])], rejected


# --- the build -------------------------------------------------------------------------


def missing_dependency() -> str | None:
    """The first module goldset needs that is not installed (the `evals` extra), else None."""
    import importlib.util

    needed = ("goldset", "langgraph", "langchain", "langchain_openai", "pydantic", "yaml", "jmespath")
    return next((m for m in needed if importlib.util.find_spec(m) is None), None)


def budgeted(cfg, cases: int):
    """goldset's settings with the case budgets raised to fit `cases` per category.

    `cases` is each prompt's front-matter target, the number of accepted cases the run aims for.
    The cap on items (`max_items_large` once the source is cut into several chunks, else
    `max_items_per_task`) counts every item ever planned, dropped and failed ones too, and
    also limits what the reconciler may add. At the defaults (14 and 80) a small cap would
    cut the target; a cap equal to the target would leave no room to replace a dropped case.
    So both caps become at least `cases` plus half again (and at least 4). Everything else
    stays as the user's file has it.
    """
    cap = cases + max(4, cases // 2)
    cfg.dataset.max_items_per_task = max(cfg.dataset.max_items_per_task, cap)
    cfg.dataset.max_items_large = max(cfg.dataset.max_items_large, cap)
    return cfg


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_inputs(doc: TaggedDocument, out: Path, codes: str, cases: int) -> tuple[Path, Path]:
    """`input/sources/<doc>.md` and `input/prompts/<CODE>.md`; returns the two folders."""
    sources, prompt_dir = out / "input" / "sources", out / "input" / "prompts"
    for d in (sources, prompt_dir):
        d.mkdir(parents=True, exist_ok=True)
    for old in list(sources.glob("*")) + list(prompt_dir.glob("*")):
        old.unlink()
    (sources / f"{safe_name(doc.doc_id)}.md").write_text(source_text(doc), encoding="utf-8")
    for c in codes:
        (prompt_dir / f"{c}.md").write_text(prompt_text(c, cases), encoding="utf-8")
    return sources, prompt_dir


def build(
    pdf: str | None,
    out_dir: str | Path,
    codes: str = CODES,
    cases: int = DEFAULT_CASES,
    config_path: str | Path | None = None,
    brain=None,
    log: Callable[[str], None] = print,
    doc_id: str | None = None,
    doc: TaggedDocument | None = None,
) -> dict:
    """Tag the PDF (or take `doc`), run goldset, write `gold.txt` and `rejected.jsonl`, and say what came out.

    Re-running into the same folder replays goldset's cached model calls. `brain` is for tests.
    """
    from goldset.config import load_config
    from goldset.runner import run

    codes = "".join(dict.fromkeys(codes.upper()))
    bad = [c for c in codes if c not in CODES]
    if bad or not codes:
        raise ValueError(f"categories must be some of {CODES} (Q is not supported here); got {codes!r}")
    if doc is None:
        from .pdf import read_pdf

        assert pdf is not None, "give a PDF or a tagged document"
        doc = tag_pages(doc_id or Path(pdf).stem, read_pdf(pdf))
    out = Path(out_dir)
    sources, prompt_dir = write_inputs(doc, out, codes, cases)
    cfg = budgeted(load_config(Path(config_path) if config_path else None), cases)
    log(f"{doc.doc_id}: {len(doc.anchors)} units, categories {codes}, {cases} cases each")
    asyncio.run(run(sources, prompt_dir, out / "build", cfg, brain=brain, log=log))
    build_dir = out / "build"
    lines, rejected = to_gold(_read_jsonl(build_dir / "golden.jsonl"), doc, codes)
    (out / "gold.txt").write_text("".join(f"{ln}\n" for ln in lines), encoding="utf-8")
    (out / "rejected.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rejected), encoding="utf-8")
    cov = json.loads((build_dir / "coverage.json").read_text(encoding="utf-8")) if (build_dir / "coverage.json").exists() else {}
    by_code: dict[str, int] = {}
    for ln in lines:
        by_code[ln.split("|", 1)[0].split("/")[0]] = by_code.get(ln.split("|", 1)[0].split("/")[0], 0) + 1
    return {
        "accepted": len(lines),
        "by_code": dict(sorted(by_code.items())),
        "rejected": len(rejected),
        "needs_human": len(_read_jsonl(build_dir / "needs_human.jsonl")),
        "coverage": {k.split("@", 1)[0]: v["ratio"] for k, v in cov.items()},
        "gold": str(out / "gold.txt"),
        "rejected_file": str(out / "rejected.jsonl"),
        "report": str(build_dir / "report.md"),
    }

"""Plan calls (spec section 5): split the work, not the document."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import prompts
from .models import Anchor, CallSpec, TaggedDocument

# The spec's words, plus the words of proposal response items and desirable requirements.
_CANDIDATE = re.compile(
    r"\b(shall|must|will|required|mandatory|should|describe|provide|indicate|submit|include)\b", re.I
)
_COMPLIANCE_HEADER = re.compile(r"\b(requirement|compliance|comply|complies|mandatory|required|must|shall)\b", re.I)

# Contract terms get their own calls (K1, K2: one per half of the document) and buyer facts
# pair with evaluation (E); see REVIEW.md, "Bid manager tailoring". Contract output for a
# whole RFP fills a call's token budget on its own.
CATEGORY_CALLS = (("A", ("B", "E", "Q")), ("B", ("G", "X", "Q")), ("C", ("D", "S", "Q")))
PAGED_CATEGORY_CALLS = (("K", ("C", "Q"), 2),)


@dataclass(frozen=True)
class PlanConfig:
    candidates_per_range: int = 40
    keep_section_below: int = 60


def is_candidate(a: Anchor) -> bool:
    if a.kind == "heading":
        return False
    if a.kind == "table_row":
        # A row of a compliance table: the header names are written into the row text.
        header_names = " ".join(part.split(":", 1)[0] for part in a.text.split(" | "))
        if _COMPLIANCE_HEADER.search(header_names):
            return True
    return bool(_CANDIDATE.search(a.text))


def candidates(doc: TaggedDocument) -> list[str]:
    return [a.id for a in doc.anchors.values() if is_candidate(a)]


def sweepable(doc: TaggedDocument) -> list[str]:
    """Every unit that could hold a fact: candidates, plus any sentence, row or heading
    with at least three words (form blanks and page furniture are left out)."""
    out = []
    for a in doc.anchors.values():
        real_words = [w for w in a.text.split() if sum(c.isalnum() for c in w) >= 2]
        if is_candidate(a) or len(real_words) >= 3:
            out.append(a.id)
    return out


def requirement_ranges(doc: TaggedDocument, cfg: PlanConfig = PlanConfig()) -> list[tuple[int, int]]:
    """Group pages into ranges of about `candidates_per_range` candidates (spec 5.1, REVIEW.md item 7)."""
    per_page: dict[int, int] = {p: 0 for p in range(1, doc.page_count + 1)}
    first_section: dict[int, str] = {}
    for a in doc.anchors.values():
        if is_candidate(a):
            per_page[a.page] += 1
            first_section.setdefault(a.page, a.section)

    # Section blocks: runs of consecutive pages whose first candidate is in one section.
    # Pages with no candidates join the block before them.
    blocks: list[list[int]] = []
    current_section: str | None = None
    for p in sorted(per_page):
        sec = first_section.get(p)
        if blocks and (sec is None or sec == current_section):
            blocks[-1].append(p)
        else:
            blocks.append([p])
            current_section = sec if sec is not None else current_section

    ranges: list[list[int]] = []
    count = 0
    target = cfg.candidates_per_range
    for block in blocks:
        size = sum(per_page[p] for p in block)
        if size >= cfg.keep_section_below:
            # A big section may be split by page.
            for p in block:
                if ranges and count + per_page[p] <= target:
                    ranges[-1].append(p)
                    count += per_page[p]
                else:
                    ranges.append([p])
                    count = per_page[p]
            continue
        if ranges and count + size <= target:
            ranges[-1].extend(block)
            count += size
        elif ranges and count == 0:
            ranges[-1].extend(block)  # previous range only held empty pages
            count = size
        else:
            ranges.append(list(block))
            count = size
    return [(r[0], r[-1]) for r in ranges if r]


def plan_calls(doc: TaggedDocument, cfg: PlanConfig = PlanConfig()) -> list[CallSpec]:
    calls = [CallSpec(name, codes, prompts.category_task(name, codes)) for name, codes in CATEGORY_CALLS]
    for name, codes, parts in PAGED_CATEGORY_CALLS:
        for i, rng in enumerate(text_ranges(doc, parts), start=1):
            calls.append(CallSpec(f"{name}{i}", codes, prompts.category_task(f"{name}{i}", codes, rng), page_range=rng))
    for i, (start, end) in enumerate(requirement_ranges(doc, cfg), start=1):
        calls.append(
            CallSpec(f"R{i}", ("R", "Q"), prompts.requirements_task(start, end), page_range=(start, end))
        )
    return calls


def text_ranges(doc: TaggedDocument, parts: int) -> list[tuple[int, int]]:
    """Split the pages into `parts` ranges holding about the same amount of text."""
    per_page = [0] * (doc.page_count + 1)
    for a in doc.anchors.values():
        per_page[a.page] += len(a.text)
    total = sum(per_page)
    ranges: list[tuple[int, int]] = []
    start, acc = 1, 0
    for p in range(1, doc.page_count + 1):
        acc += per_page[p]
        if len(ranges) < parts - 1 and acc >= total * (len(ranges) + 1) / parts and p < doc.page_count:
            ranges.append((start, p))
            start = p + 1
    ranges.append((start, doc.page_count))
    return ranges


def _ranged(call: CallSpec, name: str, rng: tuple[int, int]) -> CallSpec:
    if call.codes == ("R", "Q"):
        task = prompts.requirements_task(*rng)
    else:
        task = prompts.category_task(name, call.codes, rng)
    return CallSpec(name, call.codes, task, page_range=rng)


def split_call(call: CallSpec, page_count: int | None = None) -> list[CallSpec]:
    """Smaller calls for a call whose output was cut (spec 11, REVIEW.md item 2)."""
    if call.page_range:
        start, end = call.page_range
        if start == end:
            return []
        mid = (start + end) // 2
        return [_ranged(call, f"{call.name}a", (start, mid)), _ranged(call, f"{call.name}b", (mid + 1, end))]
    if call.kind == "sweep":
        ids = list(call.sweep_ids)
        if len(ids) < 2:
            return []
        half = len(ids) // 2
        return [
            CallSpec(f"{call.name}{s}", call.codes, prompts.sweep_task(part), kind="sweep", sweep_ids=tuple(part))
            for s, part in (("a", ids[:half]), ("b", ids[half:]))
        ]
    base = tuple(c for c in call.codes if c != "Q")
    if call.kind != "extract":
        return []
    if len(base) == 1:
        # One category over the whole document: split it by pages.
        if not page_count or page_count < 2:
            return []
        return split_call(CallSpec(call.name, call.codes, call.task, page_range=(1, page_count)))
    return [CallSpec(f"{call.name}.{c}", (c, "Q"), prompts.category_task(f"{call.name}.{c}", (c, "Q"))) for c in base]


def sweep_calls(ids: list[str], chunk: int = 30) -> list[CallSpec]:
    """The sweep, chunked so no call writes more than ~2,000 tokens (REVIEW.md, sweep sizing)."""
    codes = ("B", "C", "G", "X", "D", "S", "E", "R", "Q")
    parts = [ids[i : i + chunk] for i in range(0, len(ids), chunk)]
    return [
        CallSpec(f"SWEEP{i}", codes, prompts.sweep_task(p), kind="sweep", sweep_ids=tuple(p))
        for i, p in enumerate(parts, start=1)
    ]

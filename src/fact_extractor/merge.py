"""Merge and check helpers (spec section 8): dedupe, coverage, conflict marking."""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from .models import Fact
from .normalize import values
from .prompts import PRECEDENCE

SAME_IDS_SIMILARITY = 0.6  # same code + same IDs (REVIEW.md item 1)
OVERLAP_SIMILARITY = 0.8  # same code + overlapping IDs
# Different codes + same main ID: two calls filed one statement under two codes. Only a
# plain restatement merges: each fact holds this share of the other's content words, and
# the kept one has all the numbers and dates of the dropped one. A looser rule (0.6, one
# way) also merged second views a bid manager wants, such as the due date as a D fact next
# to "late proposals are not opened" as X, and cost about 2 points of recall on both RFPs.
CROSS_CODE_COVERAGE = 0.8


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def similarity(a: str, b: str) -> float:
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    return SequenceMatcher(None, wa, wb).ratio()


_STOP = set(
    "a an the of to for and or in on by with at as be is are will shall must may any all its it this that "
    "from each per not no than into their there these those which who whom within".split()
)
CROSS_PASS_SIMILARITY = 0.5


def paraphrase_similarity(a: str, b: str) -> float:
    """Like `similarity`, but on content words and forgiving of reordering: two passes
    word the same fact differently ("Proposals due: X" vs "Submit proposals by X")."""
    wa = [w for w in words(a) if w not in _STOP]
    wb = [w for w in words(b) if w not in _STOP]
    if not wa or not wb:
        return 0.0
    overlap = len(set(wa) & set(wb)) / min(len(set(wa)), len(set(wb)))
    return max(SequenceMatcher(None, wa, wb).ratio(), overlap * 0.8)


_RANK = {"valid": 0, "conflict": 0, "needs_review": 1}


def _same_fact(other: Fact, f: Fact) -> bool:
    if other.category == f.category:
        same_ids = set(other.ids) == set(f.ids)
        sim = similarity(other.text, f.text)
        # Two Q lines on the same IDs report the same contradiction, however worded.
        same_q = same_ids and f.category == "Q"
        return same_q or (same_ids and sim >= SAME_IDS_SIMILARITY) or sim >= OVERLAP_SIMILARITY
    # One statement filed under two codes by two calls (REVIEW.md, "Run-to-run stability").
    # A Q line is about a disagreement, never the same fact as the statement it cites.
    if "Q" in (other.category, f.category):
        return False
    if other.ids[0] != f.ids[0]:
        return False
    keep, drop = sorted((other, f), key=lambda x: (_RANK[x.status], _precedence(x.category)))
    wk = {w for w in words(keep.text) if w not in _STOP}
    wd = {w for w in words(drop.text) if w not in _STOP}
    if not wd or not wk or len(wd & wk) / max(len(wd), len(wk)) < CROSS_CODE_COVERAGE:
        return False
    return values(drop.text) <= values(keep.text, generous=True)


def dedupe(facts: list[Fact]) -> list[Fact]:
    """Merge duplicates. Only facts that share an ID are compared: with the same code on
    wording, with different codes when they also have the same main (first) ID."""
    kept: list[Fact] = []
    by_id: dict[str, list[int]] = defaultdict(list)
    for f in facts:
        match: int | None = None
        seen: set[int] = set()
        for id_ in f.ids:
            for k in by_id[id_]:
                if k in seen:
                    continue
                seen.add(k)
                if _same_fact(kept[k], f):
                    match = k
                    break
            if match is not None:
                break
        if match is None:
            kept.append(f)
            for id_ in f.ids:
                by_id[id_].append(len(kept) - 1)
            continue
        merged = _merge(kept[match], f)
        kept[match] = merged
        for id_ in merged.ids:
            if match not in by_id[id_]:
                by_id[id_].append(match)
    return kept


def _precedence(code: str) -> int:
    return PRECEDENCE.index(code) if code in PRECEDENCE else len(PRECEDENCE)


def _merge(a: Fact, b: Fact) -> Fact:
    # A valid fact wins over a needs_review one; then the code that comes first in
    # PRECEDENCE (two codes for one statement); then the longer text.
    # (Stable sort: with the same status and code, the longer text; else the earlier fact.)
    first, second = sorted((a, b), key=lambda f: (_RANK[f.status], _precedence(f.category), -len(f.text)))
    ids = list(dict.fromkeys(first.ids + second.ids))
    notes = [n.strip() for f in (first, second) for n in f.note.split(",") if n.strip()]
    note = ", ".join(dict.fromkeys(notes))  # keep the flags of both
    sources = ",".join(dict.fromkeys(first.source_call.split(",") + second.source_call.split(",")))
    return Fact(first.category, first.text, ids, note, first.status, sources, first.problems, first.conflicts)


def union_passes(first: list[Fact], second: list[Fact]) -> list[Fact]:
    """Merge two extraction passes without losing facts.

    Each fact of the second pass merges with at most one fact of the first: the most
    similar one with the same code and a shared ID. Facts within one pass never merge
    here, so several requirements from one sentence all survive. Anything without a
    match is a fact the first pass missed, and is kept.
    """
    out = list(first)
    by_id: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, f in enumerate(first):
        for id_ in f.ids:
            by_id[(f.category, id_)].append(i)
    taken: set[int] = set()
    for f in second:
        cands = {i for id_ in f.ids for i in by_id[(f.category, id_)] if i not in taken}
        scored = [(paraphrase_similarity(f.text, first[i].text), i) for i in cands]
        score, best = max(scored, default=(0.0, -1))
        if best >= 0 and (score >= CROSS_PASS_SIMILARITY or f.category == "Q"):
            taken.add(best)
            out[best] = _merge(first[best], f)
        else:
            out.append(f)
    return out


def uncited(candidate_ids: list[str], facts: list[Fact]) -> list[str]:
    cited = {i for f in facts for i in f.ids}
    return [i for i in candidate_ids if i not in cited]

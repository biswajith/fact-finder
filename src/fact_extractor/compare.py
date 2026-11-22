"""Score extracted facts against a reference ("gold") list (spec section 13).

A gold fact counts as found when an extracted fact cites at least one of the
same IDs and says much the same thing. Facts are matched across categories
too, so a fact filed under the wrong code shows up as a category mismatch,
not as a miss.

Matching is one-to-one: each extracted fact can stand for at most one gold
fact, so a broad fact that lumps several requirements together cannot score
as all of them. Pairs are assigned greedily, best text match first.

The text score only measures shared wording, so "due August 31" still
matches "due August 28". Each matched pair is then given a value check
(`check_values`): the dates, times, amounts and counted durations in the gold
fact must also be in the extracted fact. A pair is `ok`, `wrong` (the extracted
fact gives a different value of the same kind) or `incomplete` (it leaves the
value out). Gold facts with no values get no verdict.

Two refinements keep granularity differences from counting as misses:
- A gold code may list alternates ("G/R"): the fact is filed under G but
  counts as found under the same code if extracted as R too.
- A gold fact left unpaired is credited as `combined` when an extracted fact
  already paired with another gold fact also states it: it shares an ID, holds
  at least COMBINED_COVERAGE of the gold fact's content words, and passes the
  value check. It counts as found; `combined` reports how many.

`judged` (from judge.py) overrides the wording score for close calls: a pair
judged "full" or "partial" may pair below MATCH_SIMILARITY, a pair judged "no"
never pairs, nor gets combined credit.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import re

from .models import FLAGS
from .normalize import _STOP, _WORDS, values, words

# "five working days", "three (3) years": number words count only before a unit,
# so "one original and one copy" style wording is not treated as a value
_WORD_COUNT = re.compile(
    r"\b(?P<w>" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")\b"
    r"(?:\s*\(\d+\))?\s+(?:working\s+|business\s+|calendar\s+|consecutive\s+)?"
    r"(?:day|week|month|year|hour|minute|point|percent)s?\b",
    re.I,
)

# Minimum text similarity for a match. Category and citation agreement only
# break ties between candidates; they never lift a weak text match over this.
MATCH_SIMILARITY = 0.4
COMBINED_COVERAGE = 0.6


def split_note(note: str) -> tuple[list[str], str]:
    """A note holds flags and sometimes free text; keep both apart."""
    flags: list[str] = []
    rest: list[str] = []
    for part in (p.strip() for p in note.split(",")):
        if part.lower() in FLAGS:
            if part.lower() not in flags:
                flags.append(part.lower())
        elif part:
            rest.append(part)
    return flags, ", ".join(rest)


def _content(text: str) -> list[str]:
    return [w for w in words(text) if w not in _STOP]


def coverage(gold: str, found: str) -> float:
    """Share of the gold fact's content words that `found` also uses."""
    wg = set(_content(gold))
    return len(wg & set(_content(found))) / len(wg) if wg else 0.0


def similarity(gold: str, found: str) -> float:
    """How well `found` restates `gold`, on content words.

    The word-overlap part is measured against the gold fact's words, so a short
    vague fact ("Proposals due by email") does not score high against a long
    specific one just because all of its few words appear there."""
    wg, wf = _content(gold), _content(found)
    if not wg or not wf:
        return 0.0
    coverage = len(set(wg) & set(wf)) / len(set(wg))
    return max(SequenceMatcher(None, wg, wf).ratio(), coverage * 0.9)


@dataclass
class Item:
    category: str
    text: str
    ids: list[str]
    flags: list[str]
    alt: list[str] = field(default_factory=list)  # other codes that also count as the same

    def same_code(self, other: "Item") -> bool:
        return other.category == self.category or other.category in self.alt


def _strict_values(text: str) -> set[str]:
    out = values(text)
    out.update(str(_WORDS[m.group("w").lower()]) for m in _WORD_COUNT.finditer(text))
    return out


def _kind(token: str) -> str:
    return token.split(":", 1)[0] if ":" in token else "number"


@dataclass
class ValueCheck:
    verdict: str  # "ok", "wrong" or "incomplete"
    missing: list[str]  # gold values not in the extracted fact
    conflicting: list[str]  # extracted values of the same kind that gold lacks


def check_values(gold: str, found: str) -> ValueCheck | None:
    """Compare the values (dates, times, numbers) of a matched pair.

    None when the gold fact states no values. The extracted fact is read
    generously ("3" and "three", a date also yields its year), so a correct
    value in other words still passes."""
    want = _strict_values(gold)
    if not want:
        return None
    have = values(found, generous=True) | _strict_values(found)
    missing = sorted(want - have)
    if not missing:
        return ValueCheck("ok", [], [])
    kinds = {_kind(t) for t in missing}
    conflicting = sorted(t for t in _strict_values(found) - want if _kind(t) in kinds)
    return ValueCheck("wrong" if conflicting else "incomplete", missing, conflicting)


@dataclass
class Match:
    gold: Item
    found: Item | None
    score: float
    values: ValueCheck | None = None
    combined: bool = False  # credited to an extracted fact paired with another gold fact
    judged: str | None = None  # LLM verdict on this pair ("full", "partial", "no"), if it was a close call


@dataclass
class Comparison:
    matches: list[Match]
    extras: list[Item]  # extracted facts that match no gold fact
    categories: list[str]
    # gold facts missed because the extracted fact that matched them was already
    # paired with another gold fact, and it does not state this one fully
    merged: list[Match] = field(default_factory=list)
    by_category: dict[str, dict] = field(default_factory=dict)


def read_lines(path: str) -> list[Item]:
    """Read CODE|fact|IDs|flags lines (the extractor's own output format)."""
    items = []
    with open(path) as f:
        for raw in f:
            parts = raw.rstrip("\n").split("|")
            if len(parts) < 3 or parts[0].strip().upper() in ("END", "NONE", ""):
                continue
            flags, _ = split_note(parts[3] if len(parts) > 3 else "")
            ids = [i.strip().strip("[]") for i in parts[2].split(",") if i.strip()]
            code, *alt = [c.strip() for c in parts[0].upper().split("/") if c.strip()]
            items.append(Item(code, parts[1].strip(), ids, flags, alt))
    return items


def from_records(records: list[dict]) -> list[Item]:
    return [
        Item(r["category"], r["text"], [c["id"] for c in r["citations"]] + r.get("unresolved_ids", []), r.get("flags", []))
        for r in records
    ]


def compare(gold: list[Item], found: list[Item], judged: dict[tuple[str, str], str] | None = None) -> Comparison:
    judged = judged or {}
    by_id: dict[str, list[int]] = defaultdict(list)
    for i, f in enumerate(found):
        for id_ in f.ids:
            by_id[id_].append(i)
    # every (gold, extracted) pair that shares an ID, with its text score and a
    # ranking key that prefers the same code, then the same first citation
    candidates: list[tuple[float, float, int, int]] = []
    best_text = [0.0] * len(gold)
    for gi, g in enumerate(gold):
        for fi in {i for id_ in g.ids for i in by_id[id_]}:
            f = found[fi]
            score = similarity(g.text, f.text)
            best_text[gi] = max(best_text[gi], score)
            verdict = judged.get((g.text, f.text))
            if verdict == "no" or (score < MATCH_SIMILARITY and verdict is None):
                continue
            rank = max(score, MATCH_SIMILARITY) + 0.05 * g.same_code(f) + 0.02 * bool(f.ids and g.ids and f.ids[0] == g.ids[0])
            candidates.append((rank, score, gi, fi))
    candidates.sort(key=lambda c: (-c[0], c[2], c[3]))

    pair: dict[int, tuple[int, float]] = {}  # gold index -> (found index, score)
    used: set[int] = set()
    blocked: set[int] = set()  # gold facts whose candidate was taken by another
    for _, score, gi, fi in candidates:
        if gi in pair:
            continue
        if fi in used:
            blocked.add(gi)
            continue
        pair[gi] = (fi, score)
        used.add(fi)

    matches: list[Match] = []
    merged: list[Match] = []
    for gi, g in enumerate(gold):
        if gi in pair:
            fi, score = pair[gi]
            matches.append(Match(g, found[fi], round(score, 2), check_values(g.text, found[fi].text),
                                 judged=judged.get((g.text, found[fi].text))))
            continue
        # does an already-paired extracted fact state this gold fact as well?
        best: tuple[float, int] | None = None
        for fi in {i for id_ in g.ids for i in by_id[id_]} & used:
            cov = coverage(g.text, found[fi].text)
            v = check_values(g.text, found[fi].text)
            if judged.get((g.text, found[fi].text)) == "no":
                continue
            if cov >= COMBINED_COVERAGE and (v is None or v.verdict == "ok"):
                key = (cov + 0.05 * g.same_code(found[fi]), -fi)
                if best is None or key > (best[0], -best[1]):
                    best = (key[0], fi)
        if best is not None:
            fi = best[1]
            matches.append(Match(g, found[fi], round(similarity(g.text, found[fi].text), 2),
                                 check_values(g.text, found[fi].text), combined=True))
            continue
        m = Match(g, None, round(best_text[gi], 2))
        matches.append(m)
        if gi in blocked:
            merged.append(m)
    cats = sorted({g.category for g in gold})
    extras = [f for i, f in enumerate(found) if i not in used and f.category in cats]
    cmp = Comparison(matches, extras, cats, merged=merged)
    for c in cats:
        ms = [m for m in matches if m.gold.category == c]
        same = sum(1 for m in ms if m.found and m.gold.same_code(m.found))
        other = sum(1 for m in ms if m.found and not m.gold.same_code(m.found))
        n_found = sum(1 for f in found if f.category == c)
        matched_found = len({id(m.found) for m in matches if m.found and m.found.category == c})
        verdicts = Counter(m.values.verdict for m in ms if m.found and m.values)
        exact = sum(1 for m in ms if m.found and (m.values is None or m.values.verdict == "ok"))
        cmp.by_category[c] = {
            "gold": len(ms),
            "extracted": n_found,
            "recall_same_code": round(same / len(ms), 3) if ms else None,
            "recall_any_code": round((same + other) / len(ms), 3) if ms else None,
            "found_under_other_code": other,
            "combined": sum(1 for m in ms if m.combined),
            # pairs the judge let match although their wording scored below the cutoff
            "judge_rescued": sum(1 for m in ms if m.found and m.judged and m.score < MATCH_SIMILARITY),
            "judge_partial": sum(1 for m in ms if m.found and m.judged == "partial"),
            "missed_merged": sum(1 for m in merged if m.gold.category == c),
            # found under any code with every gold value present
            "recall_values_ok": round(exact / len(ms), 3) if ms else None,
            "values_checked": sum(verdicts.values()),
            "values_wrong": verdicts["wrong"],
            "values_incomplete": verdicts["incomplete"],
            "extracted_matching_gold": round(matched_found / n_found, 3) if n_found else None,
        }
    return cmp


def flag_agreement(cmp: Comparison, flag: str) -> dict:
    pairs = [m for m in cmp.matches if m.found]
    tp = sum(1 for m in pairs if flag in m.gold.flags and flag in m.found.flags)  # type: ignore[union-attr]
    gold_n = sum(1 for m in pairs if flag in m.gold.flags)
    found_n = sum(1 for m in pairs if flag in m.found.flags)  # type: ignore[union-attr]
    return {"gold": gold_n, "extracted": found_n, "both": tp}


def confusion(cmp: Comparison) -> Counter:
    return Counter((m.gold.category, m.found.category) for m in cmp.matches if m.found and not m.gold.same_code(m.found))

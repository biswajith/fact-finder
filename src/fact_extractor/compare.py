"""Score extracted facts against a reference ("gold") list (spec section 13).

A gold fact counts as found when an extracted fact cites at least one of the
same IDs and says much the same thing. Facts are matched across categories
too, so a fact filed under the wrong code shows up as a category mismatch,
not as a miss.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .merge import paraphrase_similarity as similarity
from .store import split_note

MATCH_SIMILARITY = 0.3


@dataclass
class Item:
    category: str
    text: str
    ids: list[str]
    flags: list[str]


@dataclass
class Match:
    gold: Item
    found: Item | None
    score: float


@dataclass
class Comparison:
    matches: list[Match]
    extras: list[Item]  # extracted facts that match no gold fact
    categories: list[str]
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
            items.append(Item(parts[0].strip().upper(), parts[1].strip(), ids, flags))
    return items


def from_records(records: list[dict]) -> list[Item]:
    return [
        Item(r["category"], r["text"], [c["id"] for c in r["citations"]] + r.get("unresolved_ids", []), r.get("flags", []))
        for r in records
    ]


def compare(gold: list[Item], found: list[Item]) -> Comparison:
    by_id: dict[str, list[int]] = defaultdict(list)
    for i, f in enumerate(found):
        for id_ in f.ids:
            by_id[id_].append(i)
    used: set[int] = set()
    matches: list[Match] = []
    for g in gold:
        best, best_score = None, 0.0
        for i in {i for id_ in g.ids for i in by_id[id_]}:
            f = found[i]
            score = similarity(g.text, f.text)
            if f.category == g.category:
                score += 0.15
            if f.ids and g.ids and f.ids[0] == g.ids[0]:
                score += 0.1
            if score > best_score:
                best, best_score = i, score
        if best is not None and best_score >= MATCH_SIMILARITY:
            used.add(best)
            matches.append(Match(g, found[best], round(best_score, 2)))
        else:
            matches.append(Match(g, None, round(best_score, 2)))
    cats = sorted({g.category for g in gold})
    extras = [f for i, f in enumerate(found) if i not in used and f.category in cats]
    cmp = Comparison(matches, extras, cats)
    for c in cats:
        ms = [m for m in matches if m.gold.category == c]
        same = sum(1 for m in ms if m.found and m.found.category == c)
        other = sum(1 for m in ms if m.found and m.found.category != c)
        n_found = sum(1 for f in found if f.category == c)
        matched_found = len({id(m.found) for m in matches if m.found and m.found.category == c})
        cmp.by_category[c] = {
            "gold": len(ms),
            "extracted": n_found,
            "recall_same_code": round(same / len(ms), 3) if ms else None,
            "recall_any_code": round((same + other) / len(ms), 3) if ms else None,
            "found_under_other_code": other,
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
    return Counter((m.gold.category, m.found.category) for m in cmp.matches if m.found and m.found.category != m.gold.category)

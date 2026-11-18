"""Score a run against a reference list by source ID (REVIEW.md, "A fact is a labelled
source unit").

A reference fact is found when the run has a fact citing its main (first) ID, and found
under the right code when that fact has the reference code or one of its alternates.
No text matching and no judge: the same two files always give the same score. Works on
any facts JSON whose records cite unit IDs, so the earlier pipeline's runs score too.
"""

from __future__ import annotations

from collections import defaultdict

from .compare import Item
from .prompts import PRECEDENCE


def codes_by_id(records: list[dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for r in records:
        if r["category"] == "Q":
            continue
        for c in r["citations"]:
            out[c["id"]].add(r["category"])
            if r.get("also"):
                out[c["id"]].add(r["also"])
    return out


def score(gold: list[Item], records: list[dict]) -> dict:
    codes = codes_by_id(records)
    q_ids = {c["id"] for r in records if r["category"] == "Q" for c in r["citations"]}
    by_cat: dict[str, dict] = {}
    missed, wrong_code = [], []
    for g in gold:
        if not g.ids:
            continue
        row = by_cat.setdefault(g.category, {"gold": 0, "found": 0, "same_code": 0})
        row["gold"] += 1
        # A contradiction is found when a Q fact cites either side of it.
        got = ({"Q"} if set(g.ids) & q_ids else set()) if g.category == "Q" else codes.get(g.ids[0], set())
        if not got:
            missed.append({"category": g.category, "text": g.text, "id": g.ids[0]})
            continue
        row["found"] += 1
        if got & ({g.category} | set(g.alt)):
            row["same_code"] += 1
        else:
            first = min(got, key=lambda c: PRECEDENCE.index(c) if c in PRECEDENCE else len(PRECEDENCE))
            wrong_code.append({"category": g.category, "filed_as": first, "text": g.text, "id": g.ids[0]})
    total = sum(r["gold"] for r in by_cat.values())
    for r in by_cat.values():
        r["recall"] = round(r["found"] / r["gold"], 3)
        r["recall_same_code"] = round(r["same_code"] / r["gold"], 3)
    return {
        "gold": total,
        "recall": round(sum(r["found"] for r in by_cat.values()) / total, 3) if total else None,
        "recall_same_code": round(sum(r["same_code"] for r in by_cat.values()) / total, 3) if total else None,
        "units_used": len(codes),
        "by_category": dict(sorted(by_cat.items())),
        "missed": missed,
        "wrong_code": wrong_code,
    }

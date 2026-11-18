"""How far two runs on the same document agree (REVIEW.md, "Run-to-run stability").

The model never words a fact the same way twice, so runs are compared on what they
cite and how they file it, not on text:

- `id_agreement`: shared cited IDs over all cited IDs. Did both runs find the same
  source sentences?
- `code_agreement`: of the IDs both runs cite, the share filed under the same set of
  codes. Did both runs put those sentences in the same categories?
- `fact_id_agreement`: shared fact IDs over all fact IDs. What a consumer that keys
  on `fact_id` sees as unchanged.

All three are 1.0 for two identical runs. No model call.
"""

from __future__ import annotations

from collections import Counter, defaultdict


def _codes_by_id(records: list[dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for r in records:
        for c in r["citations"]:
            out[c["id"]].add(r["category"])
    return out


def _share(both: int, total: int) -> float | None:
    return round(both / total, 3) if total else None


def compare_runs(a: list[dict], b: list[dict]) -> dict:
    ca, cb = _codes_by_id(a), _codes_by_id(b)
    both = set(ca) & set(cb)
    same = [i for i in both if ca[i] == cb[i]]
    flips: Counter[tuple[str, str]] = Counter()
    for i in both:
        if ca[i] != cb[i]:
            flips[tuple(sorted(("".join(sorted(ca[i] - cb[i])), "".join(sorted(cb[i] - ca[i])))))] += 1  # type: ignore[index]
    fa, fb = {r["fact_id"] for r in a}, {r["fact_id"] for r in b}
    cats = sorted({r["category"] for r in a + b})
    return {
        "facts": [len(a), len(b)],
        "cited_ids": [len(ca), len(cb)],
        "cited_both": len(both),
        "id_agreement": _share(len(both), len(set(ca) | set(cb))),
        "same_codes": len(same),
        "code_agreement": _share(len(same), len(both)),
        "same_fact_id": len(fa & fb),
        "fact_id_agreement": _share(len(fa & fb), len(fa | fb)),
        "by_category": {
            c: {
                "a": sum(1 for r in a if r["category"] == c),
                "b": sum(1 for r in b if r["category"] == c),
                "ids_both": sum(1 for i in both if c in ca[i] and c in cb[i]),
            }
            for c in cats
        },
        # (codes only one run used for an ID, codes only the other used), most common first
        "code_flips": flips.most_common(),
    }

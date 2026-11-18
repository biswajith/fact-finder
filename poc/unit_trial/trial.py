"""Trial of the unit-labelling approach (REVIEW.md, "A fact is a labelled source unit").

The PDF is already cut into numbered units (sentences, list items, table rows, headings)
by code. Here the model writes no facts: for every unit it answers a closed question,
which category (or none) and which flags. Three votes per unit, majority wins.

    python poc/unit_trial/trial.py "<rfp.pdf>" <gold file> [<gold file> ...]

Runs the whole thing twice (A and B) to measure how far two voted results agree, scores
recall against the reference list by source ID, and writes labels_A.json / labels_B.json
and result.json next to this file. Spends tokens: 2 x 3 labelling passes over the document.
"""

from __future__ import annotations

import asyncio
import collections
import json
import sys
import time
from pathlib import Path

from fact_extractor import compare as cm
from fact_extractor import prompts
from fact_extractor.cli import load_env
from fact_extractor.llm import OpenAIClient, Request
from fact_extractor.pdf import read_pdf
from fact_extractor.tagging import tag_pages

HERE = Path(__file__).parent
CODES = ("B", "C", "G", "X", "D", "S", "E", "R")
PREC = prompts.PRECEDENCE
FLAGS = ("mandatory", "desirable", "post-award", "risk", "unclear")
UNITS_PER_CALL = 60
VOTES = 3
PARALLEL = 32

SYSTEM = f"""You label an RFP for a bid manager, unit by unit.

THE READER
The bid manager uses the labelled units at three moments:
- Deciding whether to bid: can we qualify, can we win, what will it cost, what risk do we take on.
- Writing and submitting the proposal: what it must contain and answer, in what form, by when, and how it is scored.
- After winning: what the contract obliges the winner to do.
The bid manager reads the labelled units instead of the whole RFP, and must not miss a deadline, a mandatory item, or a risky contract term.

INPUT
The user sends the RFP as tagged text. Each line is one unit and starts with its ID in brackets, for example [p12.4]. A second message lists the IDs to label.

OUTPUT
Write exactly one line for every ID you are given, in the order given:
ID|LABEL|flags
After the last one write: END|number of lines
Write nothing else.

LABEL is one of:
- a category code, when the unit states a point the bid team must know, do, or decide;
- = when the unit only continues, qualifies, or repeats the point of a unit shortly before it, so it belongs with that unit;
- - when the unit gives the bid team nothing to know, do, or decide (most headings, tables of contents, page furniture, courtesy text, form blanks).
A unit that makes two separate points of two categories gets both codes joined by +, the main one first, for example X+D. This is rare.

CATEGORIES
{chr(10).join(prompts.DEFINITIONS[c] for c in CODES)}
When a point fits more than one code, use the first that fits in this order: {", ".join(PREC)}.

FLAGS
Empty, or a comma-separated list. Decide each flag for each unit on its own. Units labelled = or - carry no flags.
- mandatory: the RFP makes it binding (shall, must, required, will).
- desirable: the RFP prefers it but does not require it (should, may, preferred, desired, optional).
- post-award: only the winner is bound by it. Test: would a bidder who does not win ever have to do, hold, or respect this? If not, it is post-award. Whatever the proposal must contain, answer, or price, and whatever the bidder must be or have by the deadline, is not post-award, even when it is about work the winner will do later.
- risk: the term shifts cost, liability, or control onto the bidder in a way the bid team must price or decide to accept.
- unclear: the bid team cannot act on it without asking the buyer, because the RFP is vague, incomplete, or out of date on the point.

Judge every unit by the same standard, whatever the units around it got."""


def task(ids: list[str]) -> str:
    return (
        f"TASK LABEL\nLabel these {len(ids)} units, one line each, in this order:\n" + ", ".join(ids)
        + "\nRead each unit with the units around it before you label it."
    )


def chunks(doc) -> list[list[str]]:
    """Whole pages, in order, about UNITS_PER_CALL units per call."""
    out: list[list[str]] = [[]]
    page = None
    for a in doc.anchors.values():
        if a.page != page and len(out[-1]) >= UNITS_PER_CALL:
            out.append([])
        page = a.page
        out[-1].append(a.id)
    return [c for c in out if c]


def parse(text: str, ids: list[str]) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """ID -> (codes, flags). codes is ("=",), ("-",) or one or two category codes."""
    want = set(ids)
    out = {}
    for line in text.splitlines():
        p = [x.strip() for x in line.split("|")]
        if len(p) < 2 or p[0].strip("[]") not in want:
            continue
        label = p[1].upper()
        codes = tuple(c for c in label.replace(" ", "").split("+") if c)
        if not codes or not all(c in CODES or c in ("=", "-") for c in codes) or (len(codes) > 1 and set(codes) & {"=", "-"}):
            continue
        flags = tuple(sorted(f for f in (x.strip().lower() for x in (p[2] if len(p) > 2 else "").split(",")) if f in FLAGS))
        out[p[0].strip("[]")] = (codes, flags if codes[0] in CODES else ())
    return out


async def label_pass(client, doc, parts, sem, stats) -> dict:
    async def one(ids):
        async with sem:
            t = time.monotonic()
            resp = await client.complete(
                Request(SYSTEM, doc.tagged_text, task(ids), "low", 4000, "unit-trial-" + doc.doc_id), lambda _: None
            )
            stats["calls"] += 1
            stats["out"] += resp.usage.output_tokens
            stats["in"] += resp.usage.input_tokens
            stats["cached"] += resp.usage.cached_tokens
            stats["slowest"] = max(stats["slowest"], time.monotonic() - t)
            stats["truncated"] += resp.truncated
        return parse(resp.text, ids)

    got = await asyncio.gather(*(one(ids) for ids in parts))
    return {k: v for g in got for k, v in g.items()}


def vote(passes: list[dict], units: list[str]) -> dict:
    """Majority per unit on the main label; flags by majority among the votes for that label."""
    out = {}
    for u in units:
        votes = [p.get(u) for p in passes]
        mains = [v[0][0] if v else "?" for v in votes]
        count = collections.Counter(mains).most_common()
        top = [m for m, n in count if n == count[0][1]]
        # No majority: keep the unit rather than drop it, under the code that comes first.
        main = min(top, key=lambda m: PREC.index(m) if m in PREC else len(PREC) + "=-?".index(m))
        same = [v for v in votes if v and v[0][0] == main]
        second = collections.Counter(v[0][1] for v in same if len(v[0]) > 1).most_common(1)
        flags = sorted(f for f in FLAGS if sum(f in v[1] for v in same) * 2 > len(same))
        out[u] = {
            "label": main, "second": second[0][0] if second and second[0][1] * 2 > len(same) else None,
            "flags": flags, "votes": mains, "unanimous": len(set(mains)) == 1,
        }
    return out


def resolve(labels: dict, units: list[str]) -> dict[str, str]:
    """Final code per unit. '=' takes the code of the nearest earlier coded unit when that
    unit is at most 3 units back (a continuation is local); otherwise, and for '-' and
    '?', the unit has no code."""
    out: dict[str, str] = {}
    last, at = "-", -10
    for n, u in enumerate(units):
        lab = labels[u]["label"]
        if lab in CODES:
            last, at = lab, n
            out[u] = lab
        elif lab == "=" and n - at <= 3:
            out[u] = last
            at = n  # a run of continuations stays attached
        else:
            out[u] = "-"
    return out


def agreement(a: dict[str, str], b: dict[str, str], units) -> dict:
    return {
        "used": round(sum((a[u] != "-") == (b[u] != "-") for u in units) / len(units), 3),
        "code": round(sum(a[u] == b[u] for u in units) / len(units), 3),
        "differ": sum(a[u] != b[u] for u in units),
    }


def recall(final: dict[str, str], gold) -> dict:
    main = [(g, g.ids[0]) for g in gold if g.ids and g.ids[0] in final]
    found = [(g, i) for g, i in main if final[i] != "-"]
    any_id = sum(1 for g in gold if any(final.get(i, "-") != "-" for i in g.ids))
    same = sum(1 for g, i in found if final[i] == g.category or final[i] in g.alt)
    return {
        "gold": len(gold), "main_id_labelled": round(len(found) / len(main), 3),
        "any_cited_id_labelled": round(any_id / len(gold), 3), "same_code": round(same / len(main), 3),
        "missed": [f"{g.category} {g.text} [{i}]" for g, i in main if final[i] == "-"],
    }


async def main(pdf: str, gold_paths: list[str]) -> None:
    load_env()
    doc = tag_pages(Path(pdf).stem, read_pdf(pdf))
    units = list(doc.anchors)
    parts = chunks(doc)
    gold = [g for p in gold_paths for g in cm.read_lines(p)]
    client = OpenAIClient()
    sem = asyncio.Semaphore(PARALLEL)
    result: dict = {"pdf": pdf, "units": len(units), "calls_per_pass": len(parts), "votes": VOTES}
    finals, singles = {}, []
    for name in ("A", "B"):
        stats = collections.Counter()
        stats["slowest"] = 0.0
        t0 = time.monotonic()
        passes = await asyncio.gather(*(label_pass(client, doc, parts, sem, stats) for _ in range(VOTES)))
        seconds = time.monotonic() - t0
        voted = vote(passes, units)
        finals[name] = resolve(voted, units)
        singles += [resolve(vote([p], units), units) for p in passes]
        (HERE / f"labels_{name}.json").write_text(json.dumps(
            [{"id": u, "final": finals[name][u], **voted[u], "text": doc.anchors[u].text} for u in units], indent=1))
        result[name] = {
            "seconds": round(seconds, 1), "calls": stats["calls"], "output_tokens": stats["out"],
            "input_tokens": stats["in"], "cached_input_tokens": stats["cached"],
            "slowest_call_seconds": round(stats["slowest"], 1), "truncated_calls": stats["truncated"],
            "unanswered_units": sum(v == "?" for x in voted.values() for v in x["votes"]),
            "labelled": sum(v != "-" for v in finals[name].values()),
            "by_code": dict(sorted(collections.Counter(v for v in finals[name].values() if v != "-").items())),
            "continuations": sum(x["label"] == "=" for x in voted.values()),
            "not_unanimous": sum(not x["unanimous"] for x in voted.values()),
            "recall": recall(finals[name], gold),
        }
    result["voted_A_vs_voted_B"] = agreement(finals["A"], finals["B"], units)
    pairs = [(i, j) for i in range(len(singles)) for j in range(i + 1, len(singles))]
    result["single_vs_single"] = {
        k: round(sum(agreement(singles[i], singles[j], units)[k] for i, j in pairs) / len(pairs), 3) for k in ("used", "code")
    }
    result["single_recall_main_id"] = [recall(s, gold)["main_id_labelled"] for s in singles]
    (HERE / "result.json").write_text(json.dumps(result, indent=1))
    for name in ("A", "B"):
        r = dict(result[name]); rec = dict(r.pop("recall")); missed = rec.pop("missed")
        print(name, json.dumps(r)); print("  recall", json.dumps(rec)); print("  missed:", *missed[:12], sep="\n    ")
    print("voted A vs voted B:", result["voted_A_vs_voted_B"])
    print("single vs single:", result["single_vs_single"], "single recall:", result["single_recall_main_id"])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2:]))

"""LLM judge for close calls in `compare` (REVIEW.md, 2026-11-14).

Word overlap cannot tell a paraphrase from a different fact near the cutoff:
"State on the CGL policy that insurance is primary and non-contributory"
scores 0.39 against a fact that says just that. The judge looks only at pairs
near the cutoff:

- a gold fact left unmatched, with an extracted fact on the same IDs scoring
  JUDGE_LOW up to the match cutoff (its best JUDGE_PER_GOLD candidates), and
- a matched pair scoring below JUDGE_HIGH.

The judge answers `full` (the extracted fact says what the gold fact says),
`partial` (the main point is there, a detail is missing) or `no` (another fact,
or a different value). `full` and `partial` let a pair below the cutoff match;
`no` removes a pair from matching. Partial matches count as found and are
reported apart, like incomplete values. Scoring then runs again, and any new close pair that brings up is
judged too. Verdicts are cached by the two texts, so reruns are free and give
the same score.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass

from .compare import MATCH_SIMILARITY, Comparison, Item, compare, similarity
from .llm import LLMClient, Request

JUDGE_LOW = 0.2
JUDGE_HIGH = 0.5
JUDGE_PER_GOLD = 3
BATCH = 25
VERDICTS = ("full", "partial", "no")
MAX_ROUNDS = 3

SYSTEM = """You check an RFP fact extractor against a reference list written by a reviewer.
The reader is a bid manager who uses the extracted facts instead of reading the RFP.

For each numbered pair you get a REFERENCE fact and an EXTRACTED fact, both taken
from the same passage of the RFP. Decide what a bid manager reading only the
EXTRACTED fact would know about the REFERENCE fact. The extracted fact may say
more, word it differently, or file it under a different heading; that is fine.

full    - it states everything the reference fact states.
partial - it states the main point of the reference fact (the same obligation,
          right, deadline or piece of information) but leaves out a detail, or
          covers only some items of a reference fact that lists several.
no      - it is about something else, or it gives a different value (date, time,
          amount, count, who must act, who decides) for the same point.

Judge every pair by the same standard. Reply with one line per pair and nothing else:
N|full|short reason
N|partial|what is missing
N|no|short reason"""


@dataclass
class Verdict:
    gold: str
    found: str
    verdict: str  # "full", "partial" or "no"
    reason: str


def _key(gold: str, found: str) -> str:
    return json.dumps([gold, found])


class VerdictCache:
    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self.items: dict[str, Verdict] = {}
        if path and os.path.exists(path):
            with open(path) as f:
                for v in json.load(f):
                    if v.get("verdict") in VERDICTS:  # skip entries from an older format
                        self.items[_key(v["gold"], v["found"])] = Verdict(**v)

    def get(self, gold: str, found: str) -> Verdict | None:
        return self.items.get(_key(gold, found))

    def add(self, v: Verdict) -> None:
        self.items[_key(v.gold, v.found)] = v

    def save(self) -> None:
        if self.path:
            with open(self.path, "w") as f:
                json.dump([v.__dict__ for v in self.items.values()], f, indent=1)

    def verdicts(self) -> dict[tuple[str, str], str]:
        return {(v.gold, v.found): v.verdict for v in self.items.values()}


def close_calls(cmp: Comparison, found: list[Item]) -> list[tuple[str, str]]:
    """Pairs near the cutoff, as (gold text, extracted text)."""
    by_id: dict[str, list[int]] = defaultdict(list)
    for i, f in enumerate(found):
        for id_ in f.ids:
            by_id[id_].append(i)
    out: list[tuple[str, str]] = []
    for m in cmp.matches:
        if m.found is not None:
            if not m.combined and m.score < JUDGE_HIGH:
                out.append((m.gold.text, m.found.text))
            continue
        scored = sorted(
            ((similarity(m.gold.text, found[i].text), found[i].text) for i in {i for d in m.gold.ids for i in by_id[d]}),
            reverse=True,
        )
        out += [(m.gold.text, t) for s, t in scored if JUDGE_LOW <= s < MATCH_SIMILARITY][:JUDGE_PER_GOLD]
    return list(dict.fromkeys(out))


_LINE = re.compile(r"^\s*(\d+)\s*\|\s*(full|partial|no)\s*(?:\|(.*))?$", re.I)


def parse(text: str, n: int) -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m and 1 <= int(m.group(1)) <= n:
            out[int(m.group(1))] = (m.group(2).lower(), (m.group(3) or "").strip())
    return out


def _task(pairs: list[tuple[str, str]]) -> str:
    lines = [f"{i}. REFERENCE: {g}\n   EXTRACTED: {f}" for i, (g, f) in enumerate(pairs, 1)]
    return "Pairs:\n\n" + "\n\n".join(lines)


async def judge_pairs(pairs: list[tuple[str, str]], client: LLMClient, parallel: int = 4) -> list[Verdict]:
    """Ask the model about each pair. Pairs it gives no answer for are left out."""
    sem = asyncio.Semaphore(parallel)

    async def one(batch: list[tuple[str, str]]) -> list[Verdict]:
        async with sem:
            resp = await client.complete(
                Request(system=SYSTEM, document="", task=_task(batch), effort="low", max_output_tokens=4000),
                lambda _: None,
            )
        got = parse(resp.text, len(batch))
        return [Verdict(g, f, *got[i]) for i, (g, f) in enumerate(batch, 1) if i in got]

    batches = [pairs[i : i + BATCH] for i in range(0, len(pairs), BATCH)]
    results = await asyncio.gather(*(one(b) for b in batches))
    return [v for r in results for v in r]


@dataclass
class JudgeRun:
    comparison: Comparison
    asked: int  # pairs sent to the model this run
    cached: int  # close pairs answered from the cache
    unanswered: int  # pairs the model gave no verdict for (scored on wording)


async def compare_with_judge(gold: list[Item], found: list[Item], client: LLMClient, cache: VerdictCache) -> JudgeRun:
    asked = 0
    seen: set[tuple[str, str]] = set()
    unanswered: set[tuple[str, str]] = set()
    cmp = compare(gold, found, judged=cache.verdicts())
    for _ in range(MAX_ROUNDS):
        pairs = [p for p in close_calls(cmp, found) if p not in seen]
        seen.update(pairs)
        todo = [p for p in pairs if cache.get(*p) is None]
        if not todo:
            break
        verdicts = await judge_pairs(todo, client)
        asked += len(todo)
        for v in verdicts:
            cache.add(v)
        unanswered |= set(todo) - {(v.gold, v.found) for v in verdicts}
        cache.save()
        cmp = compare(gold, found, judged=cache.verdicts())
    return JudgeRun(cmp, asked, len(seen) - asked, len(unanswered))

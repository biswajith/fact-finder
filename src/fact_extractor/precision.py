"""Precision: how many extracted facts are right and worth a bid manager's time.

`compare` measures recall against a reference list; it never says whether the
other facts are correct or just noise. This module adds three things:

- `sample`: a random sample of facts with their cited source text, written as a
  CSV for a person to label (columns `supported` and `useful`).
- `score_labels`: precision from a labelled CSV, per category.
- `grade`: the same two questions asked of the model for every fact, so runs
  can be compared without labelling each one. Check it against a labelled
  sample (`agreement`) before trusting it. Grades are cached by fact text and
  cited text, so regrading a run, or another run with the same facts, is free.

`duplicates` counts near-duplicate pairs in code (same code, a shared ID,
similar wording): facts that cost reading time but add nothing.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from .compare import similarity
from .llm import LLMClient, Request

SUPPORTED = ("yes", "partly", "no")
USEFUL = ("useful", "noise")
BATCH = 20
DUPLICATE_SIMILARITY = 0.6  # rough: catches restatements, also some sibling facts

SYSTEM = """You check facts extracted from an RFP for a bid manager. The bid manager decides whether to bid, plans the response, builds the compliance matrix and submission checklist, and must not miss a deadline, a mandatory item, a scoring rule or a risky contract term.

Each numbered item gives a FACT with its category and the SOURCE text it cites (with the section heading).
Answer two questions per item, from the SOURCE text only:

supported:
yes    - the source states it; every date, amount, count, name and who-does-what is right.
partly - the main point is right but it drops a condition or qualifier that matters, or overstates it (for example "must" where the source says "may").
no     - the source does not say it, or a value or the party is wrong.

useful:
useful - a bid manager would want this line: something to know, do, decide, price, check or ask about.
noise  - boilerplate, a heading or table-of-contents entry, or so vague it gives nothing to act on.

Reply with one line per item and nothing else:
N|yes|useful|short reason
N|partly|noise|short reason"""

_LINE = re.compile(r"^\s*(\d+)\s*\|\s*(yes|partly|no)\s*\|\s*(useful|noise)\s*(?:\|(.*))?$", re.I)


@dataclass
class Grade:
    supported: str
    useful: str
    reason: str = ""


def cited_text(record: dict) -> str:
    parts = []
    for c in record.get("citations", []):
        section = f" ({c['section']})" if c.get("section") else ""
        parts.append(f"[{c['id']}]{section} {c['text']}")
    return "\n".join(parts) or "(no resolvable citation)"


def _key(record: dict) -> str:
    return json.dumps([record["category"], record["text"], [c["id"] for c in record.get("citations", [])]])


# --- human labels ------------------------------------------------------------

FIELDS = ["fact_id", "category", "flags", "text", "cited", "supported", "useful", "comment"]


def sample(records: list[dict], n: int, seed: int = 1) -> list[dict]:
    """A random sample, stratified so every category with facts gets at least two rows."""
    rng = random.Random(seed)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_cat[r["category"]].append(r)
    picked: list[dict] = []
    for rs in by_cat.values():
        picked += rng.sample(rs, min(2, len(rs)))
    rest = [r for r in records if r not in picked]
    picked += rng.sample(rest, max(0, min(n - len(picked), len(rest))))
    rng.shuffle(picked)
    return picked


def write_sample(records: list[dict], path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for r in records:
            w.writerow({
                "fact_id": r["fact_id"], "category": r["category"], "flags": ",".join(r.get("flags", [])),
                "text": r["text"], "cited": cited_text(r), "supported": "", "useful": "", "comment": "",
            })


def read_labels(path: str) -> list[dict]:
    """Labelled rows only. Accepts y/p/n and u/x as shorthand."""
    short = {"y": "yes", "p": "partly", "n": "no", "u": "useful", "x": "noise"}
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            s = short.get(row["supported"].strip().lower(), row["supported"].strip().lower())
            u = short.get(row["useful"].strip().lower(), row["useful"].strip().lower())
            if s in SUPPORTED and u in USEFUL:
                rows.append({**row, "supported": s, "useful": u})
    return rows


# --- scoring -----------------------------------------------------------------


def score(items: list[tuple[str, Grade]]) -> dict:
    """items: (category, grade). Rates per category and overall."""
    by_cat: dict[str, list[Grade]] = defaultdict(list)
    for cat, g in items:
        by_cat[cat].append(g)
        by_cat["all"].append(g)

    def rates(gs: list[Grade]) -> dict:
        n = len(gs)
        c = Counter(g.supported for g in gs)
        good = sum(1 for g in gs if g.supported == "yes" and g.useful == "useful")
        return {
            "n": n,
            "supported": round(c["yes"] / n, 3),
            "partly": round(c["partly"] / n, 3),
            "unsupported": round(c["no"] / n, 3),
            "noise": round(sum(1 for g in gs if g.useful == "noise") / n, 3),
            "precision": round(good / n, 3),  # supported and useful
        }

    return {cat: rates(gs) for cat, gs in sorted(by_cat.items(), key=lambda kv: (kv[0] == "all", kv[0]))}


def score_labels(rows: list[dict]) -> dict:
    return score([(r["category"], Grade(r["supported"], r["useful"])) for r in rows])


def duplicates(records: list[dict]) -> dict:
    """Near-duplicate pairs: same code, a shared ID, wording similarity >= DUPLICATE_SIMILARITY."""
    by_id: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        for c in r.get("citations", []):
            by_id[(r["category"], c["id"])].append(i)
    pairs: set[tuple[int, int]] = set()
    for idx in by_id.values():
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                i, j = idx[a], idx[b]
                a_, b_ = records[i]["text"], records[j]["text"]
                if (i, j) not in pairs and min(similarity(a_, b_), similarity(b_, a_)) >= DUPLICATE_SIMILARITY:
                    pairs.add((i, j))
    involved = {i for p in pairs for i in p}
    return {"pairs": len(pairs), "facts_involved": len(involved), "examples": [
        [records[i]["text"], records[j]["text"]] for i, j in sorted(pairs)[:5]
    ]}


# --- model grader --------------------------------------------------------------


class GradeCache:
    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self.items: dict[str, Grade] = {}
        if path and os.path.exists(path):
            with open(path) as f:
                self.items = {k: Grade(**v) for k, v in json.load(f).items()}

    def save(self) -> None:
        if self.path:
            with open(self.path, "w") as f:
                json.dump({k: v.__dict__ for k, v in self.items.items()}, f, indent=1)


def parse(text: str, n: int) -> dict[int, Grade]:
    out: dict[int, Grade] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m and 1 <= int(m.group(1)) <= n:
            out[int(m.group(1))] = Grade(m.group(2).lower(), m.group(3).lower(), (m.group(4) or "").strip())
    return out


def _task(batch: list[dict]) -> str:
    items = []
    for i, r in enumerate(batch, 1):
        source = cited_text(r).replace("\n", "\n   ")
        items.append(f"{i}. FACT ({r['category']}): {r['text']}\n   SOURCE:\n   {source}")
    return "Items:\n\n" + "\n\n".join(items)


async def grade(records: list[dict], client: LLMClient, cache: GradeCache, parallel: int = 8) -> tuple[list[Grade | None], int]:
    """A grade per record (None where the model gave none) and the number of facts sent to the model."""
    todo: dict[str, dict] = {}
    for r in records:
        k = _key(r)
        if k not in cache.items:
            todo.setdefault(k, r)
    sem = asyncio.Semaphore(parallel)

    async def one(batch: list[dict]) -> None:
        async with sem:
            resp = await client.complete(
                Request(system=SYSTEM, document="", task=_task(batch), effort="low", max_output_tokens=4000),
                lambda _: None,
            )
        for i, g in parse(resp.text, len(batch)).items():
            cache.items[_key(batch[i - 1])] = g

    pending = list(todo.values())
    await asyncio.gather(*(one(pending[i : i + BATCH]) for i in range(0, len(pending), BATCH)))
    cache.save()
    return [cache.items.get(_key(r)) for r in records], len(pending)


def agreement(rows: list[dict], records: list[dict], cache: GradeCache) -> dict:
    """How often the model grade matches a person's label, on the labelled facts."""
    by_fid = {r["fact_id"]: r for r in records}
    n = same_s = same_u = 0
    for row in rows:
        rec = by_fid.get(row["fact_id"])
        g = cache.items.get(_key(rec)) if rec else None
        if g is None:
            continue
        n += 1
        same_s += g.supported == row["supported"]
        same_u += g.useful == row["useful"]
    return {"n": n, "supported_agree": round(same_s / n, 3) if n else None, "useful_agree": round(same_u / n, 3) if n else None}

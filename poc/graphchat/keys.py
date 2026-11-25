"""Give the facts of a stored bid their keys, with the same LABEL call a new extraction uses.

    uv run python -m poc.graphchat.keys            # runs/_bids/durham -> poc/graphchat/out/durham.keys.json

A new extraction writes `key` and `value` on each fact (units.py: LABEL gives every unit that states a
value a `thing.attribute=value`, voted like the label). Durham was extracted before that, and extracting
it again would change its labels and break the chat eval that is written against it. So this runs only
the LABEL calls again, over each stored document as it was cut, and keeps from them the keys alone: the
stored label of every unit stays. It also says how often the new labels agree with the stored ones, to
show whether asking for a key in the same call changes the labelling.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from fact_extractor import playbooks, results, units
from fact_extractor.cli import load_env
from fact_extractor.llm import OpenAIClient
from fact_extractor.web import pricing

ROOT = Path(__file__).resolve().parents[2]
KEYS = True  # --no-keys asks for labels alone: the baseline for how much labels move between two runs
OUT = Path(__file__).resolve().parent / "out"


async def key_document(d: dict, client: OpenAIClient, votes: int, known: dict[str, str]) -> dict:
    pb = playbooks.load(d["playbook"])
    folder = ROOT / "runs" / d["run"]
    doc = results.load_document(folder, d["doc_id"])
    stored = {r["id"]: r for r in json.loads((folder / "labels.json").read_text())}
    cfg = units.Config(votes=votes)
    run = units._Run(doc, client, cfg, pb)
    parts = units.chunks(doc, cfg.units_per_label_call)
    labels: list[dict] = [{} for _ in range(votes)]
    keys: list[dict] = [{} for _ in range(votes)]
    t0 = time.monotonic()

    async def label(v: int, k: int, ids: list[str], started: asyncio.Event | None = None) -> None:
        text = await run.call(f"LABEL{k}#{v}", "label", units.label_task(ids, pb, KEYS, known), cfg.label_max_output_tokens,
                              started=started, covered=lambda t: len(units.parse_labels(t, ids, pb)), expected=len(ids))
        labels[v - 1].update(units.parse_labels(text, ids, pb))
        keys[v - 1].update(units.parse_keys(text, ids))

    started = asyncio.Event()
    first = asyncio.create_task(label(1, 1, parts[0], started))
    try:
        await asyncio.wait_for(started.wait(), cfg.warmup_timeout)
    except asyncio.TimeoutError:
        pass
    await asyncio.gather(first, *(label(v, k, ids) for v in range(1, votes + 1)
                                  for k, ids in enumerate(parts, start=1) if (v, k) != (1, 1)))
    seconds = time.monotonic() - t0
    new = units.vote(labels, list(doc.anchors), pb, keys)
    coded = [u for u in doc.anchors if stored[u]["label"] in pb.codes]
    usage = {"input": 0, "cached": 0, "output": 0, "usd": 0.0}
    for c in run.calls:
        usage["input"] += c.usage.input_tokens or 0
        usage["cached"] += c.usage.cached_tokens or 0
        usage["output"] += c.usage.output_tokens or 0
        usage["usd"] += pricing.cost(pricing.CHAT, client.model, c.usage.input_tokens, c.usage.cached_tokens,
                                     c.usage.output_tokens) or 0.0
    return {
        "doc_no": d["no"], "doc_id": d["doc_id"], "playbook": pb.name, "units": len(doc.anchors),
        "calls": len(run.calls), "calls_not_ok": sum(c.status != "ok" for c in run.calls), "seconds": round(seconds, 1),
        "usage": usage,
        "labels_same_as_stored": sum(new[u].label == stored[u]["label"] for u in doc.anchors),
        "coded_same_as_stored": sum(new[u].label == stored[u]["label"] for u in coded), "coded": len(coded),
        # by unit, whatever the new label: the stored label decides which units are facts
        "unit_keys": {u: {"key": k, "value": v, "key_votes": [g[0] if g else "" for g in given]}
                      for u in doc.anchors
                      for given in [[p.get(u) for p in keys]] for k, v in [units.vote_key(given)] if k},
    }


def write(bid_id: str) -> None:
    """Put the keys on the stored facts, as a new extraction would have written them. Only `key`, `value`
    and `key_votes` are added; every label, text and ID stays, so the bid's facts are the same facts."""
    from fact_extractor import bid as B

    keys = json.loads((OUT / f"{bid_id}.keys.json").read_text())["keys"]
    bid = B.Bid(ROOT / "runs", bid_id)
    before = json.loads((bid.folder / "facts.json").read_text())
    for d in bid.manifest()["documents"]:
        folder = ROOT / "runs" / d["run"]
        facts = json.loads((folder / "facts.json").read_text())
        by_unit = {}
        for f in facts:
            k = keys.get(f["fact_id"]) or {}
            f["key"], f["value"], f["key_votes"] = k.get("key", ""), k.get("value", ""), k.get("key_votes", [])
            if k:
                by_unit[k["unit"]] = k
        (folder / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2))
        labels = json.loads((folder / "labels.json").read_text())
        for r in labels:
            k = by_unit.get(r["id"]) or {}
            r["key"], r["value"], r["key_votes"] = k.get("key", ""), k.get("value", ""), k.get("key_votes", [])
        (folder / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2))
    after = B.build(bid)
    strip = lambda fs: [{k: v for k, v in f.items() if k not in ("key", "value", "key_votes")} for f in fs]  # noqa: E731
    print(f"{sum(bool(f.get('key')) for f in after)}/{len(after)} facts of the bid carry a key; "
          f"everything else is {'unchanged' if strip(before) == strip(after) else 'CHANGED'}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bid", default="durham")
    ap.add_argument("--votes", type=int, default=3)
    ap.add_argument("--no-keys", action="store_true", help="labels alone, to compare label agreement; writes no file")
    ap.add_argument("--write", action="store_true", help="no model call: write the keys of out/<bid>.keys.json into the "
                    "bid's stored results (facts.json and labels.json of each document) and build the bid again")
    args = ap.parse_args()
    global KEYS
    KEYS = not args.no_keys
    if args.write:
        return write(args.bid)
    load_env(str(ROOT / ".env"))
    bid = ROOT / "runs" / "_bids" / args.bid
    manifest = json.loads((bid / "bid.json").read_text())
    facts = json.loads((bid / "facts.json").read_text())
    client = OpenAIClient()
    t0 = time.monotonic()
    # One document at a time, in the order they were issued, as the app extracts them: each later
    # document is shown the keys the earlier ones used (Bid.known_keys).
    docs, known = [], {}
    for d in sorted(manifest["documents"], key=lambda d: d.get("issue_date") or ""):
        got = await key_document(d, client, args.votes, dict(known))
        docs.append(got)
        for k in got["unit_keys"].values():
            known.setdefault(k["key"], k["value"])
    seconds = time.monotonic() - t0
    by_doc = {d["doc_id"]: d for d in docs}
    keyed = {}
    for f in facts:
        d = by_doc.get(f["doc_id"])
        if not d or f.get("source_call") != "LABEL":
            continue
        for c in f["citations"]:  # the main unit first, then its continuations
            k = d["unit_keys"].get(c["id"])
            if k:
                keyed[f["fact_id"]] = {**k, "unit": c["id"]}
                break
    out = {
        "bid": args.bid, "votes": args.votes, "seconds": round(seconds, 1),
        "usd": round(sum(d["usage"]["usd"] for d in docs), 4), "calls": sum(d["calls"] for d in docs),
        "facts": len(facts), "facts_keyed": len(keyed), "distinct_keys": len({k["key"] for k in keyed.values()}),
        "documents": [{k: v for k, v in d.items() if k != "unit_keys"} for d in docs],
        "keys": keyed,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{args.bid}.keys.json"
    if KEYS:
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for d in out["documents"]:
        print(f"  doc {d['doc_no']} {d['playbook']}: {d['units']} units, {d['calls']} calls ({d['calls_not_ok']} not ok), "
              f"{d['seconds']}s, ${d['usage']['usd']:.4f}, labels same as stored {d['labels_same_as_stored']}/{d['units']}, "
              f"coded {d['coded_same_as_stored']}/{d['coded']}")
    print(f"{out['facts_keyed']}/{out['facts']} facts keyed, {out['distinct_keys']} keys, {out['calls']} calls, "
          f"${out['usd']}, {out['seconds']}s -> {path}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

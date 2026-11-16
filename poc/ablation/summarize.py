"""Print one row per (config, document): size, cost, time, recall and precision."""

import glob
import json
import os

OUT = os.path.dirname(os.path.abspath(__file__))


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


rows = []
for d in sorted(glob.glob(os.path.join(OUT, "*", "*"))):
    rep = load(os.path.join(d, "report.json"))
    if not rep:
        continue
    cmp = load(os.path.join(d, "compare.json"))
    pr = load(os.path.join(d, "precision.json")) or {}
    calls = rep["calls"]
    row = {
        "config": os.path.basename(os.path.dirname(d)), "doc": os.path.basename(d),
        "facts": rep["facts"], "calls": len(calls),
        "partial": sum(1 for c in calls if c["status"] == "partial"),
        "out_tok": rep["output_tokens"], "secs": rep["seconds"]["total"],
        "needs_rev": rep["by_status"].get("needs_review", 0),
    }
    if cmp and os.path.basename(d) == "durham" and not os.path.exists(
        os.path.join(OUT, "..", "durham", "gold", "gold.txt")
    ):
        row["doc"] = "durham*"  # scored against the unchecked draft
    if cmp:
        found = len(cmp["pairs"]); total = found + len(cmp["misses"])
        partial = sum(1 for p in cmp["pairs"] if p.get("judged") == "partial")
        row["recall"] = round(found / total, 3)
        row["recall_full"] = round((found - partial) / total, 3)
    m = pr.get("model", {}).get("all")
    if m:
        row["supported"] = m["supported"]; row["noise"] = m["noise"]; row["precision"] = m["precision"]
        row["good_facts"] = round(m["precision"] * rep["facts"])
    row["dupes"] = pr.get("duplicates", {}).get("pairs")
    rows.append(row)

cols = ["config", "doc", "facts", "good_facts", "recall", "recall_full", "precision", "supported", "noise",
        "dupes", "needs_rev", "calls", "partial", "out_tok", "secs"]
print(" ".join(f"{c:>11}" for c in cols))
for r in sorted(rows, key=lambda r: (r["doc"], r["config"])):
    print(" ".join(f"{str(r.get(c, '-')):>11}" for c in cols))
if any(r["doc"] == "durham*" for r in rows):
    print("durham*: recall scored against poc/durham/gold/gold_draft.txt, which no person has checked yet")
with open(os.path.join(OUT, "summary.json"), "w") as f:
    json.dump(rows, f, indent=2)

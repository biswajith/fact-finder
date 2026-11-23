"""Score a bid against a key a person wrote by hand. No model call: it reads what the bid stored.

The key is a JSON file with any of three parts:

    {"relations": [{"from": {"doc": "ADD1", "unit": "p1.2"}, "kind": "REPLACES",
                    "to": [{"doc": "RFP", "unit": "p1.2"}]}],
     "sides": {"Dana Pike": "buyer", "Tom Okafor": "ours"},
     "groups": [["restated rule in the RFP", {"doc": "ADD1", "text": "restated rule"}]]}

`doc` is a document ID of the bid (or its number). A relation with no targets (ADDS, NONE) is scored
on its kind alone. A group lists, for each member, a piece of the fact's text (case ignored) or an
object with the `doc` it must come from. A part the key leaves out is not scored.

Scored:
- relations: of the key's relations, how many RELATE gave the same kind and the same targets, how
  many it gave another kind, other targets, or no answer; and how many answers outside the key it
  gave a kind that does something (anything but NONE and ADDS).
- applied: for each key target of a REPLACES or REMOVES, whether the fact it reaches (a heading
  reaches every fact up to the next heading) is flagged replaced; and which facts the bid replaced
  by a relation that the key does not name.
- groups: key groups the bid made, key groups it missed, and "same" groups it made that the key does
  not list (a wrong "same" hides a change, so every restated point has to be in the key).
- sides: confirmed sides of the speakers that match the key, and how many were proposed right.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import bid as B
from . import ladder

CHANGES = ("REPLACES", "REMOVES")


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _doc_id(ref, manifest: dict) -> str:
    """A key's document: an ID of the bid, or its number."""
    for d in manifest["documents"]:
        if ref in (d["doc_id"], d["no"]) or str(ref) == str(d["no"]):
            return d["doc_id"]
    raise ValueError(f"the key names a document the bid does not have: {ref!r}")


def _targets(row: dict, manifest: dict) -> set[tuple[str, str]]:
    return {(_doc_id(t["doc"], manifest), t["unit"]) for t in row.get("to") or []}


def score_relations(bid: B.Bid, key: dict, manifest: dict) -> dict:
    stored = {d["doc_id"]: {r["unit"]: r for r in _read(bid.root / d["run"] / "relations.json", {}).get("units", [])}
              for d in manifest["documents"] if d.get("run")}
    expected = set()
    out = {"expected": len(key), "right": 0, "wrong_kind": 0, "wrong_targets": 0, "missing": 0, "extra": 0, "misses": []}
    for row in key:
        doc, unit = _doc_id(row["from"]["doc"], manifest), row["from"]["unit"]
        expected.add((doc, unit))
        got = (stored.get(doc) or {}).get(unit) or {}
        want = _targets(row, manifest)
        have = {(t["doc_id"], t["unit"]) for t in got.get("targets") or []}
        if not got.get("kind"):
            out["missing"] += 1
            why = "no answer"
        elif got["kind"] != row["kind"].upper():
            out["wrong_kind"] += 1
            why = f"kind {got['kind']}"
        elif have != want:
            out["wrong_targets"] += 1
            why = "targets " + ", ".join(sorted(f"{d}:{u}" for d, u in have)) if have else "no targets"
        else:
            out["right"] += 1
            continue
        out["misses"].append(f"{doc}:{unit} {row['kind'].upper()}: {why}")
    for doc, rows in stored.items():
        out["extra"] += sum(1 for u, r in rows.items() if (doc, u) not in expected and r.get("kind") not in ("", "NONE", "ADDS"))
    return out


def score_applied(bid: B.Bid, key: dict, manifest: dict, facts: list[dict]) -> dict:
    """Which facts the key says a REPLACES or REMOVES reaches, against the facts the bid replaced."""
    by_doc: dict[str, list[dict]] = {}
    for f in facts:
        by_doc.setdefault(f["doc_id"], []).append(f)
    units = {
        d["doc_id"]: [{"id": u["id"], "kind": u.get("kind", ""), "side": u.get("side", ""), "text": u.get("text", "")}
                      for u in _read(bid.root / d["run"] / "units.json", [])]
        for d in manifest["documents"] if d.get("run")
    }
    ix = ladder._Bid(manifest["documents"], by_doc, units)  # the same reading of a heading as the ladder's
    want: set[str] = set()
    for row in key:
        if row["kind"].upper() not in CHANGES:
            continue
        for doc, unit in _targets(row, manifest):
            if ix.kind_of(doc, unit) == "heading":
                sec = ix.section(doc, unit)
                reached = ix.facts_in(doc, sec[1]) if sec else []
            else:
                reached = ix.by_unit.get((doc, unit), [])[:1]
            want |= {f["fact_id"] for f in reached}
    by_relation = {
        f["fact_id"] for f in facts
        if "replaced" in f.get("flags", []) and any(r["kind"] in (*CHANGES, "DISAGREES") and r["to"]["fact_id"] == f["fact_id"] for r in f.get("relations") or [])
    }
    return {
        "expected": len(want), "replaced": len(want & by_relation), "not_replaced": len(want - by_relation),
        "replaced_but_not_in_key": len(by_relation - want),
    }


def _matches(fragment, facts: list[dict], manifest: dict) -> set[str]:
    text, doc = (fragment, None) if isinstance(fragment, str) else (fragment["text"], _doc_id(fragment["doc"], manifest))
    return {f["fact_id"] for f in facts if text.casefold() in f["text"].casefold() and doc in (None, f["doc_id"])}


def score_groups(key: list, manifest: dict, facts: list[dict]) -> dict:
    same: dict[str, set[str]] = {}
    for f in facts:
        if f.get("group_id") and f.get("group_kind") == "same":
            same.setdefault(f["group_id"], set()).add(f["fact_id"])
    found: set[str] = set()
    missed: list[str] = []
    for fragments in key:
        parts = [_matches(x, facts, manifest) for x in fragments]
        hit = next((gid for gid, members in same.items()
                    if all(p & members for p in parts) and members <= set().union(*parts)), None)
        if hit:
            found.add(hit)
        else:
            missed.append(" + ".join(x if isinstance(x, str) else x["text"] for x in fragments))
    return {"expected": len(key), "found": len(found), "missed": len(missed), "wrong": len(set(same) - found), "misses": missed}


def score_sides(key: dict[str, str], manifest: dict) -> dict:
    speakers = [s for d in manifest["documents"] for s in d.get("speakers") or [] if s["name"] in key]
    names = {s["name"] for s in speakers}
    return {
        "expected": len(key), "right": sum(s["side"] == key[s["name"]] for s in speakers),
        "wrong": sum(s["side"] != key[s["name"]] for s in speakers), "not_in_bid": len(set(key) - names),
        "proposed_right": sum(s["proposed"] == key[s["name"]] for s in speakers),
    }


def score(bid: B.Bid, key: dict) -> dict:
    """The counts for each part of the key. Raises FileNotFoundError when the bid has no fact list yet."""
    manifest = bid.manifest()
    facts = _read(bid.folder / "facts.json", None)
    if facts is None:
        raise FileNotFoundError(f"the bid {bid.bid_id!r} has no fact list: run it first")
    out: dict = {}
    if "relations" in key:
        out["relations"] = score_relations(bid, key["relations"], manifest)
        out["applied"] = score_applied(bid, key["relations"], manifest, facts)
    if "groups" in key:
        out["groups"] = score_groups(key["groups"], manifest, facts)
    if "sides" in key:
        out["sides"] = score_sides(key["sides"], manifest)
    return out


def report(result: dict) -> str:
    """The counts as plain lines."""
    lines = []
    if "relations" in result:
        r = result["relations"]
        lines.append(
            f"relations: {r['right']} of {r['expected']} right; {r['wrong_kind']} wrong kind, {r['wrong_targets']} wrong targets, "
            f"{r['missing']} unanswered; {r['extra']} more answered that the key does not list"
        )
        lines += [f"  {m}" for m in r["misses"]]
        a = result["applied"]
        lines.append(
            f"applied: {a['replaced']} of {a['expected']} facts replaced that should be; {a['not_replaced']} not replaced; "
            f"{a['replaced_but_not_in_key']} replaced that the key does not name"
        )
    if "groups" in result:
        g = result["groups"]
        lines.append(f"groups: {g['found']} of {g['expected']} 'same' groups made; {g['missed']} missed; {g['wrong']} made that the key does not list")
        lines += [f"  missed: {m}" for m in g["misses"]]
    if "sides" in result:
        s = result["sides"]
        lines.append(
            f"sides: {s['right']} of {s['expected']} speakers on the right side; {s['wrong']} wrong, {s['not_in_bid']} not in the bid; "
            f"{s['proposed_right']} proposed right"
        )
    return "\n".join(lines) or "the key scores nothing: it has no relations, groups or sides"


__all__ = ["score", "report"]

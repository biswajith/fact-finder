"""Turn a bid's keyed facts into current values, in code alone. No model call.

    uv run python -m poc.graphchat.keyed      # facts.json + out/durham.keys.json -> out/durham.keyed.json

A fact that states a value carries a key (`thing.attribute`) and the value, given by the LABEL call
(units.py). Here every key becomes one field with one current value:

1. Same or different. Two values of one key are the same when they clean to the same text, or both hold
   figures and one's figures are all in the other (3 years = three years; 2024-06-10 is a shorter
   2024-06-10 14:00 ET). Nothing else is the same.
2. Which stands. The app's own source level ranks them (1 a buyer document, 2 the buyer speaking on a
   call, 3 our side on a call, 4 the team's notes); a later document wins inside a level.
   - A value with a calendar date replaces an estimate or a placeholder for the same key, whatever the
     levels: "week of 2024-09-16" replaces "TBD".
   - The buyer against the buyer (levels 1 and 2 with different figures) needs a person.
   - Values without figures that differ (several contacts) are not rivals: they are listed.
3. Everything else stays a fact. Each document section is a node whose lists hold its facts, so nothing
   is lost; a fact with a key points at its field, and shows the field's value once it has been changed.

The file has the shape of the graph files, so the graph chat (agent.py, store.py) reads it unchanged.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from fact_extractor import playbooks
from fact_extractor.normalize import values

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
HAND = ROOT / "web" / "mock" / "graph" / "durham.graph.json"
LEVEL = {1: "the buyer's document", 2: "the buyer on a call", 3: "our side on a call", 4: "the team's notes"}


def clean(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9$%.]+", " ", str(s).lower()).split()).strip(" .")


_MONTH = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
_ABOUT = re.compile(r"\b(about|around|roughly|approximately|approx|nearly|some)\b|~", re.I)


def figures(text: str) -> set[str]:
    """What a value holds, for comparing two values of one key. A date, a day of a month or a time stands
    as itself (and a date also as its day and its year); the loose numbers they are made of are dropped.
    Without any of those, every number stands."""
    got = set(values(text, generous=True))
    typed = {v for v in got if ":" in v}
    if not typed:
        return got
    out = set(typed)
    for v in typed:
        if v.startswith("date:"):
            out |= {"md:" + v[10:], v[5:9]}
    return out


def same(a: str, b: str) -> bool:
    """Two values of one key say the same thing: the same text; or both hold figures and one's figures are
    all in the other (a date with and without its time); or their largest numbers are equal (95k, ninety-five
    thousand); or one is given as about a number within 2% of the other's."""
    if clean(a) == clean(b):
        return True
    fa, fb = figures(a), figures(b)
    if not fa or not fb:
        return False
    if fa <= fb or fb <= fa:
        return True
    if any(":" in v for v in fa | fb):
        return False
    try:
        ma, mb = max(float(v) for v in fa), max(float(v) for v in fb)
    except ValueError:
        return False
    return ma == mb or (bool(_ABOUT.search(a) or _ABOUT.search(b)) and abs(ma - mb) <= 0.02 * max(ma, mb))


def dated(text: str) -> bool:
    return any(v.startswith(("date:", "md:")) for v in values(text, generous=True)) or bool(_MONTH.search(text))


def title(part: str) -> str:
    return part.replace("-", " ").capitalize()


def settle(key: str, claims: list[dict]) -> dict:
    """claims: {value, fact, level, issued}. One field: the value that stands, what it beat, and why."""
    groups: list[dict] = []
    # The fullest values first, so a bare date joins the dated time it agrees with, never the other way round.
    for c in sorted(claims, key=lambda c: (-len(figures(c["value"])), c["level"])):
        for g in groups:
            if same(c["value"], g["claims"][0]["value"]):
                g["claims"].append(c)
                break
        else:
            groups.append({"claims": [c]})
    for g in groups:
        g["rank"] = min((c["level"], _newest_first(c["issued"])) for c in g["claims"])
        g["level"] = g["rank"][0]
        best = min(g["claims"], key=lambda c: ((c["level"], _newest_first(c["issued"])), -len(c["value"])))
        g["value"] = best["value"]
        g["facts"] = list(dict.fromkeys(c["fact"] for c in g["claims"]))
        g["dated"] = any(dated(c["value"]) for c in g["claims"])
        g["figures"] = bool(figures(g["value"]))
    groups.sort(key=lambda g: g["rank"])
    reason, status = "", "none"
    # A calendar date replaces an estimate or a placeholder for the same key, whatever the levels.
    specific = [g for g in groups if g["dated"]]
    placeholders = [g for g in groups if not g["dated"]] if specific and key.rsplit(".", 1)[-1].endswith(
        ("date", "due", "start", "deadline")) else []
    rivals = [g for g in groups if g not in placeholders]
    win = rivals[0]
    # Different values without figures are not rivals (several contacts, several roles): they are listed.
    listed = [g for g in rivals[1:] if not (g["figures"] or win["figures"])]
    rest = [g for g in rivals[1:] if g not in listed]
    if rest:
        if rest[0]["level"] == win["level"]:
            status, reason = "needs_review", f"Two statements from {LEVEL[win['level']]} disagree: a person must choose."
        elif {win["level"], rest[0]["level"]} == {1, 2}:
            status, reason = "needs_review", ("The buyer said something different on a call than its document says. "
                                              "The document's value stands until a person decides.")
        else:
            status = "auto_resolved"
            reason = f"{LEVEL[win['level']].capitalize()} outranks {LEVEL[rest[0]['level']]}."
    elif placeholders:
        status = "auto_resolved"
        reason = f"A stated date replaces the estimate or placeholder ({placeholders[0]['value']})."
    return {"name": title(key.rsplit(".", 1)[-1]), "key": key, "value": win["value"], "facts": win["facts"],
            "status": status, "reason": reason,
            "competing": [{"value": g["value"], "facts": g["facts"]} for g in rest],
            "replaced": [{"value": g["value"], "facts": g["facts"]} for g in placeholders],
            "listed": [{"value": g["value"], "facts": g["facts"]} for g in listed]}


def _newest_first(date: str) -> str:
    return "".join(chr(255 - ord(ch)) for ch in date or "")


def build(bid: str = "durham") -> dict:
    t0 = time.monotonic()
    folder = ROOT / "runs" / "_bids" / bid
    facts = json.loads((folder / "facts.json").read_text())
    manifest = json.loads((folder / "bid.json").read_text())
    keys = json.loads((OUT / f"{bid}.keys.json").read_text())["keys"]
    summaries = json.loads((folder / "workspace" / "summaries.json").read_text())["sections"]
    hand = json.loads(HAND.read_text())  # only for the document names, the fact table and the type names
    doc = {d["no"]: d for d in manifest["documents"]}
    name = {d["no"]: d["name"] for d in hand["documents"]}
    short = lambda f: f["fact_id"][2:]  # noqa: E731
    by_short = {short(f): f for f in facts}

    # 1. keys -> value nodes
    claims: dict[str, list[dict]] = {}
    for f in facts:
        k = keys.get(f["fact_id"]) or ({"key": f["key"], "value": f["value"]} if f.get("key") else None)
        if k:
            claims.setdefault(k["key"], []).append({"value": k["value"], "fact": short(f), "level": f.get("level") or 4,
                                                    "issued": doc[f["doc_no"]].get("issue_date") or ""})
    nodes: dict[str, dict] = {}
    field_of: dict[str, tuple[str, str]] = {}  # fact -> (node, field)
    for key in sorted(claims):
        thing = key.rsplit(".", 1)[0]
        nid = "v_" + re.sub(r"[^a-z0-9]+", "_", thing)
        n = nodes.setdefault(nid, {"id": nid, "type": "value", "label": title(thing.replace(".", " ")), "sub": "",
                                   "facts": [], "fields": [], "lists": [], "status": "live", "note": ""})
        s = settle(key, claims[key])
        if s["status"] == "none" and all("tentative" in by_short[i]["flags"] for i in s["facts"]):
            s["status"], s["reason"] = "tentative", "Every source gives it as not final."
        n["fields"].append({k: s[k] for k in ("name", "key", "value", "facts", "status", "reason", "competing")})
        for o in s["listed"] + s["replaced"]:
            lst = next((l for l in n["lists"] if l["name"] == f"Other {s['name'].lower()} statements"), None)
            if lst is None:
                lst = {"name": f"Other {s['name'].lower()} statements", "items": []}
                n["lists"].append(lst)
            lst["items"].append({"value": o["value"], "facts": o["facts"]})
        for c in claims[key]:
            field_of[c["fact"]] = (nid, s["name"])
            n["facts"].append(c["fact"])
    for n in nodes.values():
        n["sub"] = "; ".join(f"{f['name'].lower()} {f['value']}" for f in n["fields"])[:70]

    # 2. every fact stays, in a node for its document section; lists are named by category
    links = []
    for f in facts:
        cite = f["citations"][0] if f["citations"] else {}
        section = cite.get("section") or ""
        nid = f"s{f['doc_no']}_" + (re.sub(r"[^a-z0-9]+", "_", section.lower()).strip("_")[:40] or "top")
        n = nodes.setdefault(nid, {"id": nid, "type": "section", "label": section or name[f["doc_no"]],
                                   "sub": name[f["doc_no"]] if section else "", "facts": [], "fields": [], "lists": [],
                                   "status": "live", "note": ""})
        n["facts"].append(short(f))
        cat = playbooks.definition(f["category"]).split("=", 1)[1].split(":", 1)[0].strip().capitalize()
        lst = next((l for l in n["lists"] if l["name"] == cat), None)
        if lst is None:
            lst = {"name": cat, "items": []}
            n["lists"].append(lst)
        item = {"value": f["text"], "facts": [short(f)]}
        if short(f) in field_of:
            item["ref"] = list(field_of[short(f)])
            link = {"from": nid, "edge": "states", "to": field_of[short(f)][0], "facts": [short(f)], "status": "live"}
            if not any(l["from"] == link["from"] and l["to"] == link["to"] for l in links):
                links.append(link)
        lst["items"].append(item)

    # 3. the summary views are the app's own summaries; each row names the nodes its facts are in
    where: dict[str, list[str]] = {}
    for n in nodes.values():
        for i in n["facts"]:
            where.setdefault(i, []).append(n["id"])
    lenses = []
    for hl in hand["lenses"]:
        sec = summaries.get(hl["key"])
        if not sec:
            continue
        rows = []
        for r in sec["rows"]:
            ids = [w for i in r["fact_ids"] for w in where.get(i[2:], [])]
            ids.sort(key=lambda w: (not w.startswith("v_"), -ids.count(w)))
            text = " ".join(x for x in (r.get("time", ""), r["text"]) if x)
            rows.append({"row": r["row"], "text": text, "nodes": list(dict.fromkeys(ids))[:9]})
        lenses.append({"key": hl["key"], "title": hl["title"], "icon": hl["icon"], "rows": rows})

    # The app's own open conflicts between statements that are not values of a key (conflicts.json).
    conflicts = []
    for c in json.loads((folder / "conflicts.json").read_text()):
        ids = [i[2:] for i in c.get("fact_ids") or []]
        if c.get("status") == "open" and not any(i in field_of for i in ids):
            conflicts.append({"conflict": c["description"][:400], "nodes": list(dict.fromkeys(w for i in ids for w in where.get(i, [])))})

    table = hand["facts"]
    for k in table:
        table[k]["used"] = True
    fields = [f for n in nodes.values() for f in n["fields"]]
    return {"bid": hand["bid"], "documents": hand["documents"],
            "types": {**hand["types"], "value": {"name": "value"}, "section": {"name": "section"}},
            "nodes": list(nodes.values()), "links": links, "facts": table, "lenses": lenses, "conflicts": conflicts,
            "build": {"seconds": round(time.monotonic() - t0, 3), "model_calls": 0, "keys": len(claims),
                      "facts_keyed": len(field_of), "facts_total": len(facts),
                      "status": {s: sum(f["status"] == s for f in fields) for s in ("none", "auto_resolved", "needs_review")}}}


if __name__ == "__main__":
    g = build(sys.argv[1] if len(sys.argv) > 1 else "durham")
    path = OUT / "durham.keyed.json"
    path.write_text(json.dumps(g, ensure_ascii=False, indent=1))
    print(json.dumps(g["build"]), "->", path)
    for n in g["nodes"]:
        for f in n["fields"]:
            if f["status"] != "none":
                print(f"  {f['status']:13} {f['key']}: {f['value']!r} vs {[c['value'] for c in f['competing']]} | {f['reason']}")

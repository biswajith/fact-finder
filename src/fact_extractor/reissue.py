"""A reissued full RFP (design: "Reissued full RFPs").

A reissue has no list of changes. Code aligns the units of the new version with the units of the
previous one by text, in order, so that repeated text pairs up in sequence. An aligned unit keeps the
votes the previous version gave it; every other unit is labelled by the model, together with any
continuation whose coded unit did not align. A fact is carried over when every one of its units
aligns to the units of one old fact; `alignment.json` keeps the old-to-new fact ID map so the user's
corrections follow it.

Comparing two extracted fact lists instead would report false changes: labels differ between runs.
No model call is made here that the normal run does not make, and none for RELATE.
"""

from __future__ import annotations

import copy
import difflib
import json
from pathlib import Path

from . import results, units
from .models import TaggedDocument
from .xref import norm


def _match(old: TaggedDocument, new: TaggedDocument) -> tuple[dict[str, str], list[str], list[str], list[str]]:
    """`(pairs new->old, changed, new, removed)`. Equal blocks pair in order. In a block where the old
    text was replaced, the first units pair as changed; the surplus on either side is new or removed."""
    a, b = list(old.anchors.values()), list(new.anchors.values())
    ka = [(x.kind, norm(x.text)) for x in a]
    kb = [(x.kind, norm(x.text)) for x in b]
    pairs: dict[str, str] = {}
    changed: list[str] = []
    added: list[str] = []
    removed: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                pairs[b[j].id] = a[i].id
        elif tag == "delete":
            removed += [x.id for x in a[i1:i2]]
        elif tag == "insert":
            added += [x.id for x in b[j1:j2]]
        else:
            both = min(i2 - i1, j2 - j1)
            changed += [x.id for x in b[j1 : j1 + both]]
            added += [x.id for x in b[j1 + both : j2]]
            removed += [x.id for x in a[i1 + both : i2]]
    return pairs, changed, added, removed


def align(old: TaggedDocument, new: TaggedDocument) -> dict[str, str]:
    """`{new unit: old unit}` for the units whose normalised text (and kind) is the same, paired in order
    with `difflib.SequenceMatcher(autojunk=False)`. A sentence repeated in both documents pairs first
    with first, second with second."""
    return _match(old, new)[0]


def _old_voted(rows: list[dict]) -> dict[str, units.Voted]:
    return {r["id"]: units.Voted(r["label"], r.get("also"), list(r.get("flags") or []), list(r.get("votes") or [])) for r in rows}


def _copy(v: units.Voted) -> units.Voted:
    return units.Voted(v.label, v.also, list(v.flags), list(v.votes))


async def extract(
    new_doc: TaggedDocument, old_stored: results.Stored, client, pb, cfg, *, deal_id: str = "", run_id: str | None = None,
) -> units.RunResult:
    """Extract `new_doc`, the reissue of the document stored as `old_stored`. Units that align to an old
    unit keep its votes; the rest are labelled and stated in the usual batches. The result's
    `alignment` is the content of `alignment.json`. A stored result with no `labels.json` or
    `units.json` gives nothing to carry: the document is then extracted as a whole."""
    cfg = cfg or units.Config(votes=pb.votes)
    old_doc_id = old_stored.meta.get("doc_id", "")
    old = results.load_document(old_stored.folder, old_doc_id)
    try:
        rows = json.loads((old_stored.folder / "labels.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    if old is None or not rows:
        return await units.extract(new_doc, client, deal_id=deal_id, cfg=cfg, run_id=run_id, playbook=pb)
    pairs, changed, added, removed = _match(old, new_doc)
    inverse = {o: n for n, o in pairs.items()}
    old_voted = _old_voted(rows)
    old_ids = [u for u in old.anchors if u in old_voted]
    old_groups = units.group(old_voted, old_ids, pb)
    old_main = {i: g.main for g in old_groups for i in g.ids}
    order = {u: n for n, u in enumerate(new_doc.anchors)}
    old_facts = {f["fact_id"]: f for f in old_stored.facts()}

    carried: dict[str, units.Voted] = {}
    statements: dict[str, str] = {}
    for u in new_doc.anchors:
        o = pairs.get(u)
        if o is None or o not in old_voted:
            continue
        v = old_voted[o]
        if v.label == units.CONTINUES:
            m = inverse.get(old_main.get(o, ""))  # the new unit its coded unit aligned to
            if m is None or order[m] >= order[u]:
                continue  # its coded unit did not align: label it again
        elif v.label in pb.codes:
            f = old_facts.get(units.fact_id(old_doc_id, o))
            if f is not None and f.get("text_from") == "model":
                statements[u] = f["text"]
        carried[u] = _copy(v)
    only = [u for u in new_doc.anchors if u not in carried]
    result = await units.extract(
        new_doc, client, deal_id=deal_id, cfg=cfg, run_id=run_id, playbook=pb, only=only, carried=carried, statements=statements,
    )

    by_main = {g.main: g for g in old_groups}
    fact_map: dict[str, str] = {}
    for f in result.facts:
        if f["category"] == "Q" or not f["citations"]:
            continue
        cited = [c["id"] for c in f["citations"]]
        olds = [pairs.get(i) for i in cited]
        g = by_main.get(olds[0] or "")
        if g is None or olds != g.ids or cited[0] not in carried:
            continue
        before = old_facts.get(units.fact_id(old_doc_id, g.main))
        if before is None:
            continue
        fact_map[before["fact_id"]] = f["fact_id"]
        f["text"], f["text_from"] = before["text"], before.get("text_from", f["text_from"])
    alignment = {
        "previous": old_doc_id, "units": pairs, "facts": fact_map, "changed": changed, "new": added, "removed": removed,
    }
    result.alignment = alignment
    result.report["reissue"] = {
        "previous": old_doc_id, "aligned": len(pairs), "relabelled": len(only), "carried_facts": len(fact_map),
        "changed": len(changed), "new": len(added), "removed": len(removed),
    }
    return result


def read_alignment(folder: str | Path) -> dict:
    """The stored `alignment.json` of a result folder, or {} when it has none."""
    try:
        got = json.loads((Path(folder) / "alignment.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def merge_maps(maps: list[dict[str, str]]) -> dict[str, str]:
    """One old-to-new fact ID map from the maps of the reissues in issue order, chained: a fact
    carried A to B and then B to C maps A to C (and B to C)."""
    out: dict[str, str] = {}
    for m in maps:
        for k, v in out.items():
            if v in m:
                out[k] = m[v]
        for k, v in m.items():
            out.setdefault(k, v)
    return out


def bid_map(bid_folder: str | Path) -> dict[str, str]:
    """The merged old-to-new fact ID map of a bid, from the `alignment.json` of its reissued documents
    in issue order. Empty for a bid with no reissue. Reads files only."""
    from . import bid as B

    folder = Path(bid_folder)
    try:
        manifest = json.loads((folder / "bid.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    root = folder.parent.parent
    maps = []
    for d in B.issue_order(manifest):
        if d.get("playbook") == "reissued-rfp" and d.get("run"):
            facts = read_alignment(root / d["run"]).get("facts")
            if isinstance(facts, dict) and facts:
                maps.append(facts)
    return merge_maps(maps)


def map_entry(entry: dict, ids: dict[str, str]) -> dict:
    """The log entry with every fact ID it holds sent through `ids`: its `fact_id`, the `fact_ids` of a
    `raise` entry's fields and the `fact_id` of each change of each option. The entry given is not changed."""
    e = copy.deepcopy(entry)
    if e.get("fact_id") in ids:
        e["fact_id"] = ids[e["fact_id"]]
    fields = e.get("fields")
    if isinstance(fields, dict):
        if isinstance(fields.get("fact_ids"), list):
            fields["fact_ids"] = [ids.get(i, i) if isinstance(i, str) else i for i in fields["fact_ids"]]
        for o in fields.get("options") or []:
            for c in (o.get("changes") or []) if isinstance(o, dict) else []:
                if isinstance(c, dict) and c.get("fact_id") in ids:
                    c["fact_id"] = ids[c["fact_id"]]
    return e


def map_log(log: list[dict], ids: dict[str, str]) -> list[dict]:
    """`map_entry` for each entry; entries that name no mapped fact are passed on as they are."""
    return [map_entry(e, ids) for e in log] if ids else log

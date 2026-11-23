"""The priority ladder: what a relation may do to a fact. Pure code: no model, no file, no web module.

Levels: 1 buyer documents, 2 the buyer on a call, 3 our side on a call, 4 deal notes. The rule: a
fact from a lower level (a bigger number) never changes a fact from a higher one, and below level 1
nothing replaces anything automatically: two disagreeing statements are both kept and the user
decides. Between level-1 documents the later issue wins, unless the buyer's stated order of
precedence (confirmed by the user, a list of document IDs, highest first) says otherwise. Two
level-1 documents issued together (the same issue date and number) that disagree are a conflict,
never a replacement.

`apply` takes the facts of every document in issue order and the stored `relations.json` of each,
and returns the facts with `relations`, `replaced_by`, the flag `replaced` and `stale` filled in,
and the conflicts to raise for the documents. Relations are applied in issue order, not in the
order the documents were loaded, so addendum 3 loaded before addendum 2 still applies after it.
A fact's text is never changed.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

from . import playbooks

CHANGING = ("REPLACES", "REMOVES", "DISAGREES")  # the kinds that may mark a fact replaced
SETTLING = ("REPLACES", "REMOVES", "CONFIRMS")  # what a later buyer document does that settles a conflict
STALE = "section partly replaced"
REASONS = (
    "user-edited fact replaced", "old value elsewhere", "depends on changed value", "levels disagree", "unfound target",
    "issued together",
)


@dataclass
class Applied:
    facts: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)  # document conflicts, in the order they were found


def relation_id(from_doc: str, from_unit: str, kind: str, to_doc: str, to_unit: str) -> str:
    """The same relation always has the same ID, so a rejection stays attached to it."""
    return "r_" + hashlib.sha1(f"{from_doc}|{from_unit}|{kind}|{to_doc}|{to_unit}".encode()).hexdigest()[:10]


def conflict_id(fact_ids: Iterable[str], reason: str) -> str:
    return "d:" + hashlib.sha1(("|".join(sorted(set(fact_ids))) + "|" + reason).encode()).hexdigest()[:10]


def outcome(
    new_level: int, old_level: int, later: bool, precedence_says_old: bool | None = None, *, together: bool = False,
) -> str:
    """What a statement that changes or disagrees does to an existing fact.

    - "conflict": the new statement is level 2 to 4. Both are kept; the user decides.
    - "q-fact": both are level 1 and were issued together (`together`): a contradiction, no winner.
    - "keep-old": both are level 1 and the order of precedence puts the old one first, or the new
      one is not the later issue; or the new one is level 1 and the old one is not later than it.
    - "replace": both are level 1 and the new one is later or the order of precedence puts it
      first (`precedence_says_old` is False; None means the order says nothing); or a level-1
      statement changes a lower-level fact.
    """
    if new_level >= 2:
        return "conflict"
    if old_level >= 2:
        return "replace" if later else "keep-old"
    if together:
        return "q-fact"
    if precedence_says_old is not None:
        return "keep-old" if precedence_says_old else "replace"
    return "replace" if later else "keep-old"


def _clip(text: str, n: int = 70) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _flagged(fact: dict) -> list[str]:
    return [*fact.get("flags", []), *([] if "replaced" in fact.get("flags", []) else ["replaced"])]


def _replace_change(fact: dict) -> dict:
    """An edit that marks `fact` replaced. `add_flag` tells the workspace to add to the flags the
    fact has when the choice is made (the user may have changed them); `fields` is the fallback."""
    return {"op": "edit", "fact_id": fact["fact_id"], "fields": {"flags": _flagged(fact)}, "add_flag": "replaced"}


def _option(label: str, text: str = "", changes: list[dict] | None = None, question: bool = False) -> dict:
    o = {"label": label, "text": text, "citation": None, "changes": changes or []}
    if question:
        o["question"] = True
    return o


class _Bid:
    """The indexes `apply` reads: facts by ID and by unit, the units of each document in order."""

    def __init__(self, docs: list[dict], facts: dict[str, list[dict]], units: dict[str, list[dict]]) -> None:
        self.docs = {d["doc_id"]: d for d in docs}
        self.pos = {d["doc_id"]: i for i, d in enumerate(docs)}
        self.units = units
        self.by_id: dict[str, dict] = {}
        self.by_unit: dict[tuple[str, str], list[dict]] = {}
        self.order: dict[str, dict[str, int]] = {d: {u["id"]: i for i, u in enumerate(us)} for d, us in units.items()}
        for doc_id, fs in facts.items():
            for f in fs:
                self.by_id[f["fact_id"]] = f
                if f.get("category") == "Q":  # a contradiction cites units; it does not own them
                    continue
                cites = [c["id"] for c in f.get("citations") or []]
                for i, uid in enumerate(cites):
                    row = self.by_unit.setdefault((doc_id, uid), [])
                    row.insert(0, f) if i == 0 else row.append(f)  # the fact coded from the unit comes first

    def kind_of(self, doc_id: str, unit: str) -> str:
        i = self.order.get(doc_id, {}).get(unit)
        return self.units[doc_id][i].get("kind", "") if i is not None else ""

    def section(self, doc_id: str, unit: str) -> tuple[str, set[str]] | None:
        """The heading a unit sits under (itself, for a heading) and the units from it to the next heading."""
        us = self.units.get(doc_id) or []
        i = self.order.get(doc_id, {}).get(unit)
        if i is None:
            return None
        start = next((j for j in range(i, -1, -1) if us[j].get("kind") == "heading"), None)
        if start is None:
            return None
        end = next((j for j in range(start + 1, len(us)) if us[j].get("kind") == "heading"), len(us))
        return us[start]["id"], {u["id"] for u in us[start:end]}

    def facts_in(self, doc_id: str, ids: set[str]) -> list[dict]:
        seen, out = set(), []
        for uid in sorted(ids, key=lambda u: self.order[doc_id].get(u, 0)):
            for f in self.by_unit.get((doc_id, uid), []):
                if f["fact_id"] not in seen and f["citations"] and f["citations"][0]["id"] == uid:  # by main unit
                    seen.add(f["fact_id"])
                    out.append(f)
        return out

    def level_of_unit(self, doc_id: str, unit: str, from_fact: dict | None) -> int:
        if from_fact is not None and from_fact.get("level"):
            return int(from_fact["level"])
        try:
            pb = playbooks.load(self.docs[doc_id]["playbook"])
        except (KeyError, ValueError):
            return 1
        if pb.level != "by speaker":
            return int(pb.level)
        i = self.order.get(doc_id, {}).get(unit)
        side = self.units[doc_id][i].get("side") if i is not None else ""
        return 2 if side == "buyer" else 3

    def unit_text(self, doc_id: str, unit: str) -> str:
        i = self.order.get(doc_id, {}).get(unit)
        return self.units[doc_id][i].get("text", "") if i is not None else ""

    def together(self, a: str, b: str) -> bool:
        x, y = self.docs.get(a), self.docs.get(b)
        return bool(x and y and (x.get("issue_date"), x.get("issue_number")) == (y.get("issue_date"), y.get("issue_number")))


def _says_old(precedence: list[str] | None, old_doc: str, new_doc: str) -> bool | None:
    if precedence and old_doc in precedence and new_doc in precedence:
        return precedence.index(old_doc) < precedence.index(new_doc)
    return None


def apply(
    docs_in_order: list[dict], facts_by_doc: dict[str, list[dict]], relations_by_doc: dict[str, dict],
    rejected: Collection[str] = frozenset(), precedence: list[str] | None = None, *,
    units_by_doc: dict[str, list[dict]] | None = None, edited: Collection[str] = frozenset(),
) -> Applied:
    """Apply every document's relations, in the order given, to the facts of the documents before it.

    `docs_in_order` are manifest entries (doc_id, playbook, issue_date, issue_number) in issue order.
    `units_by_doc` holds each document's units in document order, `{id, kind, side, text}`: a heading
    target reaches the facts from that heading to the next one. `rejected` are relation IDs the user
    rejected: skipped everywhere. `edited` are the IDs of facts the user edited: such a fact is not
    flagged replaced, a conflict is raised instead. The input is not changed."""
    facts = {d: copy.deepcopy(fs) for d, fs in facts_by_doc.items()}
    ix = _Bid(docs_in_order, facts, units_by_doc or {})
    conflicts: dict[str, dict] = {}
    partial: list[tuple[str, str, set[str]]] = []  # (document, heading unit, units of the section) with a unit replaced

    def raise_conflict(reason: str, doc_id: str, fact_ids: list[str], title: str, description: str, options: list[dict]) -> None:
        cid = conflict_id(fact_ids, reason)
        conflicts.setdefault(cid, {
            "id": cid, "kind": "document", "title": title, "description": description, "fact_ids": fact_ids,
            "options": options, "status": "open", "resolution": None, "reason": reason, "doc_id": doc_id,
            "closed_by": "",
        })

    def mark(target: dict, by: dict | None, kind: str) -> None:
        if "replaced" not in target.get("flags", []):
            target["flags"] = [*target.get("flags", []), "replaced"]
        target["replaced_by"] = by["fact_id"] if by is not None and kind != "REMOVES" else ""

    for doc in docs_in_order:
        doc_id = doc["doc_id"]
        rel = relations_by_doc.get(doc_id) or {}
        held = {h.get("unit") for h in rel.get("held_refs") or []}
        for row in rel.get("units") or []:
            kind, unit = row.get("kind", ""), row.get("unit", "")
            if kind in ("", "NONE"):
                continue
            mains = ix.by_unit.get((doc_id, unit), [])
            from_fact = mains[0] if mains else None
            new_level = ix.level_of_unit(doc_id, unit, from_fact)
            unit_text = ix.unit_text(doc_id, unit) or (from_fact or {}).get("source_text", "")
            if not row.get("targets") and kind in ("REPLACES", "REMOVES") and unit not in held and from_fact is not None:
                raise_conflict(
                    "unfound target", doc_id, [from_fact["fact_id"]], f"Target not found: {_clip(unit_text)}",
                    f"{doc_id} changes something, but no earlier part could be found for \"{_clip(unit_text, 120)}\". Nothing was applied.",
                    [_option("Nothing to change", "The earlier text is not in the bid."), _option("Ask the buyer", question=True)],
                )
            for t in row.get("targets") or []:
                tdoc, tunit = t["doc_id"], t["unit"]
                if tdoc not in facts:
                    continue
                rid = relation_id(doc_id, unit, kind, tdoc, tunit)
                if rid in rejected:
                    continue
                heading = ix.kind_of(tdoc, tunit) == "heading"
                sec = ix.section(tdoc, tunit) if heading else None
                targets = ix.facts_in(tdoc, sec[1]) if sec else ix.by_unit.get((tdoc, tunit), [])[:1]
                for tf in targets or [None]:
                    entry = {
                        "id": rid, "kind": kind, "from": {"doc_id": doc_id, "unit": unit, "fact_id": from_fact["fact_id"] if from_fact else ""},
                        "to": {"doc_id": tdoc, "unit": tunit, "fact_id": tf["fact_id"] if tf else ""}, "rejected": False,
                    }
                    for end in (from_fact, tf):
                        if end is not None:
                            end.setdefault("relations", []).append(copy.deepcopy(entry))
                if not targets:
                    continue
                # a later buyer document that replaces, removes or confirms the buyer's fact settles an open conflict about it
                if new_level == 1 and kind in SETTLING:
                    for c in conflicts.values():
                        if (c["reason"] == "levels disagree" and not c["closed_by"] and ix.pos[c["doc_id"]] < ix.pos[doc_id]
                                and any(tf["fact_id"] in c["fact_ids"] for tf in targets)):
                            c["closed_by"] = doc_id
                if kind not in CHANGING:
                    continue
                for tf in targets:
                    if tf is from_fact:
                        continue
                    old_level = int(tf.get("level") or 1)
                    o = outcome(
                        new_level, old_level, ix.pos[doc_id] > ix.pos[tdoc], _says_old(precedence, tdoc, doc_id),
                        together=new_level == 1 and old_level == 1 and ix.together(doc_id, tdoc),
                    )
                    ids = [tf["fact_id"], *([from_fact["fact_id"]] if from_fact else [])]
                    old_text, new_text = _clip(tf["text"]), _clip(unit_text)
                    if o == "replace":
                        if tf["fact_id"] in edited:
                            raise_conflict(
                                "user-edited fact replaced", doc_id, ids, f"You edited a fact that {doc_id} replaces: {old_text}",
                                f"{doc_id} says \"{_clip(unit_text, 120)}\", which replaces a fact you changed.",
                                [_option("Use the new document's fact (mark mine replaced)", new_text, [_replace_change(tf)]),
                                 _option("Keep my edit", old_text)],
                            )
                            continue
                        mark(tf, from_fact, kind)
                        if not heading:
                            s = ix.section(tdoc, tunit)
                            if s:
                                partial.append((tdoc, s[0], s[1]))
                    elif o == "keep-old":
                        if from_fact is not None:  # the order of precedence puts the earlier document first
                            mark(from_fact, tf, "REPLACES")
                    elif o == "q-fact":
                        raise_conflict(
                            "issued together", doc_id, ids, f"{doc_id} and {tdoc} disagree: {old_text}",
                            f"Both were issued together, so neither replaces the other: \"{_clip(unit_text, 120)}\" against \"{_clip(tf['text'], 120)}\".",
                            [_option(f"Rely on {tdoc}", old_text, [_replace_change(from_fact)] if from_fact else []),
                             _option(f"Rely on {doc_id}", new_text, [_replace_change(tf)]),
                             _option("Ask the buyer", question=True)],
                        )
                    else:  # conflict: a call or a note against another fact
                        raise_conflict(
                            "levels disagree", doc_id, ids, f"{doc_id} disagrees with {tdoc}: {old_text}",
                            f"{doc_id} says \"{_clip(unit_text, 120)}\"; {tdoc} says \"{_clip(tf['text'], 120)}\". Both are kept until you choose.",
                            [_option(f"Keep the {tdoc} fact", old_text),
                             _option(f"Rely on {doc_id} (mark the {tdoc} fact replaced)", new_text, [_replace_change(tf)]),
                             _option("Ask the buyer", question=True)],
                        )
    for tdoc, _, section in partial:  # some of a section changed, its heading did not
        for f in ix.facts_in(tdoc, section):
            if "replaced" not in f.get("flags", []):
                f["stale"] = STALE
    return Applied([f for fs in facts.values() for f in fs], list(conflicts.values()))


__all__ = ["Applied", "outcome", "apply", "relation_id", "conflict_id", "REASONS", "STALE"]

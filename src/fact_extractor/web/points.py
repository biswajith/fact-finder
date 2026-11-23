"""A fact is one part of a "point": the rest of its list or table, the facts of other documents linked
to it, and the conflicts about it. The chat's `search` and `get_fact` return the whole point, so the
model never answers from one row of eight, or from one side of a disagreement.

Pure code over plain data: no model, no file, no web server. The caller passes the facts it has.
"""

from __future__ import annotations

from .runs import document_order

PLAYBOOK_NAMES = {
    "rfp": "RFP", "reissued-rfp": "reissued RFP", "change-addendum": "change addendum", "qa-addendum": "Q&A addendum",
    "fill-in-template": "fill-in template", "call-transcript": "call transcript", "deal-notes": "deal notes",
}
_SIDES = {"buyer": "buyer", "other-buyer": "the buyer's adviser", "ours": "our side", "other": "another party"}

# a relation as the member of the point sees it: the member is the `to` end, or the `from` end
_TO_END = {"REPLACES": "replaced by", "REMOVES": "removed by", "CONFIRMS": "confirmed by", "CLARIFIES": "clarified by",
           "DISAGREES": "disagreed with by", "ADDS": "added to by"}
_FROM_END = {"REPLACES": "replaces", "REMOVES": "removes", "CONFIRMS": "confirms", "CLARIFIES": "clarifies",
             "DISAGREES": "disagrees with", "ADDS": "adds to"}
_FIRST = ("DISAGREES", "REPLACES")  # the kinds that decide an answer: listed first when the cap cuts


def _playbook_name(key: str) -> str:
    name = str(key or "").split("@")[0]
    return PLAYBOOK_NAMES.get(name, name.replace("-", " "))


def source_label(fact: dict, documents: dict[int, dict]) -> str:
    """Where a fact comes from, for the model to read: the document, its type and, for a call, the
    side that was speaking. "" for a single-document run (`documents` empty) or an unknown document."""
    no = fact.get("doc_no")
    doc = documents.get(no) if documents and no else None
    if doc is None:
        return ""
    playbook = str(doc.get("playbook") or fact.get("playbook") or "").split("@")[0]
    name = _playbook_name(playbook)
    level = fact.get("level")
    lv = f"level {level}" if level else ""
    if playbook == "call-transcript":
        sides = list(dict.fromkeys(_SIDES[c["side"]] for c in fact.get("citations") or [] if c.get("side") in _SIDES))
        who = (" and ".join(sides) + " speaking") if sides else "speaker's side not known"
        return f"d{no} {name}, {who}" + (f" ({lv})" if lv else "")
    if playbook == "deal-notes":
        return f"d{no} {name} (our own notes" + (f", {lv}" if lv else "") + ")"
    return f"d{no} {name} (buyer document" + (f", {lv}" if lv else "") + ")"


def brief(f: dict, documents: dict[int, dict] | None = None) -> dict:
    """A fact in a line of keys. `source`, `replaced` and `stale` are there only when they apply."""
    page = f["citations"][0]["page_label"] if f["citations"] else None
    out = {"fact_id": f["fact_id"], "category": f["category"], "flags": f["flags"], "status": f["status"],
           "text": f["text"], "page": page, "edited": f["edited"], "deleted": f["deleted"]}
    source = source_label(f, documents or {})
    if source:
        out["source"] = source
    if "replaced" in f["flags"]:
        out["replaced"] = True
    if f.get("stale"):
        out["stale"] = f["stale"]
    return out


def _members(fact: dict, facts_by_id: dict[str, dict]) -> tuple[str, str, list[dict]]:
    gid, kind = fact.get("group_id") or "", fact.get("group_kind") or ""
    if gid and kind in ("list", "same"):
        found = [f for f in facts_by_id.values() if f.get("group_id") == gid and not f.get("deleted")]
        if not any(f["fact_id"] == fact["fact_id"] for f in found):
            found.append(fact)
        found = document_order(found)
        if len(found) > 1:
            return kind, fact.get("group_title") or "", found
    return "fact", "", [fact]


def point(fact: dict, facts_by_id: dict[str, dict], conflicts: list[dict], documents: dict[int, dict] | None = None,
          *, max_linked: int = 12) -> dict:
    """The complete thing `fact` belongs to: its group's members (a list or table, or one point
    restated), the facts linked to any member by a relation that stands (one hop, not followed
    further), and the open conflicts that name a member. `more_linked` appears when the cap cut."""
    documents = documents or {}
    kind, title, members = _members(fact, facts_by_id)
    ids = {m["fact_id"] for m in members}
    found: list[tuple[int, int, dict]] = []
    seen: set[tuple] = set()
    for m in members:
        for r in m.get("relations") or []:
            if r.get("rejected"):
                continue
            to_end = (r.get("to") or {}).get("fact_id") == m["fact_id"]
            from_end = (r.get("from") or {}).get("fact_id") == m["fact_id"]
            if not (to_end or from_end):
                continue
            other_id = (r["from"] if to_end else r["to"]).get("fact_id")
            other = facts_by_id.get(other_id or "")
            words = (_TO_END if to_end else _FROM_END).get(r.get("kind"))
            if other is None or other.get("deleted") or other_id in ids or words is None:
                continue
            key = (m["fact_id"], other_id, words)
            if key in seen:
                continue
            seen.add(key)
            entry: dict = {"relation": words}
            if len(members) > 1:
                entry["of"] = m["fact_id"]
            entry["fact"] = brief(other, documents)
            found.append((0 if r.get("kind") in _FIRST else 1, len(found), entry))
    found.sort(key=lambda t: t[:2])
    out = {
        "kind": kind, "title": title, "members": [brief(m, documents) for m in members],
        "linked": [e for _, _, e in found[:max_linked]],
        "conflicts": [{"id": c["id"], "title": c["title"], "status": c["status"]}
                      for c in conflicts if c.get("status") == "open" and ids & set(c.get("fact_ids") or [])],
    }
    if len(found) > max_linked:
        out["more_linked"] = len(found) - max_linked
    return out


def point_parts(p: dict, fact_id: str) -> dict:
    """The keys a hit or a fact carries from its point: `list` or `same` (title and the other members),
    `linked`, `more_linked` and `conflicts`; keys with nothing in them are left out."""
    out: dict = {}
    if p["kind"] in ("list", "same"):
        out[p["kind"]] = {"title": p["title"], "items": [m for m in p["members"] if m["fact_id"] != fact_id]}
    if p["linked"]:
        out["linked"] = p["linked"]
        if p.get("more_linked"):
            out["more_linked"] = p["more_linked"]
    if p["conflicts"]:
        out["conflicts"] = p["conflicts"]
    return out

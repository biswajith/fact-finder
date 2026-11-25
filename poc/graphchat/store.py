"""The deal graph as a store a chat agent reads and changes: nodes, fields with claims, links.

Loaded from web/mock/graph/durham.graph.json (the hand-built end state). Each field keeps its current
value, the values it beat (`competing`) and its own history of changes made in chat, so a change is one
write to one field and every read after it sees the new value. Nothing here calls a model.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GRAPH = ROOT / "web" / "mock" / "graph" / "durham.graph.json"

STOP = set("a an the of to and or for in on at is are was be by with what who when how do does our we us i me "
           "show tell about which where it its this that from as".split())


def words(s: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9$.%]+", " ", s.lower()).split() if len(w) > 1 and w not in STOP]


class GraphError(ValueError):
    pass


class GraphStore:
    def __init__(self, path: Path = GRAPH) -> None:
        g = json.loads(path.read_text(encoding="utf-8"))
        self.g = copy.deepcopy(g)
        self.nodes: dict[str, dict] = {n["id"]: n for n in self.g["nodes"]}
        for n in self.nodes.values():
            for f in n["fields"]:
                f.setdefault("history", [])
        self.changes: list[dict] = []  # every write, in order: what the eval checks

    # ---------------------------------------------------------------- reading
    def doc_name(self, no: int) -> str:
        return next((d["name"] for d in self.g["documents"] if d["no"] == no), f"doc {no}")

    def source(self, fid: str) -> str:
        f = self.g["facts"].get(fid)
        if not f:
            return fid
        where = f"p{f['page']}" if f["page"] not in ("", "0") else (f["section"][:24] or "")
        return " ".join(x for x in (self.doc_name(f["doc"]), where) if x)

    def sources(self, ids: list[str]) -> list[str]:
        return list(dict.fromkeys(self.source(i) for i in ids))

    def index(self) -> str:
        """One line per node: what the agent sees in its system prompt, so it can open nodes by ID."""
        types = self.g["types"]
        lines = [f"{n['id']} | {types.get(n['type'], {}).get('name', n['type'])} | {n['label']}"
                 + (f" — {n['sub']}" if n["sub"] else "") + (f" [{n['status']}]" if n["status"] != "live" else "")
                 + (f" | fields: {', '.join(f['name'] for f in n['fields'])}" if n["fields"] else "")
                 + (f" | lists: {', '.join(l['name'] for l in n['lists'])}" if n["lists"] else "")
                 for n in self.nodes.values()]
        return "\n".join(lines)

    def lenses(self) -> str:
        return "\n".join(f"{l['key']}: {l['title']} (rows: {', '.join(r['row'] for r in l['rows'])})" for l in self.g["lenses"])

    def label(self, nid: str) -> str:
        n = self.nodes.get(nid)
        return n["label"] if n else nid

    def node_view(self, nid: str) -> dict:
        n = self.nodes.get(nid)
        if n is None:
            raise GraphError(f"no node {nid!r}; use an ID from the index")
        out: dict[str, Any] = {"id": nid, "type": n["type"], "label": n["label"], "sub": n["sub"]}
        if n["status"] != "live":
            out["status"] = n["status"]
        if n.get("note"):
            out["note"] = n["note"]
        fields = []
        for f in n["fields"]:
            row: dict[str, Any] = {"field": f["name"], "value": f["value"], "sources": self.sources(f["facts"])}
            if f["status"] != "none":
                row["status"] = f["status"]
            if f.get("reason"):
                row["why"] = f["reason"]
            if f["competing"]:
                row["lost_or_other_values"] = [{"value": c["value"], "sources": self.sources(c["facts"])} for c in f["competing"]]
            if f["history"]:
                row["earlier_values"] = f["history"]
            elif f.get("key"):  # a keyed value is short: the sentences it came from carry its conditions
                row["the_sources_say"] = [self.g["facts"][i]["text"] for i in f["facts"] if i in self.g["facts"]][:4]
            fields.append(row)
        if fields:
            out["fields"] = fields
        if not fields and n["facts"]:
            out["sources"] = self.sources(n["facts"])
            out["what_the_sources_say"] = [self.g["facts"][i]["text"] for i in n["facts"] if i in self.g["facts"]][:6]
        for l in n["lists"]:
            out.setdefault("lists", {})[l["name"]] = [
                {"item": self.item_text(i), "sources": self.sources(i["facts"])} for i in l["items"]]
        links = [f"{l['edge']} → {l['to']} ({self.label(l['to'])})" for l in self.g["links"] if l["from"] == nid]
        links += [f"← {l['edge']} from {l['from']} ({self.label(l['from'])})" for l in self.g["links"] if l["to"] == nid]
        if links:
            out["links"] = links
        return out

    def item_text(self, item: dict) -> str:
        """A list item as read now. A sentence that states a keyed value (`ref`: node, field) is the source's
        wording only while that value stands; once the value was changed in chat the item shows the field."""
        ref = item.get("ref")
        if ref and ref[0] in self.nodes:
            f = next((x for x in self.nodes[ref[0]]["fields"] if x["name"] == ref[1]), None)
            if f is not None and f.get("history"):
                return f"{self.nodes[ref[0]]['label']}, {f['name'].lower()}: {f['value']} (changed in chat; see {ref[0]})"
        return item["value"]

    def find(self, query: str, type_: str | None = None, limit: int = 10) -> dict:
        q = words(query)
        if not q:
            raise GraphError("empty query")

        def score(text: str) -> float:
            t = set(words(text))
            return sum(1.0 if w in t else 0.5 if any(x.startswith(w) for x in t) else 0 for w in q)

        hits = []
        for n in self.nodes.values():
            if type_ and n["type"] != type_:
                continue
            body = " ".join([n["label"], n["sub"], *(f"{f['name']} {f['value']}" for f in n["fields"]),
                             *(self.item_text(i) for l in n["lists"] for i in l["items"])])
            s = score(n["label"]) * 2 + score(body)
            if s > 0:
                hits.append((s, {"id": n["id"], "type": n["type"], "label": n["label"], "sub": n["sub"]}))
        hits.sort(key=lambda h: -h[0])
        # Facts the graph does not hold as a value (filler, pointers) are searched too, so nothing is unreachable.
        loose = sorted(((score(f["text"]), fid) for fid, f in self.g["facts"].items() if not f["used"]), reverse=True)
        return {"nodes": [h for _, h in hits[:limit]],
                "facts_not_in_graph": [{"text": self.g["facts"][fid]["text"], "source": self.source(fid)}
                                       for s, fid in loose[:3] if s >= 1.5]}

    def view(self, key: str) -> dict:
        lens = next((l for l in self.g["lenses"] if l["key"] == key), None)
        if lens is None:
            raise GraphError(f"no view {key!r}")
        return {"view": lens["title"], "rows": [{"row": r["row"], "summary": r["text"],
                                                  "nodes": [f"{i} ({self.label(i)})" for i in r["nodes"]]} for r in lens["rows"]]}

    def review(self) -> dict:
        out: dict[str, list] = {"needs_a_person": [], "not_final": [], "settled_by_ranking": []}
        for n in self.nodes.values():
            for f in n["fields"]:
                key = {"needs_review": "needs_a_person", "tentative": "not_final", "expired": "not_final",
                       "auto_resolved": "settled_by_ranking", "decided": "settled_by_ranking"}.get(f["status"])
                if key:
                    out[key].append({"node": n["id"], "label": n["label"], "field": f["name"], "value": f["value"],
                                     "why": f.get("reason", ""),
                                     "other_values": [c["value"] for c in f["competing"]]})
        if self.g.get("conflicts"):  # disagreements between statements that are not values of a key
            out["other_open_conflicts"] = self.g["conflicts"]
        return out

    # ---------------------------------------------------------------- writing
    def _field(self, nid: str, name: str, create: bool = False) -> dict:
        n = self.nodes.get(nid)
        if n is None:
            raise GraphError(f"no node {nid!r}")
        f = next((x for x in n["fields"] if x["name"].lower() == name.lower()), None)
        if f is None:
            if not create:
                names = ", ".join(x["name"] for x in n["fields"]) or "none"
                raise GraphError(f"node {nid} has no field {name!r}; its fields: {names}. Pass new_field: true to add one.")
            f = {"name": name, "value": "", "facts": [], "status": "none", "reason": "", "competing": [], "history": []}
            n["fields"].append(f)
        return f

    def set_field(self, nid: str, field: str, value: str, kind: str, why: str, new_field: bool = False) -> dict:
        """kind: correction (the extraction misread the document: the value is replaced, its sources stay),
        update (new information from the buyer or the team: the new value wins over the documents, the old
        one is kept as an earlier value), decision (the customer chose between values the sources disagree on)."""
        if kind not in ("correction", "update", "decision"):
            raise GraphError("kind must be correction, update or decision")
        f = self._field(nid, field, create=new_field)
        old = f["value"]
        if value.strip().lower() == old.strip().lower() and kind != "decision":
            return {"ok": True, "unchanged": True, "note": "The field already holds that value; nothing was written."}
        if kind == "correction":
            f["history"].append({"value": old, "change": "corrected in chat", "why": why})
            f["value"] = value
            f["reason"] = f"Corrected by the bid team: {why}" if why else "Corrected by the bid team."
            f["status"] = "decided"
        elif kind == "update":
            if old:
                f["history"].append({"value": old, "change": "replaced by newer information", "why": why})
            f["value"] = value
            f["reason"] = f"Newer information from the bid team or buyer: {why}" if why else "Newer information."
            f["status"] = "decided"
        else:
            # A decision picks one of the values the sources gave; the winner's sources come with it.
            pick = next((c for c in f["competing"] if c["value"].lower() == value.lower()), None)
            if pick is not None:
                f["competing"].remove(pick)
                f["competing"].append({"value": old, "facts": f["facts"]})
                f["value"], f["facts"] = pick["value"], pick["facts"]
            elif value.lower() != old.lower():
                f["history"].append({"value": old, "change": "decided against", "why": why})
                f["value"] = value
            f["status"] = "decided"
            f["reason"] = f"Decided by the bid team: {why}" if why else "Decided by the bid team."
        # The subtitle in the index shows the node's main field; it must not keep showing the old value.
        if self.nodes[nid]["fields"] and self.nodes[nid]["fields"][0] is f:
            self.nodes[nid]["sub"] = f["value"][:60]
        if self.nodes[nid]["status"] == "tentative" and kind != "correction":
            self.nodes[nid]["status"] = "live"
        change = {"op": "set_field", "node": nid, "field": f["name"], "old": old, "new": f["value"], "kind": kind, "why": why}
        self.changes.append(change)
        return {"ok": True, **change}

    def add_note(self, nid: str, text: str) -> dict:
        if nid not in self.nodes:
            raise GraphError(f"no node {nid!r}")
        n = self.nodes[nid]
        n["note"] = (n.get("note", "") + "\n" + text).strip()
        self.changes.append({"op": "add_note", "node": nid, "new": text})
        return {"ok": True, "node": nid, "note": n["note"]}

    def add_list_item(self, nid: str, list_name: str, value: str) -> dict:
        n = self.nodes.get(nid)
        if n is None:
            raise GraphError(f"no node {nid!r}")
        lst = next((l for l in n["lists"] if l["name"].lower() == list_name.lower()), None)
        if lst is None:
            lst = {"name": list_name, "items": []}
            n["lists"].append(lst)
        lst["items"].append({"value": value, "facts": []})
        self.changes.append({"op": "add_list_item", "node": nid, "field": lst["name"], "new": value})
        return {"ok": True}

    def add_node(self, type_: str, label: str, sub: str, fields: dict[str, str], links: list[dict]) -> dict:
        if type_ not in self.g["types"]:
            raise GraphError(f"unknown type {type_!r}; types: {', '.join(self.g['types'])}")
        nid = "n_" + re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:30]
        while nid in self.nodes:
            nid += "_2"
        n = {"id": nid, "type": type_, "label": label, "sub": sub, "facts": [], "status": "live", "note": "",
             "fields": [{"name": k, "value": str(v), "facts": [], "status": "decided", "reason": "Added in chat.",
                         "competing": [], "history": []} for k, v in fields.items()], "lists": []}
        for l in links:
            if l.get("node_id") not in self.nodes:
                raise GraphError(f"no node {l.get('node_id')!r} to link to")
        self.nodes[nid] = n
        self.g["nodes"].append(n)
        for l in links:
            self.g["links"].append({"from": nid, "edge": l.get("edge", "about"), "to": l["node_id"], "facts": [], "status": "live"})
        self.changes.append({"op": "add_node", "node": nid, "new": label, "fields": fields})
        return {"ok": True, "id": nid}

    # ---------------------------------------------------------------- guards: code decides what is ambiguous
    @staticmethod
    def stems(text: str) -> set[str]:
        return {(w[:5] if len(w) >= 6 else w.rstrip("s")) for w in words(text) if not re.match(r"^[$\d.,%]+$", w)}

    def candidates(self, said: str, message: str = "") -> list[str]:
        """The node.fields the customer's words fit best: most naming words shared with the node and field name,
        narrowed to the fields whose value holds a figure the customer quoted, when any does."""
        toks = self.stems(said)
        scored = []
        for n in self.nodes.values():
            for f in n["fields"]:
                s = len(toks & self.stems(" ".join([n["label"], n["sub"], f["name"]])))
                if s:
                    scored.append((s, n, f))
        if not scored:
            return []
        top = max(s for s, _, _ in scored)
        best = [(n, f) for s, n, f in scored if s == top]
        figures = re.findall(r"\d[\d,.]*\d|\d", said) or re.findall(r"\d[\d,.]*\d|\d", message)
        if figures:
            with_fig = [(n, f) for n, f in best if any(x in f["value"] for x in figures)]
            best = with_fig or best
        return [f"{n['id']}.{f['name']} ({n['label']}: {f['value'][:40]})" for n, f in best]

    def check_write(self, nid: str, field: str, kind: str, message: str, target_words: str, choice_words: str) -> str | None:
        """Why a write must not happen, or None. `message` is the customer's last message."""
        low = message.lower()
        if not target_words or target_words.lower() not in low:
            return "target_words must quote the customer's own words that name what to change, exactly as in their message."
        n = self.nodes.get(nid)
        named = n is not None and bool(self.stems(n["label"]) & self.stems(message))
        # Judge the whole message, not only the words quoted: a narrower quote must not hide an ambiguous request.
        cands = max(self.candidates(target_words, message), self.candidates(message, message), key=len)
        # A field name alone does not name the target when the same words fit fields on other nodes.
        if not named and len({c.split(".")[0] for c in cands}) > 1:
            return ("Ambiguous: the customer's words fit several fields, so ask which one before changing anything: "
                    + "; ".join(cands[:12]))
        if kind == "decision":
            f = next((x for x in (n or {}).get("fields", []) if x["name"].lower() == field.lower()), None)
            if f is not None and (f["competing"] or f["status"] in ("needs_review", "auto_resolved")):
                if not choice_words or choice_words.lower() not in low:
                    return ("This field's sources disagree, and only the customer may choose. choice_words must quote their own "
                            "words stating the choice; if they did not state one, tell them what each source says and ask.")
        return None

    # ---------------------------------------------------------------- for the eval
    def text_of(self, nid: str, field: str | None = None) -> str:
        """Everything a check can look at on a node: current values, reasons and the note (not earlier values)."""
        n = self.nodes[nid]
        fs = [f for f in n["fields"] if field is None or f["name"].lower() == field.lower()]
        parts = [f"{f['name']}: {f['value']} ({f['reason']})" for f in fs]
        if field is None:
            parts += [n.get("note", "")] + [self.item_text(i) for l in n["lists"] for i in l["items"]]
        return "\n".join(parts)

    def status_of(self, nid: str, field: str) -> str:
        return self._field(nid, field)["status"]

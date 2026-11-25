"""Build a bid's deal graph from its labelled facts with a model, the way SPEC-v2's graph agent would.

    uv run python -m poc.graphchat.build                 # runs/_bids/durham -> poc/graphchat/out/durham.built.json

1. Claims. The facts go to the model in document order (issue date), in batches. For each batch it gets
   the node index built so far and returns claims: a node (an existing ID, or a type and a label), and a
   field value, a list item or only the node itself, each with the fact IDs it rests on; and links.
2. Identity. Code merges nodes: an ID wins; otherwise the same type and the same cleaned label is one node.
3. Settling. Code groups each field's claims by cleaned value, asks a text judge in one bulk call whether
   differing values mean the same thing, and settles by document rank (rfp_response profile: RFP, then
   deal notes, then call transcript; a later issue date wins inside a tier). Equal ranks that disagree
   need a person. The model never decides a conflict.
4. Views. One call per summary section picks the nodes behind each row and writes the row.

The output has the shape of web/mock/graph/durham.graph.json, so the graph chat and the page read it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from fact_extractor.cli import load_env
from fact_extractor.normalize import missing_values, values
from fact_extractor.web import model_name, pricing

ROOT = Path(__file__).resolve().parents[2]
HAND = ROOT / "web" / "mock" / "graph" / "durham.graph.json"
OUT = Path(__file__).resolve().parent / "out"

# rfp_response profile tiers (SPEC-v2 6.1) by playbook; lower is stronger.
TIER = {"rfp": 3, "addendum": 2, "buyer-qa": 2, "pricing-form": 4, "crm": 5, "deal-notes": 6, "call-transcript": 7}
BATCH = 40

TYPE_GUIDE = """deal: the bid itself (one node, id "deal"): solicitation, stage, value, our price, decisions about bidding
organization: buyer, its departments, advisors, our firm, partners
person: a named person; fields such as role, influence, stance, what they said
driver: why the buyer buys, or a buyer hot button / priority
solution: a product or service the buyer is buying (lists of components)
process: a business process or module, with user counts
system: a system the buyer uses today
phase: a phase of the work
event: a key date or deadline (field "Date" or "When"); the steps of the selection process
submission_item: what to submit and how (email, documents, forms, templates)
gate: an eligibility rule or a cause of rejection
reference: a customer reference we may use
method: how proposals are evaluated and awarded
criterion: an evaluation criterion with its weight
requirement: what the vendor must do or provide, grouped by RFP section or theme (lists of items)
contract_term: a contract term (term, termination, pricing model, price validity, law, liability, wage, EEO)
insurance: an insurance requirement with its limits
risk: a risk to the bid or the project
action: something our team must do, with owner and date
question: a question for the buyer, open or answered
competitor: a competitor"""

SYSTEM = """You build a deal graph for a bid from labelled facts. The graph holds one node per real thing (a person, an organisation, a date, a requirement group, a contract term, a risk...) and, on each node, fields with short values. Several documents talk about the same things: your job is to put each fact on the node and field it is about, so that facts from different documents about the same value land on the SAME node and field, even when they disagree. You never decide which document is right; code does that later.

Node types:
{types}

Rules:
1. Reuse nodes. When a fact is about a node already in the index, refer to it by its id. Create a node only for something not there yet, with a type from the list, a short label that names it (a person's full name, the buyer's section number and name, "Proposal due"), and a short subtitle.
2. Reuse field names. A node's existing fields are shown in the index; use the same name for the same value. Name fields in plain words ("Date", "Limit", "Role", "Full users", "Notice period").
3. One node per distinct thing: each contract term (term, termination, price validity, pricing model, governing law), each insurance cover, each key date, each requirement group, each risk is its own node named for what it is ("Price validity", "Contract term", "Cyber liability insurance"), never a field on a catch-all node such as "Resulting agreement" or "Contract". Deal-level figures (estimated value, our target price) are fields on the deal node.
4. A field holds ONE value of one thing (a date, an amount, a count, a name, a short rule). Several different statements about a node (what it covers, its parts, its duties, what someone said about it) go in a list, never in one field such as "Issue", "Risk", "Approach" or "Description" claimed several times.
5. One value per claim, short, with every figure, date, name and amount copied exactly. When a fact states several values (a date, an address and a subject line), make one claim per value, each on its own field, all citing the fact.
6. When a call or our notes state a value the RFP also states (a deadline, a user count, a term, a price validity), claim it on the same node and field as the RFP's value, even if it differs. Our own plan or assumption (what we will price, what we decided) goes on its own field, not on the buyer's value.
7. Many short items of one kind (cloud services, what a proposal must contain, what a section asks us to describe) go in a list on one node (claim with "list" and "item"), not one node each.
8. Add links generously: every person to their organisation, every department to the buyer, every date to the next date in time order, every risk to what it threatens, every action to its owner and to what it addresses, every question to what it is about, every process to the solution it runs on. Links say how nodes relate: works_at, part_of, owns, wants, decides, runs_on, replaces, covers, then (between dates in order), deadline_for, requires, must_pass, satisfies, threatens, closes, owner, about, competes_for. Link only nodes that exist or that you create in this batch.
9. Every fact must be used at least once (as a field value, a list item, a node's own fact, or a link), except pure filler (a heading, "see table 3", a question with no answer). Cite facts by their id.

Answer with one JSON object:
{{"claims": [
  {{"node": {{"id": "existing id"}} or {{"type": "...", "label": "...", "sub": "..."}}, "field": "...", "value": "...", "facts": ["id"]}},
  {{"node": {{...}}, "list": "...", "item": "...", "facts": ["id"]}},
  {{"node": {{...}}, "facts": ["id"]}}
 ],
 "links": [{{"from": {{...}}, "edge": "...", "to": {{...}}, "facts": ["id"]}}]}}"""

JUDGE = """Each item below is two short values recorded for the same field of the same thing, from different documents. Say for each whether they state the same thing or different things. Same: the same value or meaning in other words, or one is a fuller form of the other that adds no different value (2024-06-10 and 2024-06-10 at 2 pm ET; 180 days and 180 days from the due date). Different: a different date, time, amount, count, letter or rule (2 pm vs 5 pm; A vs B; 40 vs 60). Answer with JSON: {"same": [true, false, ...]} in the order given."""

LENS = """You write one summary section of a bid as rows, from the deal graph below. For each row, write the answer in one or two sentences with the figures copied exactly, and list the ids of the nodes that answer it (2 to 9, the most useful first). Use only node ids from the graph. Answer with JSON: {"rows": [{"row": "...", "text": "...", "nodes": ["id"]}]}"""


def clean(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9$%.]+", " ", str(s).lower()).split()).strip(" .")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60] or "node"


def figures(text: str) -> set[str]:
    """The values in a text, number words read too (sixty = 60); a full date also counts as its year, so
    June 2023 sits inside 2023-06-30."""
    out = set(values(text, generous=True))
    out |= {v[5:9] for v in out if v.startswith("date:")}
    return out


def competes(a: str, b: str) -> bool:
    has_figure = lambda v: bool(re.search(r"\d", v))  # noqa: E731
    short = lambda v: len(v.split()) <= 3  # noqa: E731
    return has_figure(a) or has_figure(b) or (short(a) and short(b))


class Builder:
    def __init__(self, bid: Path, reuse: bool = False) -> None:
        self.reuse = reuse  # read each batch's model answer from out/cache when it is there
        self.facts = json.loads((bid / "facts.json").read_text())
        manifest = json.loads((bid / "bid.json").read_text())
        self.docs = sorted(manifest["documents"], key=lambda d: d.get("issue_date") or "")
        self.step = {d["no"]: i for i, d in enumerate(self.docs)}
        self.doc = {d["no"]: d for d in self.docs}
        self.by_short = {f["fact_id"][2:]: f for f in self.facts}
        self.nodes: dict[str, dict] = {"deal": {"id": "deal", "type": "deal", "label": manifest.get("name") or "Deal",
                                                "sub": "", "facts": set()}}
        self.keys: dict[str, str] = {"deal|deal": "deal"}
        self.claims: list[dict] = []   # {node, field, value, facts}
        self.items: list[dict] = []    # {node, list, item, facts}
        self.links: list[dict] = []
        self.usage = {"calls": 0, "input": 0, "cached": 0, "output": 0, "usd": 0.0, "seconds": 0.0}
        self.problems: list[str] = []
        self.to_list = 0  # differing statements on one field turned into list items
        self.dropped = 0  # cited facts dropped from claims because they do not state the value
        import openai
        self.client = openai.AsyncOpenAI(timeout=300, max_retries=2)

    # ---------------------------------------------------------------- model calls
    async def ask(self, system: str, user: str, effort: str = "medium") -> dict:
        t = time.monotonic()
        r = await self.client.chat.completions.create(
            model=model_name(), reasoning_effort=effort, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], max_completion_tokens=32000)
        u = r.usage
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        self.usage["calls"] += 1
        self.usage["input"] += u.prompt_tokens
        self.usage["cached"] += cached
        self.usage["output"] += u.completion_tokens
        self.usage["usd"] += pricing.cost(pricing.CHAT, model_name(), u.prompt_tokens, cached, u.completion_tokens) or 0
        self.usage["seconds"] += time.monotonic() - t
        try:
            return json.loads(r.choices[0].message.content or "{}")
        except json.JSONDecodeError as e:
            self.problems.append(f"bad JSON from the model: {e}")
            return {}

    # ---------------------------------------------------------------- identity
    def index(self) -> str:
        fields: dict[str, list[str]] = {}
        for c in self.claims:
            fields.setdefault(c["node"], [])
            if c["field"] not in fields[c["node"]]:
                fields[c["node"]].append(c["field"])
        lists: dict[str, list[str]] = {}
        for i in self.items:
            lists.setdefault(i["node"], [])
            if i["list"] not in lists[i["node"]]:
                lists[i["node"]].append(i["list"])
        out = []
        for n in self.nodes.values():
            extra = ", ".join(fields.get(n["id"], []) + [f"[list] {x}" for x in lists.get(n["id"], [])])
            out.append(f"{n['id']} | {n['type']} | {n['label']}" + (f" — {n['sub']}" if n["sub"] else "") + (f" | fields: {extra}" if extra else ""))
        return "\n".join(out)

    def resolve(self, ref: Any) -> str | None:
        if not isinstance(ref, dict):
            return None
        if ref.get("id") in self.nodes:
            return ref["id"]
        if ref.get("id") and slug(str(ref["id"])) in self.nodes:  # an id the model made up for a node it created
            return slug(str(ref["id"]))
        t, label = ref.get("type"), str(ref.get("label") or "").strip()
        if t == "deal":
            return "deal"
        if t not in TYPES or not label:
            if ref.get("id"):
                self.problems.append(f"unknown node id {ref.get('id')}")
            return None
        key = f"{t}|{' '.join(sorted(clean(label).split()))}"
        if key in self.keys:
            return self.keys[key]
        nid = slug(label)
        while nid in self.nodes:
            nid += "_2"
        self.nodes[nid] = {"id": nid, "type": t, "label": label, "sub": str(ref.get("sub") or ""), "facts": set()}
        self.keys[key] = nid
        return nid

    def supporting(self, value: str, facts: list[str]) -> list[str]:
        """The cited facts that state every figure in the value (a date, an amount, a count). A claim that cites
        a fact for a figure the fact does not give would take that fact's rank; drop such facts. When no fact
        states the figures, all are kept and the problem is noted."""
        ok = [i for i in facts if not missing_values(value, [self.by_short[i]["text"]])]
        if ok and len(ok) < len(facts):
            self.dropped += len(facts) - len(ok)
        if not ok:
            self.problems.append(f"no cited fact states the figures of {value[:60]!r}")
        return ok or facts

    def known(self, ids: Any) -> list[str]:
        out = []
        for i in ids or []:
            i = str(i).removeprefix("f_")
            if i in self.by_short:
                out.append(i)
            else:
                self.problems.append(f"unknown fact id {i}")
        return out

    # ---------------------------------------------------------------- 1. claims
    async def read(self) -> None:
        order = sorted(self.facts, key=lambda f: (self.step[f["doc_no"]], (f["citations"][0]["page"] if f["citations"] else 0)))
        for b in range(0, len(order), BATCH):
            batch = order[b:b + BATCH]
            lines = []
            for f in batch:
                c = f["citations"][0] if f["citations"] else {}
                d = self.doc[f["doc_no"]]
                where = f"p{c.get('page_label')}" if c.get("page_label") not in (None, "", "0") else ""
                lines.append(f"{f['fact_id'][2:]} | {d['playbook']} {d.get('issue_date') or ''} {where} {c.get('section') or ''} | "
                             f"{f['category']}{' [' + ','.join(f['flags']) + ']' if f['flags'] else ''} | {f['text']}")
            user = (f"NODE INDEX SO FAR (id | type | label — subtitle | fields)\n{self.index()}\n\n"
                    f"FACTS (id | document, date, page, section | category [flags] | text)\n" + "\n".join(lines))
            cache = OUT / "cache" / f"batch{b // BATCH + 1:02d}.json"
            if self.reuse and cache.exists():
                out = json.loads(cache.read_text())
            else:
                out = await self.ask(SYSTEM.format(types=TYPE_GUIDE), user)
            if len(out.get("claims") or []) < len(batch) // 3:  # an empty or cut-off answer: ask once more
                self.problems.append(f"batch {b // BATCH + 1} came back with {len(out.get('claims') or [])} claims; asked again")
                out = await self.ask(SYSTEM.format(types=TYPE_GUIDE), user)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(out, ensure_ascii=False))
            n_claims = 0
            for c in out.get("claims") or []:
                nid = self.resolve(c.get("node"))
                facts = self.known(c.get("facts"))
                if not nid or not facts:
                    continue
                if c.get("field") and c.get("value") not in (None, ""):
                    facts = self.supporting(str(c["value"]), facts)
                    self.claims.append({"node": nid, "field": str(c["field"]).strip(), "value": str(c["value"]).strip(), "facts": facts})
                elif c.get("list") and c.get("item"):
                    self.items.append({"node": nid, "list": str(c["list"]).strip(), "item": str(c["item"]).strip(), "facts": facts})
                else:
                    self.nodes[nid]["facts"].update(facts)
                n_claims += 1
            for l in out.get("links") or []:
                a, z = self.resolve(l.get("from")), self.resolve(l.get("to"))
                if a and z and a != z:
                    self.links.append({"from": a, "edge": str(l.get("edge") or "about"), "to": z, "facts": self.known(l.get("facts"))})
            print(f"  batch {b // BATCH + 1}/{-(-len(order) // BATCH)}: {n_claims} claims, {len(self.nodes)} nodes so far", flush=True)

    # ---------------------------------------------------------------- 2 and 3. settle
    def rank(self, facts: list[str]) -> tuple[int, str]:
        """The strongest source of a claim: (tier, minus issue date), smaller is stronger."""
        best = None
        for i in facts:
            d = self.doc[self.by_short[i]["doc_no"]]
            r = (TIER.get(d["playbook"], 9), "".join(chr(255 - ord(ch)) for ch in (d.get("issue_date") or "")))
            best = r if best is None or r < best else best
        return best or (9, "")

    async def settle(self) -> dict[tuple[str, str], dict]:
        groups: dict[tuple[str, str], dict[str, dict]] = {}
        for c in self.claims:
            g = groups.setdefault((c["node"], c["field"].lower()), {})
            k = clean(c["value"])
            if k not in g:
                g[k] = {"value": c["value"], "facts": [], "name": c["field"]}
            g[k]["facts"] += [x for x in c["facts"] if x not in g[k]["facts"]]
        # Pairs code can settle: both hold figures and one's figures are all in the other (3 years = Three years;
        # June 2023 is a less specific 2023-06-30). The rest go to the judge in one bulk call.
        pairs, where, by_code = [], [], []
        for key, g in groups.items():
            ks = list(g)
            for i in range(len(ks)):
                for j in range(i + 1, len(ks)):
                    a, z = g[ks[i]]["value"], g[ks[j]]["value"]
                    va, vz = figures(a), figures(z)
                    if va and vz and (va <= vz or vz <= va):
                        by_code.append((key, ks[i], ks[j]))
                        continue
                    if bool(va) != bool(vz):  # a figure or date against none (TBD): never the same; no judge
                        continue
                    pairs.append((a, z))
                    where.append((key, ks[i], ks[j]))
        same: list[bool] = []
        for b in range(0, len(pairs), 50):
            chunk = pairs[b:b + 50]
            text = "\n".join(f"{i + 1}. A: {a}\n   B: {z}" for i, (a, z) in enumerate(chunk))
            out = await self.ask(JUDGE, text, effort="low")
            got = [bool(x) for x in (out.get("same") or [])]
            same += (got + [False] * len(chunk))[:len(chunk)]
        self.judge_pairs = len(pairs)
        parent: dict[tuple, tuple] = {}

        def find(x):
            while parent.get(x, x) != x:
                x = parent[x]
            return x
        for (key, a, z), s in [*zip(where, same), *((w, True) for w in by_code)]:
            if s:
                parent[find((key, z))] = find((key, a))
        self.same_by_code = len(by_code)
        settled = {}
        for key, g in groups.items():
            merged: dict[tuple, dict] = {}
            for k, v in g.items():
                root = find((key, k))
                m = merged.setdefault(root, {"claims": [], "facts": []})
                m["claims"].append(v)
                m["facts"] += v["facts"]
            options = []
            for m in merged.values():
                # the fullest wording among the strongest source's claims stands for the group
                best = min(m["claims"], key=lambda v: (self.rank(v["facts"]), -len(v["value"])))
                options.append({"value": best["value"], "facts": list(dict.fromkeys(m["facts"])), "rank": self.rank(m["facts"]),
                                "name": best["name"]})
            # Inside a group the fullest wording of the strongest source stands for it.
            options.sort(key=lambda o: (o["rank"], -len(o["value"])))
            win = options[0]
            # Two different values compete only when they are values of one thing: one holds a figure, a date or a
            # time, or both are a few words (A or B, must or should). Different sentences about a node are not
            # rivals: they become items of a list named after the field, and nobody is asked to choose.
            rest = [o for o in options[1:] if competes(win["value"], o["value"])]
            for o in options[1:]:
                if o not in rest:
                    self.items.append({"node": key[0], "list": win["name"], "item": o["value"], "facts": o["facts"]})
                    self.to_list += 1
            name = win["name"]
            docname = lambda o: self.doc[min((self.by_short[i] for i in o["facts"]),  # noqa: E731
                                             key=lambda f: self.rank([f["fact_id"][2:]]))["doc_no"]]["playbook"]
            if not rest:
                tentative = all("tentative" in self.by_short[i]["flags"] for i in win["facts"])
                status, reason = ("tentative", "Every source says it is not final.") if tentative else ("none", "")
            elif rest[0]["rank"] == win["rank"]:
                status = "needs_review"
                reason = f"Sources of equal rank disagree ({docname(win)}): a person must choose."
            else:
                status = "auto_resolved"
                reason = f"The {docname(win)} outranks the {', '.join(dict.fromkeys(docname(o) for o in rest))}."
            settled[key] = {"name": name, "value": win["value"], "facts": win["facts"], "status": status, "reason": reason,
                            "competing": [{"value": o["value"], "facts": o["facts"]} for o in rest]}
        return settled

    # ---------------------------------------------------------------- 4. views
    async def lenses(self, graph: dict) -> list[dict]:
        hand = json.loads(HAND.read_text())["lenses"]  # the section and row names (the summary prompts' rows)
        dump = []
        for n in graph["nodes"]:
            vals = "; ".join(f"{f['name']}: {f['value']}" for f in n["fields"])[:400]
            items = "; ".join(i["value"] for l in n["lists"] for i in l["items"])[:200]
            dump.append(f"{n['id']} | {n['type']} | {n['label']} | {vals} {('| ' + items) if items else ''}")
        text = "\n".join(dump)
        ids = {n["id"] for n in graph["nodes"]}

        async def one(lens: dict) -> dict:
            rows = [r["row"] for r in lens["rows"]] if lens["key"] != "dates" else ["One row per key date, in date order"]
            out = await self.ask(LENS, f"SECTION: {lens['title']}\nROWS: {rows}\n\nGRAPH (id | type | label | fields | list items)\n{text}", effort="low")
            got = [{"row": str(r.get("row", "")), "text": str(r.get("text", "")), "nodes": [i for i in r.get("nodes") or [] if i in ids]}
                   for r in out.get("rows") or []]
            return {"key": lens["key"], "title": lens["title"], "icon": lens["icon"], "rows": got}
        return list(await asyncio.gather(*(one(l) for l in hand)))

    # ---------------------------------------------------------------- the graph file
    async def build(self) -> dict:
        await self.read()
        settled = await self.settle()
        nodes = []
        for n in self.nodes.values():
            fields = [{"name": v["name"], "value": v["value"], "facts": v["facts"], "status": v["status"],
                       "reason": v["reason"], "competing": v["competing"]} for (nid, _), v in settled.items() if nid == n["id"]]
            lists: dict[str, dict] = {}
            for i in self.items:
                if i["node"] != n["id"]:
                    continue
                lst = lists.setdefault(i["list"].lower(), {"name": i["list"], "items": {}})
                it = lst["items"].setdefault(clean(i["item"]), {"value": i["item"], "facts": []})
                it["facts"] += [x for x in i["facts"] if x not in it["facts"]]
            nodes.append({"id": n["id"], "type": n["type"], "label": n["label"], "sub": n["sub"] or (fields[0]["value"][:50] if fields else ""),
                          "facts": sorted(n["facts"]), "fields": fields,
                          "lists": [{"name": l["name"], "items": list(l["items"].values())} for l in lists.values()],
                          "status": "tentative" if fields and all(f["status"] == "tentative" for f in fields) else "live", "note": ""})
        used = {i for n in nodes for i in n["facts"]} | {i for n in nodes for f in n["fields"] for i in f["facts"] + [x for c in f["competing"] for x in c["facts"]]} \
            | {i for n in nodes for l in n["lists"] for it in l["items"] for i in it["facts"]} | {i for l in self.links for i in l["facts"]}
        hand = json.loads(HAND.read_text())
        facts = hand["facts"]
        for k in facts:
            facts[k]["used"] = k in used
        seen, links = set(), []
        for l in self.links:
            key = (l["from"], l["edge"], l["to"])
            if key not in seen:
                seen.add(key)
                links.append({**l, "status": "live"})
        graph = {"bid": hand["bid"], "documents": hand["documents"], "types": hand["types"], "nodes": nodes, "links": links,
                 "facts": facts, "lenses": []}
        graph["lenses"] = await self.lenses(graph)
        graph["build"] = {"usage": self.usage, "judge_pairs": self.judge_pairs, "problems": self.problems[:50],
                          "facts_dropped_from_claims": self.dropped, "pairs_same_by_code": self.same_by_code, "statements_to_lists": self.to_list,
                          "facts_used": len(used), "facts_total": len(self.facts)}
        return graph


TYPES = set(json.loads(HAND.read_text())["types"])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bid", default="durham")
    ap.add_argument("--reuse", action="store_true", help="reuse the model's saved batch answers; only settling runs again")
    args = ap.parse_args()
    load_env(str(ROOT / ".env"))
    b = Builder(ROOT / "runs" / "_bids" / args.bid, reuse=args.reuse)
    g = await b.build()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{args.bid}.built.json"
    path.write_text(json.dumps(g, ensure_ascii=False, indent=1))
    st = {}
    for n in g["nodes"]:
        for f in n["fields"]:
            st[f["status"]] = st.get(f["status"], 0) + 1
    u = g["build"]["usage"]
    print(f"{len(g['nodes'])} nodes, {len(g['links'])} links, {sum(len(n['fields']) for n in g['nodes'])} fields {st}, "
          f"{g['build']['facts_used']}/{g['build']['facts_total']} facts used, {g['build']['judge_pairs']} judge pairs, "
          f"{u['calls']} calls, ${u['usd']:.4f}, {u['seconds']:.0f}s, {len(b.problems)} problems -> {path}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Run the Durham chat cases on the app's fact chat and on the graph chat, and compare. Spends API tokens.

    uv run python -m poc.graphchat.run                     # every case, both systems
    uv run python -m poc.graphchat.run --only lookup,new   # case IDs or kinds
    uv run python -m poc.graphchat.run --systems graph     # one system

The fact chat runs exactly as `fact-extractor chat-eval --modes direct` runs it (its own checks from
evals/chat/durham.yaml). The graph chat plays the same customer messages and is checked on the graph
(cases.yaml). After every case that changes something, both get a read-back question in a fresh
conversation, and the old value is counted where it still stands. Results go to poc/graphchat/out/<time>/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from fact_extractor import chateval as CE
from fact_extractor.cli import load_env
from fact_extractor.web.workspace import Workspace

from .agent import GraphChat
from .store import GraphStore

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CASES = ROOT / "evals" / "chat" / "durham.yaml"
EXTRA = HERE / "cases.yaml"


def has(p: str, text: str) -> bool:
    return re.search(p, text, re.I | re.S) is not None


@dataclass
class Row:
    case: str
    kind: str
    system: str
    passed: bool = False
    failed: list[str] = field(default_factory=list)
    messages: int = 0
    questions: int = 0
    llm_calls: int = 0
    tools: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    reply: str = ""
    changes: list[Any] = field(default_factory=list)
    readback: str = ""
    readback_ok: bool | None = None
    readback_cost_usd: float = 0.0
    stale: int | None = None
    stale_texts: list[str] = field(default_factory=list)
    skipped: bool = False


# ---------------------------------------------------------------- the fact chat (the app as it is)

def session_cost(ws: Workspace) -> tuple[int, float]:
    calls, usd = 0, 0.0
    for e in ws.chat_events(ws.chat_session()):
        if e.get("event") == "turn_end":
            calls += int(e.get("llm_calls") or 0)
            usd += float(e.get("cost_usd") or 0)
    return calls, usd


async def run_facts(case: CE.Case, expect: dict, extra: dict, models: tuple) -> Row:
    chat, summaries, model, checker = models
    tmp = Path(tempfile.mkdtemp(prefix="graphcmp_"))
    try:
        facts_path = await asyncio.to_thread(CE.copy_bid, ROOT / "runs", "durham", tmp)
        res = await CE.converse(case, expect, "direct", facts_path, chat, summaries, model, CE.planning_for("direct"), checker)
        row = Row(case.id, case.kind, "facts", res.passed, res.failed, res.messages, res.questions, res.llm_calls,
                  res.tools, res.seconds, res.cost_usd, res.turns[-1]["assistant"] if res.turns else "", res.changes)
        ws = Workspace(facts_path)
        rb = extra.get("readback")
        if rb:
            ws.clear_chat()
            text = ""
            async for ev in chat(ws, summaries, model, rb["say"], CE.planning_for("direct"), checker):
                if ev["type"] == "done":
                    text = ev["message"].get("text") or ""
            row.readback = text
            row.readback_ok = all(has(p, text) for p in rb["answer"])
            row.readback_cost_usd = session_cost(ws)[1]
        st = extra.get("stale")
        if st:
            live = [f for f in ws.state().visible() if not f.get("deleted") and "replaced" not in (f.get("flags") or [])]
            # a fact that keeps the old wording as a record but shows the current value beside it (value_now) is not stale
            hits = [f["text"] for f in live if has(st["topic"], f["text"]) and has(st["old"], f["text"]) and not f.get("value_now")]
            row.stale, row.stale_texts = len(hits), hits[:6]
        return row
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- the graph chat

def graph_checks(store: GraphStore, extra: dict) -> list[str]:
    failed = []
    for c in extra.get("graph") or []:
        nodes = c["node"] if isinstance(c["node"], list) else [c["node"]]
        texts = {n: store.text_of(n, c.get("field")) for n in nodes if n in store.nodes}
        # a value may also sit on a node linked to the mapped one (a question about it, a note): count those too
        if GRAPH_PATH:
            for n in list(texts):
                for l in store.g["links"]:
                    for other in ((l["to"],) if l["from"] == n else (l["from"],) if l["to"] == n else ()):
                        texts.setdefault(other, store.text_of(other, None) if other in store.nodes else "")
        where = f"{'/'.join(nodes)}{'.' + c['field'] if c.get('field') else ''}"
        for p in c.get("has") or []:
            if not any(has(p, t) for t in texts.values()):
                failed.append(f"{where} does not say /{p}/")
        for p in c.get("lacks") or []:
            if c.get("field") and any(has(p, f["value"]) for n in texts if n in store.nodes
                                      for f in store.nodes[n]["fields"] if f["name"].lower() == c["field"].lower()):
                failed.append(f"{where} still says /{p}/")
        sf = c.get("status_field") or c.get("field")
        if c.get("status") and sf:
            if not any(store.status_of(n, sf) == c["status"] for n in texts if any(f["name"].lower() == sf.lower() for f in store.nodes[n]["fields"])):
                failed.append(f"{where} is not {c['status']}")
    allowed = set(extra.get("allow") or [])
    if "allow" in extra or extra.get("graph"):
        for ch in store.changes:
            if ch["node"] not in allowed and not ch["node"].startswith("n_"):
                failed.append(f"changed {ch['node']} ({ch.get('field', ch['op'])}), which was not asked for")
            if ch["node"].startswith("n_") and extra.get("allow") == []:
                failed.append(f"added node {ch['node']}, which was not asked for")
    return failed


GRAPH_PATH: Path | None = None  # set by --graph: a built graph instead of the hand-built one


def all_facts(n: dict) -> set[str]:
    return set(n["facts"]) | {i for f in n["fields"] for i in f["facts"] + [x for c in f["competing"] for x in c["facts"]]} \
        | {i for l in n["lists"] for it in l["items"] for i in it["facts"]}


def mapping(hand: GraphStore, built: GraphStore) -> tuple[dict, dict]:
    """Each hand-built node and field -> the built node and field resting on the most of the same facts."""
    nodes, fields = {}, {}
    bfacts = {nid: all_facts(n) for nid, n in built.nodes.items()}
    bfields = [(nid, f["name"], set(f["facts"]) | {x for c in f["competing"] for x in c["facts"]})
               for nid, n in built.nodes.items() for f in n["fields"]]
    for hid, h in hand.nodes.items():
        hf = all_facts(h)
        best = max(bfacts.items(), key=lambda kv: (len(kv[1] & hf), -len(kv[1])), default=None)
        if best and best[1] & hf:
            nodes[hid] = best[0]
        for f in h["fields"]:
            ff = set(f["facts"]) | {x for c in f["competing"] for x in c["facts"]}
            b = max(bfields, key=lambda t: (len(t[2] & ff), -len(t[2])), default=None)
            if b and b[2] & ff:
                fields[(hid, f["name"].lower())] = (b[0], b[1])
    return nodes, fields


def translate(extra: dict, nodes: dict, fields: dict) -> dict:
    """The case's graph checks with hand-built IDs replaced by the built graph's."""
    out = dict(extra)
    checks = []
    for c in extra.get("graph") or []:
        if not isinstance(c, dict) or c.get("skip"):
            return extra
        hn = c["node"] if isinstance(c["node"], list) else [c["node"]]
        if c.get("field"):
            hits = [fields.get((h, c["field"].lower())) for h in hn]
            hits = [x for x in hits if x]
            if hits:
                # Field names differ between graphs: look at the whole mapped node, keep the status check on the field.
                checks += [{**{k: v for k, v in c.items() if k != "lacks"}, "node": [x[0] for x in hits], "field": None,
                            **({"status_field": hits[0][1]} if c.get("status") else {})}]
                if c.get("lacks"):
                    checks.append({"node": [x[0] for x in hits], "field": hits[0][1], "lacks": c["lacks"]})
                continue
        checks.append({**{k: v for k, v in c.items() if k not in ("field", "status")}, "node": [nodes.get(h, h) for h in hn]})
    if extra.get("graph"):
        out["graph"] = checks
    if "allow" in extra:
        allowed = set()
        for h in extra["allow"]:
            allowed |= {nodes.get(h, h)} | {b for (hh, _), (b, _) in fields.items() if hh == h}
        out["allow"] = sorted(allowed)
    if extra.get("stale"):
        st = extra["stale"]
        m = fields.get((st["node"], st["field"].lower()))
        out["stale"] = {**st, "node": m[0], "field": m[1]} if m else {k: v for k, v in st.items() if k not in ("node", "field")}
    return out


async def run_graph(case: CE.Case, expect: dict, extra: dict, model: Any) -> Row:
    row = Row(case.id, case.kind, "graph")
    if (extra.get("graph") or {}) == {"skip": True}:
        row.skipped, row.passed = True, True
        return row
    store = GraphStore(GRAPH_PATH) if GRAPH_PATH else GraphStore()
    if GRAPH_PATH:
        extra = translate(extra, *mapping(GraphStore(), store))
    gc = GraphChat(store, model)
    text, answered, asked_before_change = case.say, False, None
    try:
        while text and row.messages < CE.MAX_MESSAGES:
            row.messages += 1
            before = len(store.changes)
            reply = await gc.say(text)
            changed = len(store.changes) > before
            row.reply, text = reply, ""
            lines = [ln for ln in reply.splitlines() if ln.strip()]
            if not changed and lines and "?" in lines[-1]:
                row.questions += 1
                if asked_before_change is None:
                    asked_before_change = before == 0
                if not answered and (case.if_asked or not expect["asks"]):
                    answered, text = True, case.if_asked or CE.INSIST
    except Exception as e:  # one broken conversation must not stop the run
        row.failed.append(f"error: {type(e).__name__}: {e}"[:300])
    t = gc.totals
    row.llm_calls, row.tools, row.seconds, row.cost_usd = t.llm_calls, t.tools, round(t.seconds, 1), round(t.cost_usd, 6)
    row.changes = store.changes
    row.failed += [f"the reply does not say /{p}/" for p in expect["answer"] if not has(p, row.reply)]
    if expect["asks"] and not asked_before_change:
        row.failed.append("did not ask before changing")
    row.failed += graph_checks(store, extra)
    rb = extra.get("readback")
    if rb:
        g2 = GraphChat(store, model)
        row.readback = await g2.say(rb["say"])
        row.readback_ok = all(has(p, row.readback) for p in rb["answer"])
        row.readback_cost_usd = round(g2.totals.cost_usd, 6)
    st = extra.get("stale")
    if st and st.get("node"):
        try:
            v = store._field(st["node"], st["field"])["value"]
            row.stale, row.stale_texts = int(has(st["old"], v)), [v] if has(st["old"], v) else []
        except Exception:
            row.stale = None
    row.passed = not row.failed
    return row


# ---------------------------------------------------------------- report

def med(xs: list[float]) -> float:
    return round(statistics.median(xs), 2) if xs else 0.0


def report(rows: list[Row]) -> str:
    systems = [s for s in ("facts", "graph") if any(r.system == s for r in rows)]
    by = {s: [r for r in rows if r.system == s and not r.skipped] for s in systems}
    out = ["## Totals", "", "| | " + " | ".join(systems) + " |", "|---|" + "---|" * len(systems)]

    def line(name: str, f) -> None:
        out.append(f"| {name} | " + " | ".join(str(f(by[s])) for s in systems) + " |")

    line("cases passed", lambda rs: f"{sum(r.passed for r in rs)}/{len(rs)}")
    line("read-backs right after a change", lambda rs: f"{sum(bool(r.readback_ok) for r in rs if r.readback_ok is not None)}/"
         f"{sum(r.readback_ok is not None for r in rs)}")
    line("old value still stated (cases / statements)", lambda rs: f"{sum(1 for r in rs if r.stale)} / {sum(r.stale or 0 for r in rs)}")
    line("model calls, median per case", lambda rs: med([r.llm_calls for r in rs]))
    line("tool runs, median per case", lambda rs: med([r.tools for r in rs]))
    line("seconds, median per case", lambda rs: med([r.seconds for r in rs]))
    line("dollars, all cases", lambda rs: f"{sum(r.cost_usd for r in rs):.4f}")
    line("dollars, read-backs", lambda rs: f"{sum(r.readback_cost_usd for r in rs):.4f}")

    kinds = list(dict.fromkeys(r.kind for r in rows))
    out += ["", "## Passed by kind", "", "| kind | " + " | ".join(systems) + " |", "|---|" + "---|" * len(systems)]
    for k in kinds:
        out.append(f"| {k} | " + " | ".join(f"{sum(r.passed for r in by[s] if r.kind == k)}/{sum(1 for r in by[s] if r.kind == k)}"
                                            for s in systems) + " |")

    out += ["", "## By case", "", "| case | " + " | ".join(f"{s} (calls, $)" for s in systems) + " | read-back | stale |",
            "|---|" + "---|" * (len(systems) + 2)]
    for cid in dict.fromkeys(r.case for r in rows):
        cells, rbs, sts = [], [], []
        for s in systems:
            r = next((x for x in rows if x.case == cid and x.system == s), None)
            if r is None or r.skipped:
                cells.append("n/a")
                continue
            cells.append(f"{'pass' if r.passed else 'FAIL'} ({r.llm_calls}, {r.cost_usd:.4f})")
            if r.readback_ok is not None:
                rbs.append(f"{s}: {'ok' if r.readback_ok else 'WRONG'}")
            if r.stale is not None:
                sts.append(f"{s}: {r.stale}")
        out.append(f"| {cid} | " + " | ".join(cells) + f" | {'; '.join(rbs)} | {'; '.join(sts)} |")

    out += ["", "## What failed", ""]
    for r in rows:
        if not r.passed or r.readback_ok is False or r.stale:
            bits = list(r.failed)
            if r.readback_ok is False:
                bits.append(f"read-back wrong: {r.readback[:200]!r}")
            if r.stale:
                bits.append(f"still states the old value: {r.stale_texts[:3]}")
            out.append(f"- **{r.case}** [{r.system}]: " + "; ".join(bits))
    return "\n".join(out)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--systems", default="facts,graph")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--graph", default="", help="a built graph (build.py) instead of the hand-built one")
    args = ap.parse_args()
    global GRAPH_PATH
    GRAPH_PATH = Path(args.graph).resolve() if args.graph else None
    load_env(str(ROOT / ".env"))
    bid, cases = CE.load(CASES)
    only = [x for x in args.only.split(",") if x]
    if only:
        cases = [c for c in cases if c.id in only or c.kind in only]
    extra = yaml.safe_load(EXTRA.read_text()) or {}
    facts = Workspace(ROOT / "runs" / "_bids" / bid / "facts.json").state().visible()
    expects = {c.id: CE.resolve(c, facts) for c in cases}
    models = CE._live_models()
    systems = args.systems.split(",")
    gate = asyncio.Semaphore(args.parallel)
    out = HERE / "out" / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    async def one(case: CE.Case, system: str) -> Row:
        async with gate:
            ex = extra.get(case.id) or {}
            r = await (run_facts(case, expects[case.id], ex, models) if system == "facts"
                       else run_graph(case, expects[case.id], ex, models[2]))
            print(f"{case.id:28} {system:6} {'pass' if r.passed else 'FAIL'}  calls={r.llm_calls} ${r.cost_usd:.4f}"
                  + (f"  readback={'ok' if r.readback_ok else 'WRONG'}" if r.readback_ok is not None else "")
                  + (f"  stale={r.stale}" if r.stale is not None else ""), flush=True)
            return r

    rows = list(await asyncio.gather(*(one(c, s) for c in cases for s in systems)))
    (out / "results.json").write_text(json.dumps([asdict(r) for r in rows], ensure_ascii=False, indent=1, default=str))
    text = report(rows)
    (out / "report.md").write_text(text + "\n")
    print("\n" + text + f"\n\nWritten to {out}")


if __name__ == "__main__":
    asyncio.run(main())

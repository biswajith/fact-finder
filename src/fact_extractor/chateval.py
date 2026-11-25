"""Run chat cases against a bid in each planning mode and compare what came out.

A cases file (YAML, see evals/chat/durham.yaml) lists customer messages with what should be true when
the conversation ends: which facts were edited, deleted or added, which conflicts were resolved,
whether the agent had to ask first, and what the last reply must say. Every case runs once per mode
(direct, light, heavy forced, and auto, where the router picks) on its own copy of the bid, so no
case sees another's changes and the stored bid is never touched.

The runner plays the customer. A plan that waits for approval gets "Yes, go ahead."; a question gets
the case's `if_asked` once (a case that expects a question and gives none stops there). On a case
that expects a question, a plan that waits counts as asking, since nothing has changed and the
customer has a say: it is not approved, it gets `if_asked` too, or the conversation ends. So a mode
that asks when it need not costs the customer messages, and a mode that changes the wrong facts
fails the case: the report keeps the two apart.

Scored per case and mode: passed or which checks failed, the customer messages it took, plans that
waited, questions asked, model calls, tool runs, seconds and estimated dollars (from the chat
session log). `run` spends API tokens; `load` and `listing` make no model call.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import statistics
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .web import planning as P
from .web.workspace import Workspace, live_entries

MODES = ("direct", "light", "heavy", "auto")
APPROVE = "Yes, go ahead."
INSIST = "Do what I asked, as I wrote it."
MAX_MESSAGES = 5  # customer messages in one conversation, the first included
NOT_ASKED = "did not ask before changing facts"
FACT_OPS = ("edit", "delete", "add", "resolve")  # what counts as a change to the facts; raising a conflict does not


class CaseError(ValueError):
    """The cases file is wrong, or names a fact the bid does not have."""


@dataclass
class Case:
    id: str
    kind: str
    say: str
    expect: dict
    if_asked: str = ""
    on_plan: str = APPROVE


@dataclass
class Result:
    case: str
    kind: str
    mode: str
    passed: bool = False
    failed: list[str] = field(default_factory=list)  # the checks that failed, in words
    messages: int = 0  # customer messages sent
    plans_waited: int = 0
    questions: int = 0
    routed: list[str] = field(default_factory=list)  # the mode each turn ran in, with what chose it
    llm_calls: int = 0
    tools: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    error: str = ""
    turns: list[dict] = field(default_factory=list)  # {"customer", "assistant", "status"} per turn
    changes: list[dict] = field(default_factory=list)  # the live correction entries, shortened

    def record(self) -> dict:
        return dict(self.__dict__)


# --- the cases ------------------------------------------------------------------------------------


def load(path: str | Path) -> tuple[str, list[Case]]:
    """The bid a cases file is for, and its cases."""
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list) or not data.get("bid"):
        raise CaseError("a cases file needs `bid` and a list of `cases`")
    cases, seen = [], set()
    for raw in data["cases"]:
        missing = [k for k in ("id", "kind", "say") if not (isinstance(raw, dict) and raw.get(k))]
        if missing:
            raise CaseError(f"a case lacks {', '.join(missing)}: {raw!r}"[:200])
        if raw["id"] in seen:
            raise CaseError(f"two cases are named {raw['id']}")
        seen.add(raw["id"])
        unknown = set(raw.get("expect") or {}) - {"answer", "edits", "deletes", "may_edit", "adds", "resolves", "asks"}
        if unknown:
            raise CaseError(f"{raw['id']}: unknown expectation {', '.join(sorted(unknown))}")
        cases.append(Case(raw["id"], raw["kind"], " ".join(str(raw["say"]).split()), raw.get("expect") or {},
                          raw.get("if_asked") or "", raw.get("on_plan") or APPROVE))
    return str(data["bid"]), cases


def locate(facts: list[dict], where: dict, case_id: str = "") -> str:
    """The ID of the one visible fact of document `doc` whose text holds `text` (case ignored)."""
    doc, piece = where.get("doc"), str(where.get("text") or "").lower()
    if doc is None or not piece:
        raise CaseError(f"{case_id}: a fact is named by doc and text, not {where!r}")
    found = [f["fact_id"] for f in facts if f.get("doc_no") == doc and piece in str(f.get("text") or "").lower()]
    if len(found) != 1:
        raise CaseError(f"{case_id}: {len(found)} facts of document {doc} hold {where['text']!r}; it must be exactly one")
    return found[0]


def resolve(case: Case, facts: list[dict]) -> dict:
    """The case's expectations with every named fact turned into its ID."""
    e = case.expect

    def named(key: str) -> list[dict]:
        return [{**w, "fact_id": locate(facts, w, case.id)} for w in e.get(key) or []]

    out: dict[str, Any] = {"answer": list(e.get("answer") or []), "asks": bool(e.get("asks")),
                           "edits": named("edits"), "deletes": named("deletes"), "may_edit": named("may_edit"),
                           "adds": dict(e.get("adds") or {}), "resolves": dict(e.get("resolves") or {})}
    if out["resolves"].get("conflict"):
        out["resolves"]["fact_id"] = locate(facts, out["resolves"]["conflict"], case.id)
    return out


def listing(store: str | Path, path: str | Path) -> str:
    """The cases with the facts they name, to check a cases file against a bid. No model call."""
    bid, cases = load(path)
    facts = Workspace(Path(store) / "_bids" / bid / "facts.json").state().visible()
    lines = [f"{len(cases)} cases for bid {bid} ({len(facts)} facts)"]
    for c in cases:
        x = resolve(c, facts)
        ids = [w["fact_id"] for k in ("edits", "deletes", "may_edit") for w in x[k]]
        lines.append(f"  {c.id:28} {c.kind:10} {' '.join(ids)}")
    return "\n".join(lines)


# --- one conversation -----------------------------------------------------------------------------


def copy_bid(store: Path, bid: str, to: Path) -> Path:
    """Copy the bid and the runs of its documents into `to`, with a clean workspace (no corrections,
    no chat); the summaries stay. Returns the copy's facts.json."""
    src = store / "_bids" / bid
    manifest = json.loads((src / "bid.json").read_text(encoding="utf-8"))
    dst = to / "_bids" / bid
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("chat", "chat.jsonl", "corrections.jsonl"))
    for d in manifest.get("documents") or []:
        if d.get("run") and (store / d["run"]).is_dir():
            shutil.copytree(store / d["run"], to / d["run"], ignore=shutil.ignore_patterns("workspace"))
    return dst / "facts.json"


def planning_for(mode: str, approval: str = "on") -> P.Planning:
    """The planning of one mode, as `planning_from_env` builds it: a forced mode, or the router for auto."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; modes: {', '.join(MODES)}")
    approve = {"on": ("light", "heavy"), "heavy": ("heavy",), "off": ()}[approval]
    decisions = P.DecisionsRouter()
    return P.Planning(decisions if mode == "auto" else P.FixedRouter(mode), decisions, approve)


def _is_question(reply: dict, changed: bool) -> bool:
    """Whether a turn ended by asking the customer something other than "shall I go ahead": the plan
    record says so, or nothing was changed and the reply's last line is a question."""
    planning = reply.get("planning") or {}
    if planning.get("question"):
        return True
    lines = [ln for ln in str(reply.get("text") or "").splitlines() if ln.strip()]
    return not changed and bool(lines) and "?" in lines[-1]


async def converse(case: Case, expect: dict, mode: str, facts_path: Path, chat: Callable, summaries: Any, model: Any,
                   planning: P.Planning | None, checker: Any = None) -> Result:
    """Play the case's conversation on the bid at `facts_path` and score it."""
    ws = Workspace(facts_path)
    res = Result(case.id, case.kind, mode)
    text, answered, asked_before_change = case.say, False, None
    started = time.monotonic()
    try:
        while text and res.messages < MAX_MESSAGES:
            res.messages += 1
            before = len(_changes(ws))
            reply: dict = {}
            async for event in chat(ws, summaries, model, text, planning, checker):
                if event["type"] == "error":
                    res.error = str(event.get("message") or "error")[:300]
                elif event["type"] == "done":
                    reply = event["message"]
            record = reply.get("planning") or {}
            res.routed.append(f"{record.get('mode', 'direct')}/{record.get('source', '-')}")
            res.tools += len(reply.get("tools") or [])
            changed = len(_changes(ws)) > before
            status = record.get("status") or ""
            res.turns.append({"customer": text, "assistant": reply.get("text") or "", "status": status})
            text = ""
            if res.error:
                break
            if status == P.AWAITING:
                res.plans_waited += 1
                if not expect["asks"] or answered:  # once the customer has said what they meant, a plan is approved
                    text = case.on_plan
                elif not answered:  # the customer gets a say before anything changes: they do not approve, they answer
                    if asked_before_change is None:
                        asked_before_change = before == 0
                    answered, text = True, case.if_asked
            elif _is_question(reply, changed) or (not changed and reply.get("conflict_ids")):
                res.questions += 1
                if asked_before_change is None:
                    asked_before_change = before == 0
                if not answered and (case.if_asked or not expect["asks"]):
                    answered, text = True, case.if_asked or INSIST
    except Exception as e:  # one broken conversation must not stop the run
        res.error = f"{type(e).__name__}: {e}"[:300]
    res.seconds = round(time.monotonic() - started, 1)
    _totals(ws, res)
    res.changes = [_short(e) for e in live_entries(ws.log())]
    res.failed = check(expect, ws, res.turns[-1]["assistant"] if res.turns else "", bool(asked_before_change))
    if res.error:
        res.failed.insert(0, f"error: {res.error}")
    res.passed = not res.failed
    return res


def _changes(ws: Workspace) -> list[dict]:
    return [e for e in live_entries(ws.log()) if e.get("op") in FACT_OPS]


def _short(e: dict) -> dict:
    out = {k: e[k] for k in ("op", "fact_id", "conflict_id") if e.get(k)}
    fields = e.get("fields") or {}
    out.update({k: str(fields[k])[:300] for k in ("text", "note", "flags", "title", "option") if fields.get(k) is not None})
    return out


def _totals(ws: Workspace, res: Result) -> None:
    """Model calls and estimated dollars of the conversation, from its session log."""
    try:
        events = ws.chat_events(ws.chat_session())
    except Exception:
        return
    for e in events:
        if e.get("event") == "turn_end":
            totals = e.get("totals") or {}
            res.llm_calls += int(totals.get("llm_calls") or 0)
            res.cost_usd = round(res.cost_usd + float(totals.get("cost_usd") or 0), 6)


# --- scoring --------------------------------------------------------------------------------------


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I | re.S) is not None


def check(expect: dict, ws: Workspace, last_reply: str, asked_first: bool) -> list[str]:
    """The checks that failed, in words; [] when the case passed."""
    failed: list[str] = []
    state = ws.state()
    live = live_entries(ws.log())
    own = [e for e in live if not e.get("conflict_id")]  # a resolved conflict's own changes are part of resolving it
    # an edit that writes back what the fact already said changes nothing, and is not held against the agent
    edited = {e["fact_id"] for e in own if e.get("op") == "edit" and e.get("fields") != state.before.get(e["id"])}
    deleted = {e["fact_id"] for e in own if e.get("op") == "delete"}
    added = [e for e in own if e.get("op") == "add"]
    resolved = {e["conflict_id"] for e in live if e.get("op") == "resolve"}

    for p in expect["answer"]:
        if not _has(p, last_reply):
            failed.append(f"the reply does not say /{p}/")
    if expect["asks"] and not asked_first:
        failed.append(NOT_ASKED)

    for w in expect["edits"]:
        fact = state.get(w["fact_id"]) or {}
        if w["fact_id"] not in edited:
            failed.append(f"did not edit {w['fact_id']} ({w['text']})")
            continue
        body = f"{fact.get('text') or ''}\n{fact.get('note') or ''}"
        failed += [f"{w['fact_id']} does not say /{p}/ after the edit" for p in w.get("has") or [] if not _has(p, body)]
        failed += [f"{w['fact_id']} still says /{p}/" for p in w.get("lacks") or [] if _has(p, body)]
    for w in expect["deletes"]:
        if w["fact_id"] not in deleted:
            failed.append(f"did not delete {w['fact_id']} ({w['text']})")

    allowed = {w["fact_id"] for k in ("edits", "deletes", "may_edit") for w in expect[k]}
    for fid in sorted((edited | deleted) - allowed):
        fact = state.get(fid) or {}
        what = "deleted" if fid in deleted else "edited"
        failed.append(f"{what} {fid}, which was not asked for (document {fact.get('doc_no')}: {str(fact.get('text') or '')[:80]})")

    adds = expect["adds"]
    low, high = int(adds.get("min", 0)), int(adds.get("max", adds.get("min", 0)))
    if not low <= len(added) <= high:
        failed.append(f"added {len(added)} facts, expected {low}" + (f" to {high}" if high != low else ""))
    texts = "\n".join(str((e.get("fields") or {}).get("text") or "") for e in added)
    failed += [f"no added fact says /{p}/" for p in adds.get("has") or [] if added and not _has(p, texts)]

    want = expect["resolves"]
    low, high = int(want.get("min", 0)), int(want.get("max", want.get("min", 0)))
    if not low <= len(resolved) <= high:
        failed.append(f"resolved {len(resolved)} conflicts, expected {low}" + (f" to {high}" if high != low else ""))
    if want.get("fact_id") and resolved:
        holds = {c["id"] for c in state.conflicts if want["fact_id"] in (c.get("fact_ids") or [])}
        if not resolved & holds:
            failed.append(f"resolved another conflict than the one about {want['fact_id']}")
        elif resolved - holds:
            failed.append("resolved a conflict that was not asked about")
    return failed


# --- the run and its report -----------------------------------------------------------------------


async def run(store: str | Path, path: str | Path, modes: tuple[str, ...] = MODES, only: list[str] | None = None,
              approval: str = "on", repeat: int = 1, parallel: int = 4, out: str | Path | None = None,
              models: Callable[[], tuple] | None = None, on_result: Callable[[Result], None] | None = None) -> list[Result]:
    """Run every case in every mode, each on its own copy of the bid. Spends API tokens.

    `only` keeps the cases whose ID or kind is listed. `models` returns (chat function, summaries,
    chat model, checker) and is how tests pass scripted ones; `planning_for` gives each mode's planning.
    With `out`, each conversation's session log is kept there and `results.json` holds every result."""
    store = Path(store)
    bid, cases = load(path)
    if only:
        cases = [c for c in cases if c.id in only or c.kind in only]
    facts = Workspace(store / "_bids" / bid / "facts.json").state().visible()
    expects = {c.id: resolve(c, facts) for c in cases}  # fails here, before any model call, on a wrong cases file
    chat, summaries, model, checker = (models or _live_models)()
    out_dir = Path(out) if out else None
    gate = asyncio.Semaphore(max(1, parallel))

    async def one(case: Case, mode: str, n: int) -> Result:
        async with gate:
            tmp = Path(tempfile.mkdtemp(prefix="chateval_"))
            try:
                facts_path = await asyncio.to_thread(copy_bid, store, bid, tmp)
                res = await converse(case, expects[case.id], mode, facts_path, chat, summaries, model,
                                     planning_for(mode, approval), checker)
                if out_dir:
                    logs = facts_path.parent / "workspace" / "chat"
                    if logs.is_dir():
                        shutil.copytree(logs, out_dir / "logs" / f"{case.id}.{mode}.{n}", dirs_exist_ok=True)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            if on_result:
                on_result(res)
            return res

    results = list(await asyncio.gather(*(one(c, m, n) for c in cases for m in modes for n in range(1, repeat + 1))))
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "results.json").write_text(json.dumps([r.record() for r in results], ensure_ascii=False, indent=1),
                                              encoding="utf-8")
        (out_dir / "report.txt").write_text(report(results) + "\n", encoding="utf-8")
    return results


def _live_models() -> tuple:
    from .web.agent import OpenAIChatModel, chat
    from .web.consistency import ConsistencyChecker
    from .web.summaries import SummaryService

    class NoRebuild(SummaryService):
        """Summaries are read as stored and not rebuilt after a change: a rebuild runs in the background,
        outlives the copy of the bid, and is not part of what the modes are compared on."""

        def notify_change(self, ws: Workspace) -> None:
            pass

    return chat, NoRebuild(), OpenAIChatModel(), ConsistencyChecker()


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 2) if values else 0.0


def report(results: list[Result]) -> str:
    """Three tables: each mode's totals, passes by kind of case, and every case by mode."""
    modes = [m for m in MODES if any(r.mode == m for r in results)]
    by_mode = {m: [r for r in results if r.mode == m] for m in modes}
    lines = ["BY MODE", f"{'mode':8}{'passed':>9}{'messages':>10}{'plans':>7}{'questions':>11}{'calls':>7}{'seconds':>9}{'dollars':>10}",
             "        (messages, calls and seconds are the median per case; plans, questions and dollars are totals)"]
    for m, rs in by_mode.items():
        lines.append(f"{m:8}{sum(r.passed for r in rs):>5}/{len(rs):<3}{_median([r.messages for r in rs]):>10}"
                     f"{sum(r.plans_waited for r in rs):>7}{sum(r.questions for r in rs):>11}"
                     f"{_median([r.llm_calls for r in rs]):>7}{_median([r.seconds for r in rs]):>9}"
                     f"{sum(r.cost_usd for r in rs):>10.4f}")

    kinds = list(dict.fromkeys(r.kind for r in results))
    lines += ["", "PASSED BY KIND", f"{'kind':12}" + "".join(f"{m:>9}" for m in modes)]
    for k in kinds:
        cells = []
        for m in modes:
            rs = [r for r in by_mode[m] if r.kind == k]
            cells.append(f"{sum(r.passed for r in rs)}/{len(rs)}")
        lines.append(f"{k:12}" + "".join(f"{c:>9}" for c in cells))

    lines += ["", "BY CASE (pass or FAIL, then customer messages; auto also shows the mode the router picked)",
              f"{'case':30}" + "".join(f"{m:>16}" for m in modes)]
    for cid in dict.fromkeys(r.case for r in results):
        cells = []
        for m in modes:
            rs = [r for r in by_mode[m] if r.case == cid]
            if not rs:
                cells.append("-")
                continue
            cell = f"{sum(r.passed for r in rs)}/{len(rs)}" if len(rs) > 1 else ("pass" if rs[0].passed else "FAIL")
            cell += f" {_median([r.messages for r in rs]):g}"
            if m == "auto":
                cell += f" {rs[0].routed[0].split('/')[0]}" if rs[0].routed else ""
            cells.append(cell)
        lines.append(f"{cid:30}" + "".join(f"{c:>16}" for c in cells))

    fails = [r for r in results if not r.passed]
    if fails:
        lines += ["", "WHAT FAILED"]
        for r in fails:
            lines.append(f"{r.case} [{r.mode}]: " + "; ".join(r.failed))
    return "\n".join(lines)

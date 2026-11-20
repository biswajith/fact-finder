"""The self-correcting loop as a LangGraph graph.

    plan -> work -> verify -> reconcile --(open items and rounds left)--> work
                                        \\-------------(otherwise)------> finalize

plan       planner (reasoning) writes a todo list per (prompt, source) task. A source cut into
           several chunks is planned in two levels: allocate a case budget over the chunks from
           the source's profile, then plan each chunk with its full content.
work       Luna workers make a candidate per open item; a blind solver answers the same case
verify     code checks -> Decisions API gate -> Decisions sweep of every other chunk (large
           sources) -> reasoning adjudicator for the unsure ones
reconcile  code sends items out of attempts to a human; the planner retries, rewrites, splits
           or drops the rest and adds items for the coverage units still uncovered
finalize   writes golden.jsonl, needs_human.jsonl, coverage.json and the report

The planner proposes, code disposes: ids, spans, caps, attempt budgets, coverage and "done" are code.
"""

import asyncio
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, TypedDict, TypeVar

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from . import prompts as P
from .brain import Brain, model_for
from .checks import check_candidate
from .chunks import chunk_of, inside, leaf_count, render_chunk, render_chunk_list, span_size
from .config import Config
from .coverage import Atlas, CoverageReport, covered_by, measure, render_units
from .gate import questions_for, shared_input, sweep_question, triage
from .profile import pattern, render_profile, within
from .query import query_tool
from .schemas import (
    Allocation,
    Attempt,
    BlindAnswer,
    Candidate,
    Chunk,
    ChunkPlan,
    GoldenRecord,
    Item,
    PlannedItem,
    PromptSpec,
    ReconcilePlan,
    Source,
    Span,
    Task,
    TaskPlan,
    Verdict,
)
from .sources import leaves, render_for_planner, render_span, resolve_pointer, span_error
from .store import RunStore


TM = TypeVar("TM", bound=BaseModel)


class State(TypedDict):
    round: int
    tasks: dict[str, Task]
    items: dict[str, Item]


@dataclass
class Deps:
    cfg: Config
    brain: Brain
    sources: dict[str, Source]
    prompts: dict[str, PromptSpec]
    atlas: dict[str, Atlas]  # by source id
    store: RunStore
    log: Callable[[str], None] = print
    _next_id: list[int] = field(default_factory=lambda: [0])
    _tools: dict[str, list[BaseTool]] = field(default_factory=dict)

    def tools(self, source_id: str) -> list[BaseTool]:
        """The query tool over one JSON source (none for text, or when tools are off)."""
        source = self.sources[source_id]
        if source.kind != "json" or not self.cfg.tools.query:
            return []
        if source_id not in self._tools:
            self._tools[source_id] = [query_tool(source.data, self.cfg.tools.max_result_chars)]
        return self._tools[source_id]

    async def call(self, stage: str, schema: type[TM], system: str, user: str, source_id: str) -> TM:
        tools = self.tools(source_id)
        if tools:
            return await self.brain.agent(stage, schema, system, user, tools, self.cfg.tools.max_calls)
        return await self.brain.structured(stage, schema, system, user)

    def view(self, source_id: str, span: Span, aggregate: bool) -> str:
        """What a worker, the solver, the gate and the adjudicator see of the source for one item."""
        source = self.sources[source_id]
        if not aggregate or source.kind != "json":
            return render_span(source, span, self.cfg.render)
        root = span.pointer or ""
        node = resolve_pointer(source.data, root)
        stats = {p: s for p, s in self.atlas[source_id].stats.items() if within(p, pattern(root))}
        sample = "\n".join(f"{p} = {json.dumps(v, ensure_ascii=False)}" for p, v in list(leaves(node, root))[:40])
        parts = [f"SOURCE {source.id}: an aggregate case over {root or '(whole document)'} ({leaf_count(node)} leaves, too many "
                 "to show). Compute every count, sum, average or filter with the query_json tool; its root is the whole document.",
                 f"PROFILE OF {root or '(whole document)'}\n{render_profile(stats)}", f"SAMPLE (first leaves)\n{sample}"]
        if source.glossary:
            parts.append(f"FIELD GLOSSARY ({source.glossary_id})\n{source.glossary.strip()}")
        return "\n\n".join(parts)

    def new_id(self) -> str:
        self._next_id[0] += 1
        return f"T-{self._next_id[0]:03d}"

    def target(self, task: Task) -> int:
        if task.mode == "reference":
            return 1
        return self.prompts[task.prompt_id].cases or self.cfg.dataset.cases_per_task

    def cap(self, task: Task) -> int:
        return self.cfg.dataset.max_items_large if self.atlas[task.source_id].large else self.cfg.dataset.max_items_per_task

    def coverage(self, task: Task, items: dict[str, Item]) -> CoverageReport:
        source, atlas = self.sources[task.source_id], self.atlas[task.source_id]
        hits: set[str] = set()
        for i in _task_items(items, task.id):
            if i.status == "accepted" and i.candidate is not None:
                hits |= covered_by(i, i.candidate.evidence, source, atlas.chunks, atlas.units)
        return measure(atlas.units, hits)

    def overview(self, task: Task) -> str:
        """The source as a planner sees it: in full when it is one chunk, else its profile and chunk list."""
        source, atlas = self.sources[task.source_id], self.atlas[task.source_id]
        if not atlas.large:
            return render_for_planner(source, self.cfg.render)
        chunks = render_chunk_list(atlas.chunks, atlas.unit_counts())
        if source.kind == "json":
            parts = [f"SOURCE {source.id} (JSON, {leaf_count(source.data)} leaves: too large to show; profile of every field pattern)\n"
                     f"{render_profile(atlas.stats)}"]
            if source.glossary:
                parts.append(f"FIELD GLOSSARY ({source.glossary_id})\n{source.glossary.strip()}")
        else:
            parts = [render_for_planner(source, self.cfg.render)]
        return "\n\n".join(parts + [f"CHUNKS\n{chunks}"])


OPEN = ("pending", "verify")


def _copy(items: dict[str, Item]) -> dict[str, Item]:
    return {k: v.model_copy(deep=True) for k, v in items.items()}


def _task_items(items: dict[str, Item], task_id: str) -> list[Item]:
    return [i for i in items.values() if i.task_id == task_id]


def _admit(deps: Deps, task: Task, planned: list[PlannedItem], items: dict[str, Item], parent: str | None,
           limit: int | None = None, chunk: Chunk | None = None) -> list[str]:
    """Code-side acceptance of planner items: valid span, small enough for a worker, inside its chunk, under the cap."""
    source, atlas = deps.sources[task.source_id], deps.atlas[task.source_id]
    room = deps.cap(task) - len(_task_items(items, task.id))
    if limit is not None:
        room = min(room, limit)
    added: list[str] = []
    for p in planned:
        span = p.span()
        if source.kind == "json" and span.pointer is None:
            span = Span(pointer="")
        aggregate = p.aggregate and source.kind == "json"
        err = span_error(source, span)
        if err is None and chunk is not None and not inside(chunk, span):
            err = f"span {span.key()} is outside chunk {chunk.id}"
        if err is None and task.mode == "cases" and not aggregate:  # aggregates are computed by the tool, not read
            size, most = span_size(source, span), deps.cfg.render.max_json_leaves if source.kind == "json" else 2 * deps.cfg.chunking.text_max_chars
            if size > most:
                err = f"span {span.key()} is too large for a worker ({size} > {most})"
        if err is not None:
            deps.log(f"  {task.id}: planner item skipped ({err})")
            continue
        if len(added) >= room:
            if limit is None or room < limit:
                deps.log(f"  {task.id}: item cap reached, {len(planned) - len(added)} planned item(s) not added")
            break
        iid = deps.new_id()
        items[iid] = Item(id=iid, task_id=task.id, span=span, case_type=p.case_type, instruction=p.instruction,
                          acceptance=p.acceptance[:5], parent=parent, aggregate=aggregate,
                          chunk_id=None if aggregate else chunk.id if chunk else chunk_of(atlas.chunks, span))
        added.append(iid)
    return added


def _whole(source: Source) -> PlannedItem:
    n = len(source.text.splitlines())
    text = source.kind == "text"
    return PlannedItem(span_start_line=1 if text else None, span_end_line=n if text else None, span_pointer=None if text else "",
                       case_type="reference_output", instruction="Write the reference output for the whole source.",
                       acceptance=["The output covers everything the task prompt asks for."], aggregate=False)


def _item_block(item: Item) -> str:
    crit = "\n".join(f"- {c}" for c in item.acceptance)
    return f"TODO ITEM {item.id}\ncase_type: {item.case_type}\ninstruction: {item.instruction}\nacceptance criteria:\n{crit}"


def _reasons(item: Item) -> list[str]:
    if not item.history:
        return []
    last = item.history[-1]
    out = list(last.check_errors)
    if last.gate is not None:
        out += [f"gate {r}" for r in last.gate.failing]
    if last.verdict is not None:
        out += [f"adjudicator: {r}" for r in last.verdict.reasons]
        if last.verdict.fix_instructions:
            out.append(f"adjudicator fix: {last.verdict.fix_instructions}")
    return out


def _clip(text: str, n: int = 600) -> str:
    return text if len(text) <= n else text[:n] + " ..."


def _spread(budgets: dict[str, int], total: int) -> dict[str, int]:
    """Trim a planner's per-chunk budget to the total, taking from the largest first."""
    out = {k: max(0, v) for k, v in budgets.items()}
    while sum(out.values()) > total:
        out[max(out, key=lambda k: (out[k], k))] -= 1
    return out


# --- nodes ------------------------------------------------------------------------


def build_graph(deps: Deps):
    cfg = deps.cfg

    def task_head(task: Task) -> str:
        prompt = deps.prompts[task.prompt_id]
        return f"TASK PROMPT ({prompt.id})\n{prompt.text}"

    async def plan_small(task: Task) -> TaskPlan:
        prompt = deps.prompts[task.prompt_id]
        fmt = prompt.output_format or "decide from the prompt"
        user = (f"{task_head(task)}\n\n{deps.overview(task)}\n\nSettings: output_format = {fmt}; "
                f"target cases in cases mode = {deps.target(task)}; at most {deps.cap(task)} items.")
        return await deps.brain.structured("plan", TaskPlan, P.PLANNER.format(cases=deps.target(task)), user)

    async def plan_large(task: Task) -> tuple[Allocation, list[tuple[Chunk, int, ChunkPlan]]]:
        prompt, source, atlas = deps.prompts[task.prompt_id], deps.sources[task.source_id], deps.atlas[task.source_id]
        budget = min(deps.cap(task), max(deps.target(task), len(atlas.chunks)))
        cov = measure(atlas.units, set())
        fmt = prompt.output_format or "decide from the prompt"
        user = (f"{task_head(task)}\n\n{deps.overview(task)}\n\nUNCOVERED UNITS (rarest first)\n"
                f"{render_units(cov.uncovered, cfg.coverage.max_listed)}\n\nSettings: output_format = {fmt}; budget = {budget} cases.")
        alloc = await deps.brain.structured("allocate", Allocation, P.ALLOCATOR.format(budget=budget), user)
        by_id = {c.id: c for c in atlas.chunks}
        wanted = _spread({b.chunk_id: b.cases for b in alloc.budgets if b.chunk_id in by_id}, budget)
        focus = {b.chunk_id: b.focus for b in alloc.budgets}
        if alloc.mode == "reference":
            return alloc, []

        async def one(c: Chunk, n: int) -> tuple[Chunk, int, ChunkPlan]:
            todo = [u for u in cov.uncovered if u.chunk_id == c.id]
            user = (f"{task_head(task)}\n\nMODE: cases; OUTPUT FORMAT: {prompt.output_format or alloc.output_format}\n\n"
                    f"SOURCE PROFILE (whole document, for context)\n{render_profile(atlas.stats, 120) if atlas.stats else '(text source)'}\n\n"
                    f"{render_chunk(source, c)}\n\n"
                    + (f"FIELD GLOSSARY\n{source.glossary.strip()}\n\n" if source.glossary else "")
                    + f"FOCUS FOR THIS CHUNK: {focus.get(c.id, '')}\n\nUNCOVERED UNITS IN THIS CHUNK\n"
                    f"{render_units(todo, cfg.coverage.max_listed)}")
            return c, n, await deps.brain.structured("plan_chunk", ChunkPlan, P.CHUNK_PLANNER.format(n=n), user)

        picks = [(by_id[cid], n) for cid, n in wanted.items() if n > 0]
        return alloc, list(await asyncio.gather(*(one(c, n) for c, n in picks)))

    async def plan(state: State) -> dict[str, object]:
        tasks = {k: v.model_copy() for k, v in state["tasks"].items()}
        items = _copy(state["items"])
        order = list(tasks.values())

        async def one(task: Task):
            return await (plan_large(task) if deps.atlas[task.source_id].large else plan_small(task))

        results = await asyncio.gather(*(one(t) for t in order))
        for task, res in zip(order, results):  # admitted in task order, so ids are stable across re-runs
            prompt, source = deps.prompts[task.prompt_id], deps.sources[task.source_id]
            if isinstance(res, TaskPlan):
                task.mode, task.rationale = res.mode, res.mode_rationale
                task.output_format = prompt.output_format or res.output_format
                planned = res.items[:1] if res.mode == "reference" else res.items
                if not _admit(deps, task, planned, items, None) and res.mode == "reference":
                    _admit(deps, task, [_whole(source)], items, None)  # no usable span from the planner
            else:
                alloc, plans = res
                task.mode, task.rationale = alloc.mode, alloc.mode_rationale
                task.output_format = prompt.output_format or alloc.output_format
                if alloc.mode == "reference":
                    deps.log(f"  {task.id}: reference mode on a source of {len(deps.atlas[source.id].chunks)} chunks; "
                             "the worker sees a capped view and the sweep checks the rest")
                    _admit(deps, task, [_whole(source)], items, None)
                for chunk, n, cp in plans:
                    _admit(deps, task, cp.items, items, None, limit=n, chunk=chunk)  # validate first, then take up to n
                if alloc.mode == "cases" and alloc.aggregates:
                    _admit(deps, task, [a.model_copy(update={"aggregate": True}) for a in alloc.aggregates], items, None)
            mine = _task_items(items, task.id)
            n_agg = sum(i.aggregate for i in mine)
            deps.log(f"plan  {task.id}: {task.mode}, {len(mine)} item(s) over {len({i.chunk_id for i in mine} - {None})} chunk(s)"
                     + (f", {n_agg} aggregate" if n_agg else ""))
        deps.store.write_json("plan.json", {"tasks": tasks, "items": items})
        return {"tasks": tasks, "items": items}

    async def work(state: State) -> dict[str, object]:
        rnd = state["round"] + 1
        tasks, items = state["tasks"], _copy(state["items"])

        async def one(item: Item) -> None:
            task = tasks[item.task_id]
            view = deps.view(task.source_id, item.span, item.aggregate)
            head = f"{task_head(task)}\n\nMODE: {task.mode}; OUTPUT FORMAT: {task.output_format}"
            if item.status == "pending":
                user = f"{head}\n\n{_item_block(item)}\n\n{view}"
                if item.feedback:
                    user += "\n\nFEEDBACK FROM EARLIER ATTEMPTS (fix all of it):\n" + "\n".join(f"- {f}" for f in item.feedback)
                if item.candidate is not None:
                    user += f"\n\nPREVIOUS CANDIDATE (rejected):\n{item.candidate.model_dump_json(indent=1)}"
                cand = await deps.call("work", Candidate, P.WORKER, user, task.source_id)
                if task.mode == "reference":
                    cand = cand.model_copy(update={"case_input": ""})
                item.candidate, item.attempts = cand, item.attempts + 1
                item.history.append(Attempt(round=rnd, by="worker", candidate=cand))
                item.status = "verify"
            assert item.candidate is not None
            if item.blind is None or item.blind_for != item.candidate.case_input:
                case = item.candidate.case_input or "(reference mode: produce the output for the whole source)"
                user = f"{task_head(task)}\n\n{view}\n\nCASE INPUT:\n{case}"
                item.blind = await deps.call("solve", BlindAnswer, P.SOLVER, user, task.source_id)
                item.blind_for = item.candidate.case_input

        todo = [i for i in items.values() if i.status in OPEN]
        await asyncio.gather(*(one(i) for i in todo))
        deps.log(f"round {rnd}: work {len(todo)} item(s)")
        return {"round": rnd, "items": items}

    async def verify(state: State) -> dict[str, object]:
        rnd, tasks, items = state["round"], state["tasks"], _copy(state["items"])
        batch = [i for i in items.values() if i.status == "verify"]
        accepted: dict[str, list[str]] = defaultdict(list)
        near: dict[tuple[str, str | None], list[str]] = defaultdict(list)  # accepted inputs per (task, chunk), for novelty
        for i in items.values():
            if i.status == "accepted" and i.candidate is not None:
                accepted[i.task_id].append(i.candidate.case_input)
                near[(i.task_id, i.chunk_id)].append(i.candidate.case_input)

        # 1. code checks
        gated: list[Item] = []
        for item in batch:
            task = tasks[item.task_id]
            assert item.candidate is not None
            errs = check_candidate(item.candidate, item, task, deps.sources[task.source_id], accepted[task.id])
            item.history[-1].check_errors = errs
            if errs:
                item.status, item.history[-1].outcome = "failed", "failed"
            else:
                gated.append(item)

        # 2. Decisions API gate, one request per (task, span)
        groups: dict[tuple[str, str], list[Item]] = defaultdict(list)
        for item in gated:
            groups[(item.task_id, f"{item.span.key()}|{item.aggregate}")].append(item)

        async def gate(group: list[Item]) -> None:
            task = tasks[group[0].task_id]
            prompt, source = deps.prompts[task.prompt_id], deps.sources[task.source_id]
            shared = shared_input(deps.view(source.id, group[0].span, group[0].aggregate), prompt)
            questions = {}
            seen = near[(task.id, group[0].chunk_id)][-30:] if task.mode == "cases" else []
            for n, item in enumerate(group):
                assert item.candidate is not None
                for k, q in questions_for(item, task, source, list(seen)).items():
                    questions[f"c{n}_{k}"] = q
                if task.mode == "cases":
                    seen.append(item.candidate.case_input)
            resp = await deps.brain.decide("gate", shared, questions)
            for n, item in enumerate(group):
                item.history[-1].gate = triage(resp, f"c{n}_", cfg.gate)

        await asyncio.gather(*(gate(g) for g in groups.values()))

        # 3. sweep: on a large source, ask every other chunk whether it changes the case
        flagged: dict[str, dict[str, float]] = defaultdict(dict)
        if cfg.sweep.enabled:
            live = [i for i in gated if i.history[-1].gate and i.history[-1].gate.outcome != "fail" and not i.aggregate
                    and deps.atlas[tasks[i.task_id].source_id].large]  # aggregates already read the whole source, by code
            jobs: list[tuple[Task, Chunk, list[Item]]] = []
            for task in tasks.values():
                mine = [i for i in live if i.task_id == task.id]
                for c in deps.atlas[task.source_id].chunks if mine else []:
                    others = [i for i in mine if not inside(c, i.span)]
                    if others:
                        jobs.append((task, c, others))

            async def sweep(task: Task, c: Chunk, cands: list[Item]) -> None:
                shared = [HumanMessage(render_chunk(deps.sources[task.source_id], c)), HumanMessage(task_head(task))]
                resp = await deps.brain.decide("sweep", shared, {f"s{n}": sweep_question(i, task) for n, i in enumerate(cands)})
                for n, i in enumerate(cands):
                    a = resp.predicates.get(f"s{n}")
                    if a is not None and a.probability >= cfg.sweep.flag:
                        flagged[i.id][c.id] = a.probability

            await asyncio.gather(*(sweep(t, c, cs) for t, c, cs in jobs))
            for i in live:
                if flagged.get(i.id):
                    g = i.history[-1].gate
                    assert g is not None
                    g.sweep = dict(sorted(flagged[i.id].items(), key=lambda kv: -kv[1]))
                    g.failing += [f"sweep: {cid} may contradict or change the answer (p={p:.2f})" for cid, p in list(g.sweep.items())[:5]]
                    g.outcome = "unsure"

        # 4. pass / fail now; unsure goes to the adjudicator
        unsure: list[Item] = []
        for item in gated:
            g = item.history[-1].gate
            assert g is not None
            if g.outcome == "pass":
                item.status, item.history[-1].outcome = "accepted", "accepted"
            elif g.outcome == "fail":
                item.status, item.history[-1].outcome = "failed", "failed"
            else:
                unsure.append(item)

        async def adjudicate(item: Item) -> None:
            task = tasks[item.task_id]
            source = deps.sources[task.source_id]
            last = item.history[-1]
            assert item.candidate is not None and last.gate is not None
            by_id = {c.id: c for c in deps.atlas[source.id].chunks}
            passages = [render_chunk(source, by_id[cid]) for cid in list(last.gate.sweep)[: cfg.sweep.max_passages]]
            user = (f"{task_head(task)}\n\nMODE: {task.mode}; OUTPUT FORMAT: {task.output_format}\n\n"
                    f"{_item_block(item)}\n\n{deps.view(source.id, item.span, item.aggregate)}\n\n"
                    + (f"PASSAGES FROM ELSEWHERE IN THE SOURCE\n" + "\n\n".join(passages) + "\n\n" if passages else "")
                    + f"CANDIDATE:\n{item.candidate.model_dump_json(indent=1)}\n\n"
                    f"INDEPENDENT ANSWER:\n{item.blind.model_dump_json(indent=1) if item.blind else '(none)'}\n\n"
                    f"VERIFIER CONCERNS:\n" + "\n".join(f"- {r}" for r in last.gate.failing))
            v = await deps.call("adjudicate", Verdict, P.ADJUDICATOR, user, source.id)
            last.verdict = v
            if v.decision == "accept":
                item.status, last.outcome = "accepted", "accepted"
            elif v.decision == "revise" and v.corrected is not None:
                fixed = v.corrected.model_copy(update={"case_input": ""}) if task.mode == "reference" else v.corrected
                last.outcome = "revised"
                item.candidate, item.attempts = fixed, item.attempts + 1
                item.history.append(Attempt(round=rnd, by="adjudicator", candidate=fixed))
                item.status = "verify"  # a correction is a new candidate: it is verified like any other
            else:
                item.status, last.outcome = "failed", "failed"

        await asyncio.gather(*(adjudicate(i) for i in unsure))
        counts = Counter(i.history[-1].outcome or "revised" for i in batch)
        deps.log(f"round {rnd}: verify {len(batch)}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) +
                 f" ({len(unsure)} adjudicated, {len(flagged)} flagged by the sweep)")
        return {"items": items}

    async def reconcile(state: State) -> dict[str, object]:
        rnd, tasks, items = state["round"], state["tasks"], _copy(state["items"])
        for item in items.values():
            if item.status == "failed" and item.attempts >= cfg.loop.max_attempts:
                item.status, item.note = "needs_human", f"failed {item.attempts} attempts; last: " + "; ".join(_reasons(item))[:800]
        if rnd >= cfg.loop.max_rounds:
            deps.store.write_json(f"rounds/round_{rnd:02d}.json", {"tasks": tasks, "items": items})
            return {"items": items}

        def room_for(task: Task) -> int:
            """New items allowed this round: up to the case target, then more while coverage is short."""
            if task.mode == "reference":
                return 0
            mine = _task_items(items, task.id)
            live = [i for i in mine if i.status in ("accepted", *OPEN)]
            n_open = sum(i.status in OPEN for i in mine)
            want = deps.target(task) - len(live)
            if deps.coverage(task, items).ratio < cfg.coverage.target:
                want = max(want, cfg.coverage.max_new_per_round - n_open)
            return max(0, min(want, deps.cap(task) - len(mine)))

        async def ask(task: Task) -> ReconcilePlan | None:
            mine = _task_items(items, task.id)
            failed = [i for i in mine if i.status == "failed"]
            live = [i for i in mine if i.status in ("accepted", *OPEN)]
            room = room_for(task)
            if not failed and room == 0:
                return None
            cov = deps.coverage(task, items)

            def line(i: Item) -> str:
                case = _clip(i.candidate.case_input, 200) if i.candidate else _clip(i.instruction, 200)
                where = "aggregate" if i.aggregate else i.chunk_id
                return f"- {i.id} [{i.status}] [{where}] {i.case_type} span {i.span.key()}: {case}"

            fails = []
            for i in failed:
                cand = i.candidate.model_dump_json(indent=1) if i.candidate else "(none)"
                fails.append(f"{_item_block(i)}\nspan: {i.span.key()}\nattempts: {i.attempts}\nlast candidate:\n{_clip(cand, 1500)}\n"
                             "problems:\n" + "\n".join(f"- {r}" for r in _reasons(i)))
            kinds = ", ".join(f"{k} {a}/{b}" for k, (a, b) in sorted(cov.by_kind.items()))
            user = (f"{task_head(task)}\n\nMODE: {task.mode}\n\n{deps.overview(task)}\n\n"
                    f"ACCEPTED AND OPEN ITEMS:\n" + ("\n".join(line(i) for i in live) or "(none)") +
                    "\n\nFAILED ITEMS:\n" + ("\n\n".join(fails) or "(none)") +
                    f"\n\nCOVERAGE: {cov.covered}/{cov.total} units ({cov.ratio:.0%}; target {cfg.coverage.target:.0%}): {kinds}. "
                    f"{sum(i.status == 'accepted' for i in mine)} accepted, target {deps.target(task)} cases.\n"
                    f"UNCOVERED UNITS (rarest first)\n{render_units(cov.uncovered, cfg.coverage.max_listed)}\n\n"
                    f"You may add at most {room} new item(s).")
            return await deps.brain.structured("reconcile", ReconcilePlan, P.RECONCILER.format(room=room), user)

        def apply(task: Task, rp: ReconcilePlan) -> None:
            source = deps.sources[task.source_id]
            failed = [i for i in _task_items(items, task.id) if i.status == "failed"]
            room = room_for(task)
            acted: set[str] = set()
            for a in rp.actions:
                item = items.get(a.item_id)
                if item is None or item.status != "failed" or item.task_id != task.id or a.item_id in acted:
                    continue
                acted.add(a.item_id)
                if a.action == "drop":
                    item.status, item.note = "dropped", a.feedback
                elif a.action == "split" and a.split_into:
                    kids = _admit(deps, task, a.split_into, items, item.id)
                    item.status, item.note = "dropped", f"split into {', '.join(kids) or 'nothing (cap)'}"
                elif a.action == "rewrite" and a.replacement is not None and span_error(source, a.replacement.span()) is None:
                    r = a.replacement
                    item.span, item.case_type, item.instruction, item.acceptance = r.span(), r.case_type, r.instruction, r.acceptance[:5]
                    item.aggregate = r.aggregate and source.kind == "json"
                    item.chunk_id = None if item.aggregate else chunk_of(deps.atlas[source.id].chunks, item.span)
                    item.feedback = [a.feedback] if a.feedback else []
                    item.candidate, item.blind, item.status = None, None, "pending"
                else:
                    item.feedback.append(a.feedback or "; ".join(_reasons(item)))
                    item.status = "pending"
            for item in failed:  # code fallback: the planner skipped it
                if item.id not in acted:
                    item.feedback.append("; ".join(_reasons(item)))
                    item.status = "pending"
            if rp.new_items and room:
                _admit(deps, task, rp.new_items, items, None, limit=room)

        order = list(tasks.values())
        plans = await asyncio.gather(*(ask(t) for t in order))
        for task, rp in zip(order, plans):  # applied in task order, so item ids are the same on every re-run
            if rp is not None:
                apply(task, rp)
        st = Counter(i.status for i in items.values())
        cov = ", ".join(f"{t.id} {deps.coverage(t, items).ratio:.0%}" for t in order)
        deps.log(f"round {rnd}: reconcile -> " + ", ".join(f"{k} {v}" for k, v in sorted(st.items())) + f"; coverage {cov}")
        deps.store.write_json(f"rounds/round_{rnd:02d}.json", {"tasks": tasks, "items": items})
        return {"items": items}

    def route(state: State) -> Literal["work", "finalize"]:
        open_ = any(i.status in OPEN for i in state["items"].values())
        return "work" if open_ and state["round"] < cfg.loop.max_rounds else "finalize"

    async def finalize(state: State) -> dict[str, object]:
        tasks, items = state["tasks"], _copy(state["items"])
        for item in items.values():
            if item.status not in ("accepted", "dropped", "needs_human"):
                item.note = f"still {item.status} when rounds ran out; last: " + "; ".join(_reasons(item))[:800]
                item.status = "needs_human"
        golden = [_record(deps, tasks[i.task_id], i) for i in items.values() if i.status == "accepted"]
        coverage = {t.id: deps.coverage(t, items) for t in tasks.values()}
        deps.store.write_jsonl("golden.jsonl", golden)
        deps.store.write_jsonl("needs_human.jsonl", [i for i in items.values() if i.status == "needs_human"])
        deps.store.write_json("coverage.json", {k: {"ratio": round(c.ratio, 4), "covered": c.covered, "total": c.total,
                                                    "by_kind": c.by_kind, "uncovered": [u.id for u in c.uncovered]}
                                                for k, c in coverage.items()})
        deps.store.write_json("final.json", {"tasks": tasks, "items": items})
        deps.store.write_json("usage.json", deps.brain.ledger.as_dict())
        deps.store.write_text("report.md", report(deps, tasks, items, state["round"], coverage))
        deps.log(f"done: {len(golden)} golden record(s) in {deps.store.root / 'golden.jsonl'}")
        return {"items": items}

    g = StateGraph(State)
    g.add_node("plan", plan)
    g.add_node("work", work)
    g.add_node("verify", verify)
    g.add_node("reconcile", reconcile)
    g.add_node("finalize", finalize)
    g.add_edge(START, "plan")
    g.add_edge("plan", "work")
    g.add_edge("work", "verify")
    g.add_edge("verify", "reconcile")
    g.add_conditional_edges("reconcile", route)
    g.add_edge("finalize", END)
    return g.compile()


# --- outputs ----------------------------------------------------------------------


def _record(deps: Deps, task: Task, item: Item) -> GoldenRecord:
    assert item.candidate is not None
    final = item.history[-1]
    source, atlas = deps.sources[task.source_id], deps.atlas[task.source_id]
    return GoldenRecord(
        id=f"{task.id}#{item.id}",
        prompt_id=task.prompt_id,
        source_id=task.source_id,
        mode=task.mode,
        case_type=item.case_type,
        case_input=item.candidate.case_input,
        expected_output=item.candidate.expected_output,
        evidence=item.candidate.evidence,
        span=item.span,
        provenance={
            "item": item.id,
            "chunk": item.chunk_id,
            "aggregate": item.aggregate,
            "instruction": item.instruction,
            "acceptance": item.acceptance,
            "attempts": item.attempts,
            "accepted_in_round": final.round,
            "written_by": final.by,
            "adjudicated": final.verdict is not None,
            "adjudicator_reasons": final.verdict.reasons if final.verdict else [],
            "gate_scores": final.gate.scores if final.gate else {},
            "agreement": final.gate.agreement if final.gate else None,
            "covers": sorted(covered_by(item, item.candidate.evidence, source, atlas.chunks, atlas.units)),
            "rationale": item.candidate.rationale,
            "models": {k: model_for(deps.cfg, k).model_dump() for k in ("plan", "work", "solve", "adjudicate")}
            | {"gate": deps.cfg.models.decisions},
        },
    )


def report(deps: Deps, tasks: dict[str, Task], items: dict[str, Item], rounds: int, coverage: dict[str, CoverageReport]) -> str:
    status = Counter(i.status for i in items.values())
    acc = [i for i in items.values() if i.status == "accepted"]
    first_pass = sum(1 for i in acc if i.attempts == 1 and i.history[-1].verdict is None)
    corrected = len(acc) - first_pass
    problems: Counter[str] = Counter()
    for i in items.values():
        for a in i.history:
            problems.update(re.sub(r"^evidence \d+: ", "", e).split(":")[0].split(" (")[0] for e in a.check_errors)
            if a.gate is not None:
                problems.update("gate " + f.split(":")[0] for f in a.gate.failing)
    lines = [
        "# Golden dataset run report", "",
        f"Rounds: {rounds}. Items: {len(items)}. " + ", ".join(f"{k}: {v}" for k, v in sorted(status.items())) + ".",
        f"Accepted: {len(acc)} ({first_pass} on the first try, {corrected} after self-correction).", "",
        "| Task | Mode | Chunks | Accepted (min) | Coverage | Dropped | Needs human |", "|---|---|---|---|---|---|---|",
    ]
    for t in tasks.values():
        c = Counter(i.status for i in _task_items(items, t.id))
        cov = coverage[t.id]
        lines.append(f"| {t.id} | {t.mode} | {len(deps.atlas[t.source_id].chunks)} | {c['accepted']} ({deps.target(t)}) | "
                     f"{cov.covered}/{cov.total} ({cov.ratio:.0%}) | {c['dropped']} | {c['needs_human']} |")
    lines += ["", f"## Coverage (target {deps.cfg.coverage.target:.0%})", ""]
    for t in tasks.values():
        cov = coverage[t.id]
        kinds = ", ".join(f"{k} {a}/{b}" for k, (a, b) in sorted(cov.by_kind.items()))
        lines += [f"`{t.id}`: {kinds}", ""]
        if cov.uncovered:
            lines += ["Not covered, rarest first:", render_units(cov.uncovered, 15), ""]
    lines += ["## Most common problems found (all attempts)", ""]
    lines += [f"- {k}: {v}" for k, v in problems.most_common(12)] or ["- none"]
    lines += ["", "## Needs human", ""]
    lines += [f"- {i.id} ({i.task_id}): {i.note}" for i in items.values() if i.status == "needs_human"] or ["- none"]
    lines += ["", "## Model usage", "", "```json", json.dumps(deps.brain.ledger.as_dict(), indent=2), "```", ""]
    return "\n".join(lines)

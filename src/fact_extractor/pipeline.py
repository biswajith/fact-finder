"""Run the whole extraction for one document (spec sections 5 to 9, failures in 11)."""

from __future__ import annotations

import asyncio
import hashlib
import random
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Protocol

from . import planner, prompts, xref
from .llm import CallFailed, LLMClient, RateLimited, Request, Response
from .merge import dedupe, uncited, union_passes
from .models import CallRecord, CallSpec, Fact, TaggedDocument
from .store import InMemoryFactStore, fact_id, to_record
from .validate import Checked, LineBuffer, check_output

ALL_CODES = ("B", "C", "G", "X", "D", "S", "E", "R", "Q")


@dataclass
class Config:
    max_parallel: int = 32  # every extraction call at once, with room for a second pass, on a ~50-page RFP
    max_output_tokens: int = 3000
    # The check reasons at medium effort over the whole fact list; hidden reasoning counts
    # toward the cap, and at 3,000 a 700-fact list left no room for any Q line.
    check_max_output_tokens: int = 8000
    call_timeout: float = 120.0
    warmup_timeout: float = 10.0  # wait at most this long for the first call to stream
    rate_limit_retries: int = 5
    backoff_base: float = 1.0
    max_splits: int = 3  # how often a cut call may be split again
    # Run every extraction call this many times and keep the union. 1 by default: a second
    # pass added 0-3 points of recall for ~60% more output tokens (REVIEW.md, "Trimming tests").
    passes: int = 1
    sweep_all: bool = True  # sweep every uncited sentence, not only shall/must candidates
    sweep_chunk: int = 30  # uncited IDs per sweep call; ~1,000 output tokens each
    parallel_check: bool = True  # check runs alongside the sweep (REVIEW.md item 12)
    # Switches for trimming tests (poc/ablation): turn a stage off to measure what it adds.
    sweep: bool = True  # coverage sweep over uncited IDs
    check: bool = True  # model contradiction check (xref.py still runs)
    plan: planner.PlanConfig = field(default_factory=planner.PlanConfig)


class Decisions(Protocol):
    async def submit(self, conflict: dict) -> None: ...


class RecordingDecisions:
    """Stand-in for the Decisions API: keeps what was sent."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def submit(self, conflict: dict) -> None:
        self.sent.append(conflict)


class _Limiter:
    """Concurrency limit that can be lowered during a run (spec 11, rate limit)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._active = 0
        self._cond = asyncio.Condition()

    async def __aenter__(self) -> None:
        async with self._cond:
            await self._cond.wait_for(lambda: self._active < self.limit)
            self._active += 1

    async def __aexit__(self, *exc) -> None:
        async with self._cond:
            self._active -= 1
            self._cond.notify_all()

    def lower(self) -> None:
        self.limit = max(1, self.limit // 2)


@dataclass
class RunResult:
    run_id: str
    facts: list[dict]
    report: dict


class _Run:
    def __init__(self, doc: TaggedDocument, client: LLMClient, cfg: Config) -> None:
        self.doc = doc
        self.client = client
        self.cfg = cfg
        self.limiter = _Limiter(cfg.max_parallel)
        self.calls: list[CallRecord] = []
        self.none_ids: set[str] = set()  # sweep answered NONE
        self.cache_key = "fx-" + hashlib.sha256((prompts.SYSTEM + doc.tagged_text).encode()).hexdigest()[:24]

    # --- one model call with retries -----------------------------------------

    async def _request(
        self, spec: CallSpec, rec: CallRecord, started: asyncio.Event | None = None
    ) -> tuple[Response, list[str]]:
        req = Request(
            prompts.SYSTEM, self.doc.tagged_text, spec.task, spec.effort,
            self.cfg.check_max_output_tokens if spec.kind == "check" else self.cfg.max_output_tokens,
            self.cache_key,
        )
        errors = 0
        limited = 0
        while True:
            buf = LineBuffer()
            times: dict[str, float] = {}

            def on_text(text: str) -> None:
                now = time.monotonic()
                times.setdefault("first", now)
                times["last"] = now
                if started is not None:
                    started.set()
                buf.feed(text)

            try:
                q0 = time.monotonic()
                async with self.limiter:
                    sent = time.monotonic()
                    rec.queue_seconds += sent - q0
                    resp = await asyncio.wait_for(self.client.complete(req, on_text), self.cfg.call_timeout)
                buf.close()
                _timing(rec, sent, times, resp.usage.output_tokens)
                rec.output = resp.text
                return resp, buf.lines
            except RateLimited:
                limited += 1
                rec.retries += 1
                self.limiter.lower()
                if limited > self.cfg.rate_limit_retries:
                    raise CallFailed("rate limited too many times")
                delay = self.cfg.backoff_base * (2 ** (limited - 1))
                await asyncio.sleep(delay + random.uniform(0, self.cfg.backoff_base))
            except (CallFailed, asyncio.TimeoutError) as e:
                errors += 1
                rec.retries += 1
                if errors > 1:  # retry once (spec 11)
                    raise CallFailed(str(e) or "timeout") from e
                rec.log.append(f"retrying after error: {e or 'timeout'}")

    # --- extraction, sweep and check calls -----------------------------------

    async def run_call(self, spec: CallSpec, started: asyncio.Event | None = None, depth: int = 0) -> list[Fact]:
        rec = CallRecord(spec.name, spec.kind)
        self.calls.append(rec)
        t0 = time.monotonic()
        try:
            resp, lines = await self._request(spec, rec, started)
        except CallFailed as e:
            rec.status = "failed"
            rec.log.append(f"call failed: {e}")
            rec.seconds = time.monotonic() - t0
            if started is not None:
                started.set()
            return []
        rec.seconds = time.monotonic() - t0
        rec.usage = resp.usage

        out = check_output(lines, spec, self.doc)
        rec.lines = out.body_lines
        rec.end_count = out.end_count
        rec.failed_lines = len(out.failed)
        for c in out.checked:
            rec.log.extend(c.log)
        if out.end_count is not None and out.end_count != out.body_lines:
            rec.log.append(f"END says {out.end_count} lines, got {out.body_lines}")
        if spec.kind == "sweep":
            self.none_ids.update(out.none_ids)
            answered = set(out.none_ids) | {i for c in out.checked for i in c.line.ids}
            missing = [i for i in spec.sweep_ids if i not in answered]
            if missing and out.end_count is not None:
                rec.log.append(f"sweep gave no line for: {', '.join(missing)}")

        # Lines that fail validation are kept as needs_review with their problems; there is no
        # repair call (it added no measurable recall, REVIEW.md "Trimming tests").
        facts = [_fact(c, spec.name) for c in out.checked]

        cut = out.end_count is None or resp.truncated
        if cut:
            parts = planner.split_call(spec, self.doc.page_count) if depth < self.cfg.max_splits else []
            if parts:
                rec.status = "split"
                rec.log.append(f"output cut; rerunning as {', '.join(p.name for p in parts)}")
                results = await asyncio.gather(*(self.run_call(p, depth=depth + 1) for p in parts))
                for r in results:
                    facts.extend(r)
            else:
                rec.status = "partial"
                rec.log.append("output cut and the call cannot be split further; kept valid lines")
        return facts



def _timing(rec: CallRecord, sent: float, times: dict[str, float], output_tokens: int) -> None:
    if "first" not in times:
        return
    rec.ttft_seconds = round(times["first"] - sent, 3)
    rec.model_seconds = round(times["last"] - sent, 3)
    # Output tokens include hidden reasoning, written before the first visible text,
    # so the rate is taken over the whole call, not from the first token.
    if output_tokens >= 100 and rec.model_seconds > 0.2:
        rec.tokens_per_second = round(output_tokens / rec.model_seconds, 1)


def percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolated percentile, p in 0..100."""
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 3)


def _stats(values: list[float]) -> dict:
    return {
        "n": len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": round(max(values), 3) if values else None,
    }


def _fact(c: Checked, source: str, extra: list[str] | None = None) -> Fact:
    problems = list(c.reasons) + list(extra or [])
    return Fact(
        c.line.code, c.line.fact, c.line.ids, c.line.note,
        "valid" if not problems else "needs_review", source, problems,
    )



def _mark_conflicts(facts: list[Fact], doc_id: str) -> None:
    """Facts that share an ID with a Q line get status conflict (REVIEW.md item 15)."""
    qs = [f for f in facts if f.category == "Q"]
    for f in facts:
        f.conflicts = []
    for q in qs:
        qid = fact_id(doc_id, q)
        for f in facts:
            if f.category != "Q" and set(f.ids) & set(q.ids):
                f.conflicts.append(qid)
                if f.status == "valid":
                    f.status = "conflict"


async def extract(
    doc: TaggedDocument,
    client: LLMClient,
    *,
    deal_id: str,
    store: InMemoryFactStore | None = None,
    decisions: Decisions | None = None,
    cfg: Config | None = None,
    run_id: str | None = None,
) -> RunResult:
    cfg = cfg or Config()
    run_id = run_id or f"run_{datetime.now(timezone.utc):%Y_%m_%d}_{uuid.uuid4().hex[:6]}"
    run = _Run(doc, client, cfg)
    stages: dict[str, float] = {}
    t_start = time.monotonic()

    # 3. Extract: start one call, then the rest once it streams (spec 5.2).
    calls = planner.plan_calls(doc, cfg.plan)
    started = asyncio.Event()
    first = asyncio.create_task(run.run_call(calls[0], started))
    try:
        await asyncio.wait_for(started.wait(), cfg.warmup_timeout)
    except asyncio.TimeoutError:
        pass
    # Later passes repeat every call; the prefix is the same, so they read from the cache.
    extra = [replace(c, name=f"{c.name}#{p}") for p in range(2, cfg.passes + 1) for c in calls]
    rest = [asyncio.create_task(run.run_call(c)) for c in calls[1:] + extra]
    results = await asyncio.gather(first, *rest)
    by_pass: dict[int, list[Fact]] = {}
    for spec, r in zip(calls + extra, results):
        p = int(spec.name.split("#")[1]) if "#" in spec.name else 1
        by_pass.setdefault(p, []).extend(r)
    facts = dedupe(by_pass.get(1, []))
    for p in sorted(k for k in by_pass if k > 1):
        facts = union_passes(facts, dedupe(by_pass[p]))
    facts = dedupe(facts)
    stages["extract"] = time.monotonic() - t_start

    # 5. Coverage sweep and contradiction check (spec 8.2, 8.3).
    t = time.monotonic()
    candidate_ids = planner.candidates(doc)
    sweep_ids = planner.sweepable(doc) if cfg.sweep_all else candidate_ids
    missing = uncited(sweep_ids, facts)
    sweep_specs = planner.sweep_calls(missing, cfg.sweep_chunk) if cfg.sweep else []

    async def sweep() -> list[Fact]:
        rs = await asyncio.gather(*(run.run_call(s) for s in sweep_specs))
        return [f for r in rs for f in r]

    async def check(fs: list[Fact]) -> list[Fact]:
        if not cfg.check:
            return []
        spec = CallSpec("CHECK", ("Q",), prompts.check_task([f.line() for f in fs]), effort="medium", kind="check")
        return await run.run_call(spec)

    if cfg.parallel_check:
        swept, checked = await asyncio.gather(sweep(), check(facts))
        facts = dedupe(facts + swept + checked)
    else:
        swept = await sweep()
        facts = dedupe(facts + swept)
        stages["sweep"] = time.monotonic() - t
        t = time.monotonic()
        facts = dedupe(facts + await check(facts))
    stages["check" if not cfg.parallel_check else "sweep_and_check"] = time.monotonic() - t

    # Cross-references checked in code (xref.py); merges with any model Q line on the same IDs.
    xref_facts = xref.check(doc)
    facts = dedupe(facts + xref_facts)

    # 6. Store.
    _mark_conflicts(facts, doc.doc_id)
    records = [to_record(f, doc, deal_id, run_id) for f in facts]
    decision_errors: list[str] = []
    if decisions is not None:
        for r in records:
            if r["category"] == "Q":
                try:
                    await decisions.submit(r)
                except Exception as e:  # the run still stores its facts
                    decision_errors.append(f"{r['fact_id']}: {e}")
    stages["total"] = time.monotonic() - t_start

    report = _report(run, doc, deal_id, run_id, records, stages, candidate_ids, facts, decision_errors, sweep_ids)
    report["xref_conflicts"] = len(xref_facts)
    if store is not None:
        store.save_run(deal_id, doc.doc_id, run_id, records, report)
    return RunResult(run_id, records, report)


def _report(run, doc, deal_id, run_id, records, stages, candidate_ids, facts, decision_errors, sweep_ids) -> dict:
    later = [c for c in run.calls[1:] if c.usage.input_tokens]
    cache_in = sum(c.usage.input_tokens for c in later)
    by_cat: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in records:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {
        "run_id": run_id,
        "deal_id": deal_id,
        "doc_id": doc.doc_id,
        "pages": doc.page_count,
        "ids": len(doc.anchors),
        "candidates": len(candidate_ids),
        "swept_ids": len(sweep_ids),
        "uncited_candidates_after_sweep": len([i for i in uncited(candidate_ids, facts) if i not in run.none_ids]),
        "sweep_none": len(run.none_ids),
        "facts": len(records),
        "by_category": by_cat,
        "by_status": by_status,
        "seconds": {k: round(v, 2) for k, v in stages.items()},
        "cache_hit_calls_2_to_n": round(sum(c.usage.cached_tokens for c in later) / cache_in, 3) if cache_in else None,
        "output_tokens": sum(c.usage.output_tokens for c in run.calls),
        "performance": _performance(run.calls, stages),
        "failed_calls": [c.name for c in run.calls if c.status == "failed"],
        "decision_errors": decision_errors,
        "calls": [asdict(c) for c in run.calls],
    }


def _performance(calls: list[CallRecord], stages: dict[str, float]) -> dict:
    """Latency and speed across calls. For tokens/s the slow tail is the low end, so p5 is given too."""
    done = [c for c in calls if c.ttft_seconds is not None]
    tps = [c.tokens_per_second for c in done if c.tokens_per_second]
    extract_out = sum(c.usage.output_tokens for c in calls if c.kind == "extract")
    return {
        "call_seconds": _stats([c.seconds for c in done]),
        "model_seconds": _stats([c.model_seconds for c in done]),
        "ttft_seconds": _stats([c.ttft_seconds for c in done]),  # type: ignore[misc]
        "queue_seconds": _stats([c.queue_seconds for c in done]),
        "tokens_per_second": {**_stats(tps), "p5": percentile(tps, 5)},
        "extract_stage_tokens_per_second": round(extract_out / stages["extract"], 1) if stages.get("extract") else None,
    }

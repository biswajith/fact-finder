import asyncio

from conftest import ScriptedClient, task_name

from fact_extractor import prompts
from fact_extractor.llm import CallFailed, RateLimited
from fact_extractor.pipeline import Config, RecordingDecisions, extract
from fact_extractor.store import InMemoryFactStore

# One pass and the candidate-only sweep keep call counts predictable; the recall options
# have their own tests below.
FAST = Config(backoff_base=0, warmup_timeout=1, passes=1, sweep_all=False)

OUTPUTS = {
    "A": "B|Buyer is the City of Springfield|p1.1|\nB|Questions by email to jane.doe@springfield.gov|p1.2|\nEND|2\n",
    "B": "END|0\n",
    "K": "C|Records system contract with the City|p1.1|risk\nEND|1\n",
    "C": (
        "D|Proposals due 2027-03-03 17:00 ET|p1.3|\n"
        "D|Pre-bid meeting 2027-02-10|p1.4|\n"
        "S|Proposal page limit 50 pages|p3.1|\n"
        "Q|Due date 2027-03-03 vs 2027-03-05|p1.3,p3.2|\n"
        "END|4\n"
    ),
    "R": (
        "R|System supports 500 concurrent users|p2.1|\n"
        "R|Vendor provides 24/7 support|p2.2,p2.t1r1|mandatory\n"
        "R|Uptime 99.9%|p2.t1r2|\n"
        "END|3\n"
    ),
    "SWEEP": "R|Data retained for 7 years|p2.3|\nEND|1\n",
    "CHECK": "Q|Proposal due 2027-03-03 vs 2027-03-05|p1.3,p3.2|\nEND|1\n",
}


def handler(req):
    return OUTPUTS[task_name(req).split(".")[0].split("#")[0].rstrip("0123456789ab") or "R"]


SEQUENTIAL = Config(backoff_base=0, warmup_timeout=1, parallel_check=False, passes=1, sweep_all=False)


async def test_end_to_end(doc):
    client = ScriptedClient(handler)
    store = InMemoryFactStore()
    decisions = RecordingDecisions()
    res = await extract(doc, client, deal_id="deal_442", store=store, decisions=decisions, cfg=SEQUENTIAL, run_id="run_1")

    texts = {f["text"]: f for f in res.facts}
    due = texts["Proposals due 2027-03-03 17:00 ET"]
    assert due["citations"][0]["text"] == "Proposals are due March 3, 2027 at 5:00 PM Eastern."
    assert due["citations"][0]["section"] == "2. Schedule"
    assert due["status"] == "conflict" and due["conflicts"]
    assert texts["Data retained for 7 years"]["source_call"] == "SWEEP1"
    assert texts["Vendor provides 24/7 support"]["flags"] == ["mandatory"]
    # Extraction and check Q lines describe the same conflict and are merged.
    qs = [f for f in res.facts if f["category"] == "Q"]
    assert len(qs) == 1 and decisions.sent[0]["fact_id"] == qs[0]["fact_id"]
    assert res.report["uncited_candidates_after_sweep"] == 0
    assert store.find(deal_id="deal_442", category="R")
    assert store.run_report("run_1")["facts"] == len(res.facts)

    # Every call shares the cached prefix byte for byte; only the task differs.
    assert {(r.system, r.document) for r in client.requests} == {(prompts.SYSTEM, doc.tagged_text)}
    assert next(r for r in client.requests if task_name(r) == "CHECK").effort == "medium"
    assert res.report["cache_hit_calls_2_to_n"] > 0.5


async def test_first_call_streams_before_others_start(doc):
    order = []

    class Probe(ScriptedClient):
        async def complete(self, request, on_text):
            order.append(("start", task_name(request)))
            return await super().complete(request, on_text)

    client = Probe(handler)
    await extract(doc, client, deal_id="d", cfg=FAST)
    assert order[0] == ("start", "A")
    assert len(client.requests) >= 4


async def test_cut_requirement_call_is_split(doc):
    def h(req):
        name = task_name(req)
        if name == "R" and "pages 1 to 3" in req.task:
            return "R|System supports 500 concurrent users|p2.1|\n"  # no END: cut off
        return handler(req)

    res = await extract(doc, ScriptedClient(h), deal_id="d", cfg=FAST)
    calls = {c["name"]: c for c in res.report["calls"]}
    assert calls["R1"]["status"] == "split"
    assert {"R1a", "R1b"} <= set(calls)
    assert sum(f["text"] == "System supports 500 concurrent users" for f in res.facts) == 1


async def test_cut_category_call_splits_by_category(doc):
    def h(req):
        if task_name(req) == "A":
            return "B|Buyer is the City of Springfield|p1.1|\n"
        if task_name(req) == "A.E":
            return "END|0\n"
        return handler(req)

    res = await extract(doc, ScriptedClient(h), deal_id="d", cfg=FAST)
    names = [c["name"] for c in res.report["calls"]]
    assert "A.B" in names and "A.E" in names


async def test_failed_lines_kept_as_needs_review_without_a_repair_call(doc):
    def h(req):
        if task_name(req) == "C":
            return "D|Pre-bid meeting 2027-02-11|p1.4|\nD|Award date 2027-04-01|p77.1|\nEND|2\n"
        return handler(req)

    client = ScriptedClient(h)
    res = await extract(doc, client, deal_id="d", cfg=FAST)
    assert not any("REPAIR" in task_name(r) for r in client.requests)
    texts = {f["text"]: f for f in res.facts}
    wrong = texts["Pre-bid meeting 2027-02-11"]
    assert wrong["status"] == "needs_review" and any("2027-02-11" in p for p in wrong["problems"])
    award = texts["Award date 2027-04-01"]
    assert award["status"] == "needs_review" and award["unresolved_ids"] == ["p77.1"]


async def test_rate_limit_backs_off_and_lowers_parallelism(doc):
    hits = {"n": 0}

    def h(req):
        if task_name(req) == "B" and hits["n"] < 2:
            hits["n"] += 1
            return RateLimited("429")
        return handler(req)

    res = await extract(doc, ScriptedClient(h), deal_id="d", cfg=FAST)
    b = next(c for c in res.report["calls"] if c["name"] == "B")
    assert b["status"] == "ok" and b["retries"] == 2


async def test_call_error_retried_once_then_failed(doc):
    def h(req):
        if task_name(req) == "B":
            return CallFailed("boom")
        return handler(req)

    client = ScriptedClient(h)
    res = await extract(doc, client, deal_id="d", cfg=FAST)
    assert res.report["failed_calls"] == ["B"]
    assert sum(task_name(r) == "B" for r in client.requests) == 2
    assert res.facts  # the rest of the run still lands


async def test_timeout_counts_as_call_error(doc):
    class Slow(ScriptedClient):
        async def complete(self, request, on_text):
            if task_name(request) == "B":
                await asyncio.sleep(1)
            return await super().complete(request, on_text)

    cfg = Config(backoff_base=0, warmup_timeout=1, call_timeout=0.05, passes=1, sweep_all=False)
    res = await extract(doc, Slow(handler), deal_id="d", cfg=cfg)
    assert res.report["failed_calls"] == ["B"]


async def test_sweep_none_and_chunking(doc):
    def h(req):
        if task_name(req).startswith("SWEEP"):
            ids = req.task.split("yet:\n", 1)[1].split("\n", 1)[0].split(", ")
            return "".join(f"NONE|no fact|{i}|\n" for i in ids) + f"END|{len(ids)}\n"
        if task_name(req) == "R":
            return "END|0\n"
        return handler(req)

    client = ScriptedClient(h)
    res = await extract(doc, client, deal_id="d", cfg=Config(backoff_base=0, sweep_chunk=2, parallel_check=False, passes=1, sweep_all=False))
    sweeps = [r for r in client.requests if task_name(r).startswith("SWEEP")]
    assert len(sweeps) >= 2
    assert res.report["uncited_candidates_after_sweep"] == 0
    assert res.report["sweep_none"] == res.report["candidates"] - 3  # p1.2, p1.4, p3.1 are cited


async def test_parallel_check(doc):
    res = await extract(doc, ScriptedClient(handler), deal_id="d", cfg=Config(backoff_base=0, parallel_check=True, passes=1, sweep_all=False))
    assert "sweep_and_check" in res.report["seconds"]
    assert any(f["category"] == "Q" for f in res.facts)


async def test_rerun_replaces_facts_in_store(doc):
    store = InMemoryFactStore()
    for run in ("r1", "r2"):
        await extract(doc, ScriptedClient(handler), deal_id="d", store=store, cfg=FAST, run_id=run)
    facts = store.find(deal_id="d")
    assert {f["run_id"] for f in facts} == {"r2"}
    assert len({f["fact_id"] for f in facts}) == len(facts)


async def test_performance_report(doc):
    from fact_extractor.pipeline import percentile

    assert percentile([1, 2, 3, 4, 5], 50) == 3 and percentile([1, 2, 3, 4, 5], 95) == 4.8
    res = await extract(doc, ScriptedClient(handler, chunk=3), deal_id="d", cfg=FAST)
    perf = res.report["performance"]
    assert perf["ttft_seconds"]["n"] == len(res.report["calls"])
    assert perf["model_seconds"]["p95"] >= perf["model_seconds"]["p50"] >= 0
    assert set(perf["tokens_per_second"]) == {"n", "p50", "p95", "max", "p5"}


async def test_second_pass_adds_missed_facts_without_duplicates(doc):
    calls = {"n": 0}

    def h(req):
        if task_name(req) == "R":
            calls["n"] += 1
            if calls["n"] == 1:  # first pass misses the uptime row and words one fact differently
                return "R|System supports 500 concurrent users|p2.1|\nEND|1\n"
            return (
                "R|Support 500 concurrent users in the system|p2.1|\n"
                "R|Vendor provides 24/7 support|p2.2,p2.t1r1|\n"
                "R|Uptime 99.9%|p2.t1r2|\nEND|3\n"
            )
        return handler(req)

    cfg = Config(backoff_base=0, warmup_timeout=1, passes=2, sweep_all=False)
    client = ScriptedClient(h)
    res = await extract(doc, client, deal_id="d", cfg=cfg)
    names = {c["name"] for c in res.report["calls"]}
    assert {"A", "A#2", "R1", "R1#2"} <= names
    r = [f["text"] for f in res.facts if f["category"] == "R"]
    assert sum("500 concurrent users" in t for t in r) == 1  # paraphrases across passes merge
    assert "Uptime 99.9%" in r  # only the second pass found it


def test_union_passes_keeps_split_requirements():
    from fact_extractor.merge import union_passes
    from fact_extractor.models import Fact

    def F(t, ids):
        return Fact("R", t, ids, "", "valid", "R1")

    first = [F("Provide 24/7 phone support", ["p2.2"]), F("Provide an online ticket portal", ["p2.2"])]
    second = [F("Vendor must provide 24/7 phone support", ["p2.2"]), F("Provide online ticket portal", ["p2.2"]),
              F("Provide monthly reports", ["p2.2"])]
    out = union_passes(first, second)
    assert [f.text for f in out] == [
        "Vendor must provide 24/7 phone support", "Provide an online ticket portal", "Provide monthly reports",
    ]


async def test_sweep_all_includes_sentences_without_candidate_words(doc):
    from fact_extractor import planner

    assert "p1.1" not in planner.candidates(doc) and "p1.1" in planner.sweepable(doc)
    # Calls A and K find nothing, so the buyer sentence p1.1 (no shall/must) is uncited.
    client = ScriptedClient(lambda req: "END|0\n" if task_name(req) in ("A", "K1", "K2", "K3") else handler(req))
    cfg = Config(backoff_base=0, warmup_timeout=1, passes=1, sweep_all=True)
    res = await extract(doc, client, deal_id="d", cfg=cfg)
    sweep = next(r for r in client.requests if task_name(r).startswith("SWEEP"))
    assert "p1.1" in sweep.task
    assert res.report["swept_ids"] > res.report["candidates"]


async def test_check_gets_its_own_token_budget(doc):
    client = ScriptedClient(handler)
    await extract(doc, client, deal_id="d", cfg=Config(backoff_base=0, passes=1, sweep_all=False))
    budgets = {task_name(r): r.max_output_tokens for r in client.requests}
    assert budgets["CHECK"] == 8000 and budgets["A"] == 3000


async def test_stages_can_be_switched_off(doc):
    client = ScriptedClient(handler)
    cfg = Config(backoff_base=0, warmup_timeout=1, passes=1, sweep_all=False, sweep=False, check=False)
    res = await extract(doc, client, deal_id="d", cfg=cfg)
    names = {task_name(r) for r in client.requests}
    assert not any(n.startswith(("SWEEP", "CHECK")) for n in names)
    assert "Data retained for 7 years" not in {f["text"] for f in res.facts}

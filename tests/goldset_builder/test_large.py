"""Large sources: profile, structural chunks, coverage units, and the two-level, coverage-driven loop."""

import json
from pathlib import Path

from goldset.chunks import chunk_source, leaf_count
from goldset.config import ChunkingCfg, Config
from goldset.coverage import build_atlas, covered_by, measure
from goldset.profile import pattern, profile
from goldset.runner import run
from goldset.schemas import Evidence, Item, Source, Span
from goldset.sources import leaves, load_sources

from .fakes import E, LargeScriptedBrain

LARGE = Path(__file__).parent.parent.parent / "examples" / "goldset" / "large"


def _orders() -> Source:
    return load_sources(LARGE / "sources")[0]


def test_profile_finds_enums_nulls_missing_keys_and_numeric_bounds() -> None:
    st = profile(_orders().data)
    assert pattern("/orders/17/lines/0/qty") == "/orders/*/lines/*/qty"
    status = st["/orders/*/status"]
    assert status.is_enum and set(status.values) == {'"DLV"', '"SHP"', '"PAI"', '"NEW"', '"CAN"'}
    assert st["/orders/*/delivered_at"].nulls > 0 and st["/orders/*/order_id"].many_values
    coupon = st["/orders/*/coupon"]
    assert coupon.missing == coupon.parents - coupon.count and coupon.missing_example.startswith("/orders/")
    qty = st["/orders/*/lines/*/qty"]
    assert not qty.is_enum and (qty.num_min, qty.num_max) == (1, 4)  # numbers get boundaries, not one unit per value


def test_json_chunks_partition_every_leaf_and_respect_the_size() -> None:
    src = _orders()
    chunks = chunk_source(src, ChunkingCfg(json_max_leaves=300))
    assert len(chunks) > 10 and all(c.size <= 300 for c in chunks)
    seen = [p for c in chunks for root in c.pointers for p, _ in leaves(_at(src.data, root), root)]
    assert len(seen) == len(set(seen)) == leaf_count(src.data)  # every leaf in exactly one chunk


def _at(data: object, ptr: str) -> object:
    from goldset.sources import resolve_pointer
    return resolve_pointer(data, ptr)


def test_text_chunks_follow_sections_and_cover_every_line() -> None:
    text = "\n".join(f"## Section {s}\n\n" + "\n\n".join(f"Paragraph {s}.{p} " + "word " * 60 for p in range(6)) for s in range(8))
    src = Source(id="big.md", kind="text", text=text)
    chunks = chunk_source(src, ChunkingCfg(text_max_chars=2000))
    assert len(chunks) > 4 and all(c.size <= 2000 for c in chunks)
    assert all(a.end_line is not None and b.start_line is not None and a.end_line < b.start_line for a, b in zip(chunks, chunks[1:]))
    assert all(c.title.startswith("Section") for c in chunks)


def test_units_list_rare_edge_cases_first_and_evidence_covers_them() -> None:
    src = _orders()
    atlas = build_atlas(src, Config())
    left = measure(atlas.units, set()).uncovered
    assert left[0].id == 'value:/orders/*/status="CAN"'  # rarest value first
    kinds = {u.kind for u in left[:8]}
    assert kinds <= {"value", "null", "missing"}
    missing = next(u for u in atlas.units if u.id == "missing:/orders/*/coupon")
    item = Item(id="T-001", task_id="t", span=Span(pointer=missing.example), case_type="edge", instruction="", acceptance=[],
                chunk_id=missing.chunk_id)
    ev = [E(None, missing.example, None),
          E(None, f"{missing.example}/status", None)]
    hit = covered_by(item, ev, src, atlas.chunks, atlas.units)
    assert {"missing:/orders/*/coupon", f"chunk:{missing.chunk_id}", "path:/orders/*/status"} <= hit
    assert any(h.startswith("value:/orders/*/status=") for h in hit)


async def test_large_json_is_planned_per_chunk_swept_and_driven_to_coverage(tmp_path: Path) -> None:
    brain = LargeScriptedBrain()
    logs: list[str] = []
    state = await run(LARGE / "sources", LARGE / "prompts" / "support_lookup.md", tmp_path, Config(), brain=brain, log=logs.append)
    items = list(state["items"].values())
    atlas = build_atlas(_orders(), Config())

    # level 1 then level 2: one call per chunk with a budget, never more items than budgeted
    assert brain.ledger.calls["allocate"] == 1 and brain.ledger.calls["plan_chunk"] == len(atlas.chunks)
    first = [i for i in items if i.parent is None and i.history and i.history[0].round == 1 and not i.aggregate]
    assert len(first) == len(atlas.chunks) and {i.chunk_id for i in first} == {c.id for c in atlas.chunks}
    assert any("outside chunk" in m for m in logs)  # the planner's whole-document span was refused

    # the reconciler saw what was uncovered, and coverage rose each round to the target
    assert all("UNCOVERED UNITS" in u for s, u in brain.prompts if s == "reconcile")
    ratios = [float(m.rsplit(" ", 1)[1].rstrip("%")) for m in logs if "; coverage " in m]
    assert ratios == sorted(ratios) and ratios[-1] >= 90
    cov = json.loads((tmp_path / "coverage.json").read_text())["support_lookup@orders.json"]
    assert cov["ratio"] >= 0.9

    # the sweep flagged one case from another chunk; the adjudicator saw the passage and decided
    swept = [i for i in items if any(a.gate and a.gate.sweep for a in i.history)]
    assert len(swept) == 1 and "C02" in swept[0].history[0].gate.sweep  # type: ignore[union-attr]
    assert swept[0].status == "accepted" and swept[0].history[0].verdict is not None

    # aggregates: computed with the tool; a number "counted by reading" is caught by re-running the query
    aggs = [i for i in items if i.aggregate]
    assert len(aggs) == 2 and all(i.chunk_id is None and i.span.pointer == "/orders" for i in aggs)
    assert all(i.status == "accepted" and i.attempts == 2 for i in aggs)
    assert all("query result mismatch" in i.history[0].check_errors[0] for i in aggs)
    assert brain.agent_calls["work"] > 0 and not any(a.gate and a.gate.sweep for i in aggs for a in i.history)

    golden = [json.loads(x) for x in (tmp_path / "golden.jsonl").read_text().splitlines()]
    assert len(golden) <= Config().dataset.max_items_large
    cancelled = next(g for g in golden if g["case_type"] == "aggregate" and "CAN" in g["case_input"])
    assert cancelled["expected_output"] == "The answer is 6." and cancelled["evidence"][0]["result_json"] == "6"
    assert 'value:/orders/*/status="CAN"' in cancelled["provenance"]["covers"]
    assert "query_fits" in cancelled["provenance"]["gate_scores"]
    assert all(g["provenance"]["covers"] and (g["provenance"]["chunk"] or g["provenance"]["aggregate"]) for g in golden)
    assert "## Coverage" in (tmp_path / "report.md").read_text()


def test_query_engine_and_its_extra_functions() -> None:
    from goldset.query import QueryError, query_tool, run_query, same_result

    data = _orders().data
    assert run_query(data, "length(orders[?status=='CAN'])") == 6
    by = run_query(data, "count_by(orders, &status)")
    assert sum(by.values()) == 400 and by["CAN"] == 6
    assert run_query(data, "sum_by(orders, &currency, &shipping_minor)")["GBP"] > 0
    assert run_query(data, "orders[0].lines[].mul(qty, unit_price_minor)") == [
        ln["qty"] * ln["unit_price_minor"] for ln in data["orders"][0]["lines"]]
    assert run_query(data, "round(div(`1`, `3`), `2`)") == 0.33
    assert same_result(0.1 + 0.2, 0.3) and not same_result(True, 1)
    late = run_query(data, "length(orders[?delivered_at==null && before(promised_by, '2026-10-26')])")
    assert late == sum(1 for o in data["orders"] if o["delivered_at"] is None and o["promised_by"] < "2026-10-26")
    assert run_query(data, "after('2026-10-01T10:00:00Z', '2026-10-01')") is True
    import pytest
    with pytest.raises(QueryError):
        run_query(data, "orders[?")
    with pytest.raises(QueryError):
        run_query(data, "div(`1`, `0`)")
    tool = query_tool(data, 100)
    assert tool.invoke({"expression": "orders[?"}).startswith("error:")
    assert "truncated" in tool.invoke({"expression": "orders[].order_id"})


def test_checks_rerun_cited_queries() -> None:
    from goldset.checks import check_candidate
    from goldset.schemas import Candidate, Task

    src = _orders()
    task = Task(id="t", prompt_id="p", source_id=src.id, mode="cases")
    item = Item(id="T-001", task_id="t", span=Span(pointer="/orders"), case_type="aggregate", instruction="", acceptance=[], aggregate=True)

    def cand(*ev: Evidence) -> Candidate:
        return Candidate(case_input="How many?", expected_output="6", evidence=list(ev), rationale="")

    q = "length(orders[?status=='CAN'])"
    assert check_candidate(cand(E(query=q, result="6")), item, task, src, []) == []
    assert "query result mismatch" in check_candidate(cand(E(query=q, result="5")), item, task, src, [])[0]
    assert "query failed" in check_candidate(cand(E(query="orders[?", result="1")), item, task, src, [])[0]
    assert "query result missing" in check_candidate(cand(E(query=q, result=None)), item, task, src, [])[0]
    errs = check_candidate(cand(E(None, "/orders/40/status", '"CAN"')), item, task, src, [])
    assert errs == ["computed evidence missing: an aggregate case must cite the query_json query and result behind each number"]

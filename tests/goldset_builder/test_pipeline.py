"""The whole graph on the examples with a scripted brain: every self-correction path, then a free re-run."""

import json
from pathlib import Path

from goldset.config import Config
from goldset.runner import run

from .fakes import ScriptedBrain

EX = Path(__file__).parent.parent.parent / "examples" / "goldset"


async def test_loop_corrects_itself_and_routes_the_rest(tmp_path: Path) -> None:
    brain = ScriptedBrain()
    logs: list[str] = []
    state = await run(EX / "sources", EX / "prompts", tmp_path, Config(), brain=brain, log=logs.append)
    items = state["items"]
    by = {i.instruction.split(":")[0]: i for i in items.values()}

    assert "outside" not in by  # span outside the source: code refused the planner's item
    assert by["london"].status == "accepted" and by["london"].attempts == 1
    assert by["order"].status == "accepted" and by["order"].attempts == 2  # wrong pointer value caught by code
    assert "4950" in by["order"].history[0].check_errors[0]
    assert by["alcohol"].status == "accepted" and "not verbatim" in by["alcohol"].history[0].check_errors[0]
    late = by["lateclaim"]
    assert late.status == "accepted" and late.history[0].outcome == "revised" and late.history[-1].by == "adjudicator"
    assert by["dropme"].status == "dropped"
    assert by["impossible"].status == "needs_human" and by["impossible"].attempts == 3
    assert state["tasks"]["order_summary@orders/order-1001.json"].mode == "reference"

    golden = [json.loads(line) for line in (tmp_path / "golden.jsonl").read_text().splitlines()]
    assert len(golden) == 4
    rec = next(g for g in golden if g["case_type"] == "reference_output")
    assert rec["case_input"] == "" and json.loads(rec["expected_output"])["amount_due"] == 120.15
    assert rec["provenance"]["attempts"] == 2 and rec["provenance"]["gate_scores"]["glossary"] > 0.9
    human = (tmp_path / "needs_human.jsonl").read_text().splitlines()
    assert len(human) == 1 and "failed 3 attempts" in json.loads(human[0])["note"]
    report = (tmp_path / "report.md").read_text()
    assert "Accepted: 4 (1 on the first try, 3 after self-correction)" in report
    assert (tmp_path / "rounds" / "round_03.json").exists() and (tmp_path / "plan.json").exists()

    # The worker saw the reconciler's feedback and its rejected candidate on the retry.
    retry = [u for s, u in brain.prompts if s == "work" and "alcohol:" in u][1]
    assert "use the exact policy wording" in retry and "PREVIOUS CANDIDATE" in retry

    # Re-running into the same folder replays every call from the cache.
    again = ScriptedBrain()
    state2 = await run(EX / "sources", EX / "prompts", tmp_path, Config(), brain=again, log=logs.append)
    assert sum(again.ledger.calls.values()) == 0
    assert {k: v.status for k, v in state2["items"].items()} == {k: v.status for k, v in items.items()}


async def test_round_budget_sends_open_items_to_a_human(tmp_path: Path) -> None:
    cfg = Config.model_validate({"loop": {"max_rounds": 1}})
    state = await run(EX / "sources", EX / "prompts", tmp_path, cfg, brain=ScriptedBrain(), log=lambda _: None)
    st = {i.instruction.split(":")[0]: i.status for i in state["items"].values()}
    assert st["london"] == "accepted"
    assert st["lateclaim"] == "needs_human"  # revised by the adjudicator, but never re-verified
    assert st["alcohol"] == "needs_human"

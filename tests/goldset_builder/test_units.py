"""Pure pieces: source loading, pointers, code checks, gate triage."""

from pathlib import Path

import pytest
from langchain_openai.decisions import ChoiceAnswer, DecisionResponse, PredicateAnswer, RefusalAnswer

from goldset.checks import check_candidate, normalize
from goldset.config import GateCfg, RenderCfg, load_config
from goldset.gate import triage
from goldset.schemas import Candidate, Evidence, Item, Span, Task
from goldset.sources import leaves, load_prompts, load_sources, make_tasks, render_span, resolve_pointer, span_error

from .fakes import E

EX = Path(__file__).parent.parent.parent / "examples" / "goldset"


def test_json_sources_take_the_folder_glossary_and_glossaries_are_not_sources() -> None:
    srcs = {s.id: s for s in load_sources(EX / "sources")}
    assert set(srcs) == {"orders/order-1001.json", "travel-policy.md"}
    order = srcs["orders/order-1001.json"]
    assert order.kind == "json" and order.glossary_id == "orders/glossary.md"
    assert order.glossary and "minor currency units" in order.glossary


def test_same_stem_glossary_wins(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text('{"x": 1}')
    (tmp_path / "a.md").write_text("x: own")
    (tmp_path / "glossary.md").write_text("x: shared")
    (tmp_path / "b.json").write_text('{"x": 2}')
    srcs = {s.id: s for s in load_sources(tmp_path)}
    assert set(srcs) == {"a.json", "b.json"}
    assert srcs["a.json"].glossary == "x: own" and srcs["b.json"].glossary == "x: shared"


def test_prompts_front_matter_and_task_matching() -> None:
    prompts = {p.id: p for p in load_prompts(EX / "prompts")}
    assert prompts["order_summary"].output_format == "json"
    assert prompts["policy_qa"].cases == 4 and prompts["policy_qa"].text.startswith("You are")
    tasks = make_tasks(list(prompts.values()), load_sources(EX / "sources"))
    assert [t.id for t in tasks] == ["order_summary@orders/order-1001.json", "policy_qa@travel-policy.md"]


def test_pointers() -> None:
    data = {"a/b": [{"c": None}], "e": []}
    assert resolve_pointer(data, "/a~1b/0/c") is None
    assert resolve_pointer(data, "") == data
    with pytest.raises(KeyError):
        resolve_pointer(data, "/a~1b/3")
    assert dict(leaves(data)) == {"/a~1b/0/c": None, "/e": []}


def test_render_and_spans() -> None:
    src = {s.id: s for s in load_sources(EX / "sources")}["travel-policy.md"]
    view = render_span(src, Span(start_line=13, end_line=13), RenderCfg(context_lines=1))
    assert "13 | In London" in view and "12 | The nightly" in view and "15 |" not in view
    assert span_error(src, Span(start_line=1, end_line=999)) is not None
    assert span_error(src, Span(pointer="")) is not None  # text source needs lines


def _item(kind: str = "lookup") -> Item:
    return Item(id="T-001", task_id="t", span=Span(start_line=1, end_line=2), case_type=kind, instruction="", acceptance=[])


def test_checks_catch_invented_quotes_wrong_values_bad_json_and_duplicates() -> None:
    srcs = {s.id: s for s in load_sources(EX / "sources")}
    text, order = srcs["travel-policy.md"], srcs["orders/order-1001.json"]
    cases = Task(id="t", prompt_id="p", source_id=text.id, mode="cases")
    good = Candidate(case_input="Q?", expected_output="A", rationale="",
                     evidence=[E("Alcohol  is not\nreimbursed.", None, None)])
    assert check_candidate(good, _item(), cases, text, []) == []  # whitespace differences are fine
    bad = good.model_copy(update={"evidence": [E("Alcohol is never reimbursed.", None, None)]})
    assert "not verbatim" in check_candidate(bad, _item(), cases, text, [])[0]
    assert check_candidate(good, _item(), cases, text, ["q?"]) == ["case_input duplicates an accepted case"]

    ref = Task(id="t", prompt_id="p", source_id=order.id, mode="reference", output_format="json")
    ev = [E(None, "/discount_pct", "10"), E(None, "/delivered_at", "null")]
    ok = Candidate(case_input="", expected_output='{"a": 1}', evidence=ev, rationale="")
    assert check_candidate(ok, _item(), ref, order, []) == []
    wrong = ok.model_copy(update={"expected_output": "{a: 1}", "evidence": [E(None, "/nope", "1")]})
    errs = check_candidate(wrong, _item(), ref, order, [])
    assert any("not valid JSON" in e for e in errs) and any("does not exist" in e for e in errs)
    assert normalize("“Hi”  there") == '"Hi" there'


def _resp(preds: dict[str, float], agree: str | None = "equivalent", conf: float = 0.9, refuse: bool = False) -> DecisionResponse:
    answers: dict = {f"c0_{k}": PredicateAnswer(type="predicate", probability=p) for k, p in preds.items()}
    if agree:
        answers["c0_agreement"] = ChoiceAnswer(type="choice", choice=agree, probabilities={agree: conf}, confidence=conf)
    if refuse:
        answers["c0_format"] = RefusalAnswer(type="refusal")
    answers["c1_grounded"] = PredicateAnswer(type="predicate", probability=0.0)  # another candidate: ignored
    return DecisionResponse(model="gpt-6-luna", answers=answers)


def test_triage_bands() -> None:
    cfg = GateCfg.model_validate({})
    assert triage(_resp({"grounded": 0.97, "correct": 0.9}), "c0_", cfg).outcome == "pass"
    assert triage(_resp({"grounded": 0.1, "correct": 0.6}), "c0_", cfg).outcome == "fail"
    assert triage(_resp({"grounded": 0.6}), "c0_", cfg).outcome == "unsure"
    assert triage(_resp({"grounded": 0.99}, agree="conflict"), "c0_", cfg).outcome == "unsure"
    assert triage(_resp({"grounded": 0.99}, conf=0.3), "c0_", cfg).outcome == "unsure"
    assert triage(_resp({"grounded": 0.99}, refuse=True), "c0_", cfg).outcome == "unsure"
    r = triage(_resp({"grounded": 0.1}), "c0_", cfg)
    assert r.failing == ["grounded: p=0.10"]


def test_config_file_is_optional_and_partial(tmp_path: Path) -> None:
    assert load_config(None).models.planner.effort == "high"
    p = tmp_path / "c.yaml"
    p.write_text("loop:\n  max_rounds: 2\n")
    cfg = load_config(p)
    assert cfg.loop.max_rounds == 2 and cfg.gate.accept == 0.85

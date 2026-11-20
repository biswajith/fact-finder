from types import SimpleNamespace

import pytest

pytest.importorskip("deepeval")

from deepeval.models import DeepEvalBaseLLM  # noqa: E402
from deepeval.models.llms.openai_model import OpenAIModel  # noqa: E402
from deepeval.test_case import SingleTurnParams  # noqa: E402

from fact_extractor import evalsuite as ev  # noqa: E402
from fact_extractor import precision  # noqa: E402
from fact_extractor.compare import Item  # noqa: E402
from fact_extractor.score import score  # noqa: E402


def rec(cat, text, ids, also=None, fid=None):
    return {
        "fact_id": fid or f"f_{ids[0]}_{cat}", "category": cat, "text": text, "flags": [], "also": also,
        "citations": [{"id": i, "section": "Sec", "text": f"source {i}"} for i in ids],
    }


GOLD = [
    Item("D", "Due on a date", ["p1.1"], []),
    Item("C", "A contract term", ["p2.1", "p2.2"], [], ["R"]),
    Item("C", "Same, filed under the alternate", ["p2.5"], [], ["R"]),
    Item("G", "A gate", ["p3.1"], []),
    Item("R", "Never extracted", ["p4.1"], []),
    Item("Q", "Two sides disagree", ["p5.1", "p5.2"], []),
    Item("Q", "Another disagreement", ["p5.8", "p5.9"], []),
    Item("E", "Filed through the also code", ["p6.1"], []),
    Item("B", "No IDs, so no case", [], []),
]
RECORDS = [
    rec("D", "Proposals are due on the date", ["p1.1"]),
    rec("R", "Contract term as a requirement", ["p2.1"]),
    rec("R", "Alternate code", ["p2.5"]),
    rec("D", "Gate filed as a deadline", ["p3.1"]),
    rec("Q", "Sides disagree", ["p5.2"]),
    rec("C", "Filed as contract", ["p6.1"], also="E"),
    rec("Q", "Ignored for a non-Q reference", ["p4.1"]),
]


class StubModel(DeepEvalBaseLLM):
    def __init__(self):
        super().__init__("stub")

    def load_model(self):
        return self

    def generate(self, prompt, schema=None):
        raise AssertionError("no model call expected")

    async def a_generate(self, prompt, schema=None):
        raise AssertionError("no model call expected")

    def get_model_name(self):
        return "stub"


def measured():
    out = []
    for case in ev.reference_cases(GOLD, RECORDS):
        m = ev.ReferenceFound()
        m.measure(case)
        out.append((case, m))
    return out


def test_reference_cases_shape():
    cases = ev.reference_cases(GOLD, RECORDS)
    assert len(cases) == 8  # the reference fact without IDs has no case
    first = cases[0]
    assert first.expected_output == "Due on a date"
    assert first.actual_output == "Proposals are due on the date"
    assert first.name == "D p1.1" and first.tags == ["D", "p1.1"]
    assert first.metadata == {"code": "D", "alt": [], "ids": ["p1.1"], "main_id": "p1.1", "filed_as": ["D"], "flags": []}
    missed = cases[4]
    assert missed.actual_output == ev.NOT_FOUND and missed.metadata["filed_as"] == []
    assert cases[1].metadata["alt"] == ["R"] and cases[1].metadata["filed_as"] == ["R"]


def test_reference_found_scores():
    got = {c.name: (m.score, m.is_successful(), m.reason) for c, m in measured()}
    assert got["C p2.1"][:2] == (1.0, True)  # alternate code counts as the right code
    assert got["C p2.5"][:2] == (1.0, True)
    assert got["D p1.1"][:2] == (1.0, True)
    assert got["G p3.1"][:2] == (0.5, False) and "reference code is G" in got["G p3.1"][2]
    assert got["R p4.1"][:2] == (0.0, False) and "Missed" in got["R p4.1"][2]  # a Q fact does not count for R
    assert got["Q p5.1"][:2] == (1.0, True)  # a Q fact cites the other side of the contradiction
    assert got["Q p5.8"][:2] == (0.0, False)
    assert got["E p6.1"][:2] == (1.0, True)  # found through the `also` code


def test_reference_found_threshold_is_an_argument():
    case = ev.reference_cases(GOLD, RECORDS)[3]  # found under another code: 0.5
    lenient = ev.ReferenceFound(threshold=0.5)
    lenient.measure(case)
    assert lenient.is_successful() and lenient.success is True
    assert ev.ReferenceFound().__name__ == "Reference found"


async def test_reference_found_async_matches_sync():
    case = ev.reference_cases(GOLD, RECORDS)[3]
    assert await ev.ReferenceFound().a_measure(case) == 0.5


def test_pass_rates_equal_score_py():
    s = score(GOLD, RECORDS)
    scores = [m.score for _, m in measured()]
    assert len(scores) == s["gold"]
    assert round(sum(x >= 0.5 for x in scores) / len(scores), 3) == s["recall"]
    assert round(sum(x == 1.0 for x in scores) / len(scores), 3) == s["recall_same_code"]
    assert 0 < s["recall_same_code"] < s["recall"] < 1  # the fixture exercises every outcome


def many(n):
    return [rec(("B", "C", "D")[i % 3], f"Fact number {i}", [f"p{i}.1"], fid=f"f{i}") for i in range(n)]


def test_fact_cases_shape_and_seeded_sample():
    records = many(40)
    all_cases = ev.fact_cases(records)
    assert len(all_cases) == 40
    c = all_cases[0]
    assert c.actual_output == "Fact number 0" and c.retrieval_context == ["[p0.1] (Sec) source p0.1"]
    assert c.name == "B f0" and c.tags == ["B"] and "buyer information" in c.input
    a = [x.name for x in ev.fact_cases(records, sample=10, seed=3)]
    assert a == [x.name for x in ev.fact_cases(records, sample=10, seed=3)] and len(set(a)) == 10
    assert a != [x.name for x in ev.fact_cases(records, sample=10, seed=4)]
    # the same facts a person labels with `precision.sample`
    assert a == [f"{r['category']} {r['fact_id']}" for r in precision.sample(records, 10, 3)]


def test_fact_without_citation_still_has_context():
    r = rec("B", "x", ["p1.1"])
    r["citations"] = []
    assert ev.fact_cases([r])[0].retrieval_context == ["(no resolvable citation)"]


def test_judged_metrics_are_constructed_with_the_right_params():
    stub = StubModel()
    sf = ev.same_fact(stub)
    assert sf.evaluation_params == [SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT]
    assert sf.criteria == ev.SAME_FACT_CRITERIA and sf.threshold == 0.5 and sf.model is stub
    u = ev.useful(stub)
    assert u.evaluation_params == [SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT]
    assert "useful - a bid manager would want this line" in u.criteria and "noise" in u.criteria
    s = ev.supported(stub)
    assert s.threshold == 1.0 and s.include_reason and s.model is stub
    assert SingleTurnParams.RETRIEVAL_CONTEXT in s._required_params


def test_useful_criteria_quote_the_precision_prompt():
    for line in ev.USEFUL_CRITERIA.split("\n\n")[1].splitlines()[:1]:
        assert line.split(": ", 1)[1] in precision.SYSTEM
    assert "bid manager decides whether to bid" in ev.USEFUL_CRITERIA


def test_judge_model_name(monkeypatch):
    monkeypatch.delenv("FACT_EXTRACTOR_MODEL", raising=False)
    assert ev.judge_model() == "gpt-6-luna"
    monkeypatch.setenv("FACT_EXTRACTOR_MODEL", "gpt-x")
    assert ev.judge_model() == "gpt-x"


class FakeCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, prompt_tokens_details=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], usage=usage)


async def test_default_judge_model_name_works_in_deepeval_without_unsupported_params(monkeypatch):
    """DeepEval lists the project's default model: a plain name is accepted and no `temperature` is sent."""
    monkeypatch.delenv("FACT_EXTRACTOR_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    model = OpenAIModel(model=ev.judge_model())
    fake = FakeCompletions()
    monkeypatch.setattr(model, "load_model", lambda async_mode=False: SimpleNamespace(chat=SimpleNamespace(completions=fake)))
    text, _ = await model.a_generate("hello")
    assert text == "ok"
    assert fake.calls[0]["model"] == "gpt-6-luna" and "temperature" not in fake.calls[0]
    assert model.supports_log_probs() is False  # GEval then scores from the model's JSON answer, not logprobs

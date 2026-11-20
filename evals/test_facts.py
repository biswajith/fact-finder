"""Is each extracted fact backed by its cited text, and worth a bid manager's time?

Judges a seeded sample (EVAL_SAMPLE, default 30) of the run's facts. Needs OPENAI_API_KEY.
"""

import os

import pytest
from conftest import facts, sample_size

from deepeval import assert_test
from fact_extractor.evalsuite import fact_cases, judge_model, supported, useful

if not os.environ.get("OPENAI_API_KEY"):
    pytest.skip("set OPENAI_API_KEY (or put it in .env) to run the judged fact tests", allow_module_level=True)

CASES = fact_cases(facts(), sample=sample_size())


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_fact(case):
    model = judge_model()
    assert_test(case, [supported(model), useful(model)])

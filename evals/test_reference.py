"""Was each reference fact found, and under the right code? One test per reference fact.

Without EVAL_JUDGE this makes no model call. With EVAL_JUDGE=1 every found fact is also
checked by the `same_fact` judge (needs OPENAI_API_KEY).
"""

import pytest
from conftest import facts, gold, judging

from deepeval import assert_test
from fact_extractor.evalsuite import NOT_FOUND, ReferenceFound, judge_model, reference_cases, same_fact

CASES = reference_cases(gold(), facts())


@pytest.mark.parametrize("case", CASES, ids=[f"{c.name}#{i}" for i, c in enumerate(CASES)])
def test_reference(case):
    metrics = [ReferenceFound()]
    if judging() and case.actual_output != NOT_FOUND:
        metrics.append(same_fact(judge_model()))
    assert_test(case, metrics)

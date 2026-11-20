"""Inputs for the DeepEval suite, read from environment variables (README, "Evals").

    EVAL_FACTS   facts.json of the run to evaluate
    EVAL_GOLD    one or more reference files (CODE|fact|IDs|flags), separated by commas or os.pathsep
    EVAL_SAMPLE  how many extracted facts to judge in test_facts.py (default 30)
    EVAL_JUDGE   1 to add the model-judged `same_fact` metric to test_reference.py

An unset input skips the test with a message. Telemetry is opted out before DeepEval is imported.
"""

import json
import os
import re

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")

import pytest  # noqa: E402

from fact_extractor.cli import load_env  # noqa: E402
from fact_extractor.compare import Item, read_lines  # noqa: E402

load_env()


def _need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"set {name} to run this suite (see evals/conftest.py)", allow_module_level=True)
    return value


def facts() -> list[dict]:
    with open(_need("EVAL_FACTS")) as f:
        return json.load(f)


def gold() -> list[Item]:
    paths = [p for p in re.split(rf"[,{re.escape(os.pathsep)}]", _need("EVAL_GOLD")) if p.strip()]
    return [item for p in paths for item in read_lines(p.strip())]


def sample_size() -> int:
    return int(os.environ.get("EVAL_SAMPLE", "30"))


def judging() -> bool:
    return os.environ.get("EVAL_JUDGE") == "1"

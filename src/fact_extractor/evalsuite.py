"""DeepEval view of the project's own scoring (run from `evals/`, not from `tests/`).

`score.py`, `judge.py` and `precision.py` stay the source of truth. This module
turns their questions into DeepEval test cases and metrics so one `deepeval test
run` gives a per-fact pass/fail list with reasons:

- `reference_cases` + `ReferenceFound`: was each reference fact found, and under
  the right code? No model call. `ReferenceFound` asks `score.score` itself about
  one reference fact, so the two can never disagree.
- `same_fact`: for found cases, does the extracted text say what the reference
  says? The counterpart of the `judge.py` prompt; needs a model.
- `fact_cases` + `supported` + `useful`: precision per extracted fact, with the
  cited source text as context. `useful` asks the question `precision.py` asks.

The criteria state general tests that apply to any fact; none is tied to a
particular document.
"""

from __future__ import annotations

import os

from deepeval.metrics import BaseMetric, FaithfulnessMetric, GEval
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, SingleTurnParams

from . import precision
from .compare import Item
from .prompts import DEFINITIONS
from .score import codes_by_id, score

DEFAULT_MODEL = "gpt-6-luna"  # same default as llm.OpenAIClient
NOT_FOUND = "(no extracted fact cites this reference fact's source ID)"


# --- reference cases ---------------------------------------------------------


def _citing(records: list[dict], ids: list[str], q: bool) -> list[dict]:
    """Records of the Q code (q) or any other code that cite one of `ids`."""
    return [
        r for r in records
        if (r["category"] == "Q") == q and any(c["id"] in ids for c in r["citations"])
    ]


def reference_cases(gold: list[Item], records: list[dict]) -> list[LLMTestCase]:
    """One case per reference fact that has IDs, in reference order.

    `actual_output` is the text of the extracted facts citing the reference
    fact's main (first) ID, or NOT_FOUND. A contradiction (code Q) is looked up
    by any of its IDs among the Q facts, as `score.score` does.
    """
    codes = codes_by_id(records)
    cases = []
    for g in gold:
        if not g.ids:
            continue
        main = g.ids[0]
        if g.category == "Q":
            hits = _citing(records, g.ids, q=True)
            filed = ["Q"] if hits else []
        else:
            hits = _citing(records, [main], q=False)
            filed = sorted(codes.get(main, set()))
        cases.append(LLMTestCase(
            input=f"Extract the facts the RFP states in the passage with ID {main}.",
            actual_output="\n".join(r["text"] for r in hits) or NOT_FOUND,
            expected_output=g.text,
            name=f"{g.category} {main}",
            tags=[g.category, main],
            metadata={
                "code": g.category, "alt": list(g.alt), "ids": list(g.ids), "main_id": main,
                "filed_as": filed, "flags": list(g.flags),
            },
        ))
    return cases


class ReferenceFound(BaseMetric):
    """1.0 found under its code or an alternate, 0.5 found under another code, 0.0 missed."""

    _required_params = [SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT]

    def __init__(self, threshold: float = 1.0) -> None:
        self.threshold = threshold
        self.async_mode = False
        self.include_reason = True

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        meta = test_case.metadata or {}
        ref = Item(meta["code"], test_case.expected_output or "", meta["ids"], meta["flags"], meta["alt"])
        # Rebuild one record per code the run filed the ID under, and let score.score judge it.
        records = [{"category": c, "citations": [{"id": ref.ids[0]}]} for c in meta["filed_as"]]
        row = score([ref], records)["by_category"][ref.category]
        if not row["found"]:
            self.score, self.reason = 0.0, f"Missed: no extracted fact cites {meta['main_id']}."
        elif row["same_code"]:
            self.score, self.reason = 1.0, f"Found under {', '.join(meta['filed_as'])} (reference code {ref.category})."
        else:
            alts = f" or {'/'.join(ref.alt)}" if ref.alt else ""
            self.score = 0.5
            self.reason = f"Found under {', '.join(meta['filed_as'])}; the reference code is {ref.category}{alts}."
        self.success = self.is_successful()
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.score is not None and self.score >= self.threshold

    @property
    def __name__(self):
        return "Reference found"


# --- judged: same fact -------------------------------------------------------

SAME_FACT_CRITERIA = (
    "The expected output is a reference fact written by a reviewer; the actual output is the text of "
    "the fact or facts a tool extracted from the same passage. Decide whether a bid manager who reads "
    "only the actual output would know what the reference fact states. The actual output may say more, "
    "word it differently or list several facts together; that is fine. It states the same fact when it "
    "has the same subject and the same obligation, right, deadline or piece of information, and every "
    "date, time, amount, count, duration and party (who must act, who decides) matches. Fail it when "
    "it is about something else, gives a different value for the same point, or leaves out a value "
    "that the reference states."
)


def same_fact(model, threshold: float = 0.5) -> GEval:
    return GEval(
        name="Same fact",
        criteria=SAME_FACT_CRITERIA,
        evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT],
        model=model,
        threshold=threshold,
    )


# --- extracted-fact cases ----------------------------------------------------


def fact_cases(records: list[dict], sample: int | None = None, seed: int = 1) -> list[LLMTestCase]:
    """One case per extracted fact: its text, with the cited source text as context.

    With `sample` set, the same seeded, per-category sample `precision.sample` draws
    for human labelling, so a model grade and a person's label cover the same facts.
    """
    chosen = precision.sample(records, sample, seed) if sample is not None else records
    cases = []
    for r in chosen:
        context = [f"[{c['id']}]" + (f" ({c['section']})" if c.get("section") else "") + f" {c['text']}"
                   for c in r.get("citations", [])]
        cases.append(LLMTestCase(
            input=f"Extract the facts the RFP states that fit this category. {DEFINITIONS[r['category']]}",
            actual_output=r["text"],
            retrieval_context=context or ["(no resolvable citation)"],
            name=f"{r['category']} {r['fact_id']}",
            tags=[r["category"]],
            metadata={"fact_id": r["fact_id"], "category": r["category"], "flags": list(r.get("flags", []))},
        ))
    return cases


def _between(text: str, start: str, end: str) -> str:
    """The part of `text` after `start` and before `end` (precision.SYSTEM keeps its wording in one string)."""
    return text.split(start, 1)[1].split(end, 1)[0].strip()


# The two audience lines and the "useful / noise" definitions, exactly as precision.grade asks them.
USEFUL_CRITERIA = (
    "The actual output is one fact extracted from an RFP for a bid manager. "
    + _between(precision.SYSTEM, "for a bid manager.", "\n\nEach numbered")
    + "\n\nJudge it with the same two labels the project uses: "
    + _between(precision.SYSTEM, "useful:\n", "\n\nReply")
    + "\nPass a fact that is 'useful' and fail one that is 'noise'."
)


def supported(model, threshold: float = 1.0) -> FaithfulnessMetric:
    """Every claim in the fact must be backed by the cited source text."""
    return FaithfulnessMetric(model=model, threshold=threshold, include_reason=True)


def useful(model, threshold: float = 0.5) -> GEval:
    return GEval(
        name="Useful",
        criteria=USEFUL_CRITERIA,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=model,
        threshold=threshold,
    )


# --- model -------------------------------------------------------------------


def judge_model() -> str | DeepEvalBaseLLM:
    """The model for judged metrics: $FACT_EXTRACTOR_MODEL, else the project default.

    DeepEval 4.3.4 lists this default in its OpenAI table (no temperature sent, no
    logprobs, structured outputs on), so the name works as it is. A name it does
    not list would be sent `temperature=0`, which reasoning models reject; give such
    a model a `DeepEvalBaseLLM` of its own."""
    return os.environ.get("FACT_EXTRACTOR_MODEL", DEFAULT_MODEL)

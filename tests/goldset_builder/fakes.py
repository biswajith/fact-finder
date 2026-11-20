"""A scripted brain: the whole graph runs with no API calls.

Behaviour is keyed off the item instruction, so one scripted run exercises every path:
first-try pass, code-check failure then retry, gate-unsure then adjudicator revision,
planner drop, and running out of attempts (needs human).
"""

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any, TypeVar, cast

from langchain_core.messages import HumanMessage
from langchain_openai.decisions import ChoiceAnswer, DecisionResponse, Predicate, PredicateAnswer, Question, Usage
from pydantic import BaseModel

from langchain_core.tools import BaseTool

from goldset.brain import Ledger
from goldset.schemas import (
    Allocation,
    BlindAnswer,
    Candidate,
    ChunkBudget,
    ChunkPlan,
    Evidence,
    PlannedItem,
    ReconcileAction,
    ReconcilePlan,
    TaskPlan,
    Verdict,
)

T = TypeVar("T", bound=BaseModel)

ORDER_OK = '{"order_id": "SO-1001", "status": "shipped", "items": 6, "amount_due": 120.15, "currency": "EUR", "late": true}'


def text_item(a: int, b: int, kind: str, instruction: str) -> PlannedItem:
    return PlannedItem(span_start_line=a, span_end_line=b, span_pointer=None, case_type=kind, instruction=instruction,
                       acceptance=["The answer gives the exact figure from the policy."], aggregate=False)


def E(quote: str | None = None, pointer: str | None = None, value: str | None = None,
      query: str | None = None, result: str | None = None) -> Evidence:
    return Evidence(quote=quote, pointer=pointer, value_json=value, query=query, result_json=result)


def q(text: str, quote: str) -> list[Evidence]:
    return [E(quote, None, None)] if quote else []


class ScriptedBrain:
    def __init__(self) -> None:
        self.ledger = Ledger()
        self.seen: Counter[str] = Counter()  # worker calls per item id
        self.prompts: list[tuple[str, str]] = []
        self.tools: dict[str, BaseTool] = {}
        self.agent_calls: Counter[str] = Counter()

    async def agent(self, stage: str, schema: type[T], system: str, user: str, tools: list[BaseTool], max_tool_calls: int) -> T:
        self.agent_calls[stage] += 1
        self.tools = {t.name: t for t in tools}
        return await self.structured(stage, schema, system, user)

    async def structured(self, stage: str, schema: type[T], system: str, user: str) -> T:
        self.ledger.calls[stage] += 1
        self.prompts.append((stage, user))
        out: BaseModel
        if stage == "plan":
            out = self._plan(user)
        elif stage == "work":
            out = self._work(user)
        elif stage == "solve":
            out = BlindAnswer(answer="independent answer", answerable=True)
        elif stage == "adjudicate":
            out = self._adjudicate(user)
        elif stage == "reconcile":
            out = self._reconcile(user)
        else:
            raise AssertionError(stage)
        assert isinstance(out, schema)
        return cast(T, out)

    def _plan(self, user: str) -> TaskPlan:
        if "order_summary" in user:
            return TaskPlan(mode="reference", mode_rationale="one summary per record", output_format="json", items=[
                PlannedItem(span_start_line=None, span_end_line=None, span_pointer="", case_type="reference_output",
                            instruction="order: summarise the whole record", acceptance=["amount_due is 120.15"], aggregate=False),
            ])
        return TaskPlan(mode="cases", mode_rationale="questions about the policy", output_format="text", items=[
            text_item(12, 13, "lookup", "london: ask the London hotel limit"),
            text_item(18, 19, "lookup", "alcohol: ask whether alcohol is reimbursed"),
            text_item(24, 26, "edge", "lateclaim: ask about a claim sent after 100 days"),
            text_item(5, 8, "multi_hop", "impossible: a case that always fails the gate"),
            text_item(18, 20, "lookup", "dropme: a case the planner gives up on"),
            text_item(400, 410, "lookup", "outside: span outside the source, code must skip it"),
        ])

    def _work(self, user: str) -> Candidate:
        iid = re.search(r"TODO ITEM (T-\d+)", user)
        assert iid
        self.seen[iid[1]] += 1
        n = self.seen[iid[1]]
        if "order:" in user:
            if n == 1:  # wrong value at a real pointer: the code check catches it
                ev = [E(None, "/lines/0/unit_price_minor", "4590")]
                return Candidate(case_input="", expected_output=ORDER_OK, evidence=ev, rationale="r")
            ev = [E(None, "/lines/0/unit_price_minor", "4950"),
                  E(None, "/status", '"SHP"')]
            return Candidate(case_input="", expected_output=ORDER_OK, evidence=ev, rationale="r")
        if "london:" in user:
            return Candidate(case_input="What is the hotel limit in London?", expected_output="260 EUR per night.",
                             evidence=q("", "In London, Paris, New York and Tokyo the limit is 260 EUR per night."), rationale="r")
        if "alcohol:" in user:
            quote = "Alcohol is never reimbursed." if n == 1 else "Alcohol is not reimbursed."  # first quote is invented
            return Candidate(case_input="Can I claim wine with dinner?", expected_output="No. Alcohol is not reimbursed.",
                             evidence=q("", quote), rationale="r")
        if "lateclaim:" in user:
            return Candidate(case_input="I submit a claim 100 days after my trip. Is it paid?",
                             expected_output="UNSURE maybe partly.", evidence=q("", "Claims submitted after 90 days are not reimbursed."), rationale="r")
        if "impossible:" in user:
            return Candidate(case_input=f"Impossible question {n}?", expected_output="BAD answer",
                             evidence=q("", "Business class needs written approval"), rationale="r")
        if "dropme:" in user:
            return Candidate(case_input="Is a client dinner covered?", expected_output="BAD guess",
                             evidence=q("", "Client dinners are exempt"), rationale="r")
        raise AssertionError(user[:200])

    def _adjudicate(self, user: str) -> Verdict:
        fixed = Candidate(case_input="I submit a claim 100 days after my trip. Is it paid?",
                          expected_output="No. Claims submitted after 90 days are not reimbursed.",
                          evidence=q("", "Claims submitted after 90 days are not reimbursed."), rationale="fixed")
        return Verdict(decision="revise", reasons=["output hedged; policy is clear"], fix_instructions="", corrected=fixed)

    def _reconcile(self, user: str) -> ReconcilePlan:
        failed = user.split("FAILED ITEMS:", 1)[1]
        actions = []
        for block in re.split(r"\n(?=TODO ITEM )", failed):
            m = re.search(r"TODO ITEM (T-\d+)", block)
            if not m:
                continue
            action = "drop" if "dropme:" in block else "retry"
            actions.append(ReconcileAction(item_id=m[1], action=action, feedback="use the exact policy wording",
                                           replacement=None, split_into=[]))
        return ReconcilePlan(actions=actions, new_items=[], notes="")

    async def decide(self, stage: str, shared: Sequence[HumanMessage], questions: dict[str, Question]) -> DecisionResponse:
        self.ledger.calls[stage] += 1
        answers: dict[str, Any] = {}
        for name, qq in questions.items():
            text = qq.instructions
            if isinstance(qq, Predicate):
                p = 0.1 if "BAD" in text else 0.6 if ("UNSURE" in text and name.endswith("_grounded")) else 0.95
                answers[name] = PredicateAnswer(type="predicate", probability=p)
            else:
                answers[name] = ChoiceAnswer(type="choice", choice="equivalent",
                                             probabilities={"equivalent": 0.9, "minor_difference": 0.05, "conflict": 0.05}, confidence=0.9)
        return DecisionResponse(model="gpt-6-luna", answers=answers, usage=Usage(input_tokens=100 * len(questions)))


# --- large JSON: two-level planning, coverage-driven additions, sweep -------------------------


def _record_of(ptr: str) -> str:
    m = re.match(r"^(/[^/]+/\d+)", ptr)
    return m[1] if m else "/" + ptr.strip("/").split("/")[0]


def _uncovered(user: str, header: str) -> list[str]:
    block = user.split(header, 1)[1] if header in user else ""
    return re.findall(r"^- \[C\d+\] .*?; e\.g\. at (\S+)$", block, flags=re.M)


AGGREGATES = ["length(orders[?status=='CAN'])", "sum(orders[?currency=='GBP'].shipping_minor)"]


class LargeScriptedBrain(ScriptedBrain):
    """Plans one case per chunk, then adds cases for uncovered units; the sweep flags one case once."""

    def __init__(self, sweep_flags: bool = True) -> None:
        super().__init__()
        self.sweep_flags = sweep_flags
        self.flagged_once = False

    async def structured(self, stage: str, schema: type[T], system: str, user: str) -> T:
        self.prompts.append((stage, user))
        self.ledger.calls[stage] += 1
        out: BaseModel
        if stage == "allocate":
            ids = re.findall(r"^(C\d+)  ", user.split("CHUNKS\n", 1)[1], flags=re.M)
            out = Allocation(mode="cases", mode_rationale="lookups", output_format="text",
                             budgets=[ChunkBudget(chunk_id=c, cases=1, focus="rare values first") for c in ids] +
                                     [ChunkBudget(chunk_id="C99", cases=3, focus="no such chunk")],
                             aggregates=[PlannedItem(span_start_line=None, span_end_line=None, span_pointer="/orders", case_type="aggregate",
                                                     instruction=f"query: {qq}", acceptance=["gives the exact number"], aggregate=False)
                                         for qq in AGGREGATES])  # code sets aggregate=True for these
        elif stage == "plan_chunk":
            todo = _uncovered(user, "UNCOVERED UNITS IN THIS CHUNK")
            first = re.search(r"^(/\S+) = ", user, flags=re.M)
            assert first
            target = todo[0] if todo else first[1]
            good = PlannedItem(span_start_line=None, span_end_line=None, span_pointer=_record_of(target), case_type="lookup",
                               instruction=f"cover {target}", acceptance=["quotes the order number"], aggregate=False)
            too_big = good.model_copy(update={"span_pointer": "", "instruction": "whole document"})
            out = ChunkPlan(items=[too_big, good])  # code must skip the first and keep the second
        elif stage == "work":
            out = self._work_large(user)
        elif stage == "reconcile":
            room = int(re.search(r"You may add at most (\d+) new item", user)[1])  # type: ignore[index]
            new = [PlannedItem(span_start_line=None, span_end_line=None, span_pointer=_record_of(p), case_type="edge",
                               instruction=f"cover {p}", acceptance=["quotes the order number"], aggregate=False)
                   for p in _uncovered(user, "UNCOVERED UNITS")[:room]]
            out = ReconcilePlan(actions=[], new_items=new, notes="")
        elif stage == "adjudicate":
            assert "PASSAGES FROM ELSEWHERE IN THE SOURCE" in user
            out = Verdict(decision="accept", reasons=["the flagged passage is a different order"], fix_instructions="", corrected=None)
        else:
            self.prompts.pop()
            self.ledger.calls[stage] -= 1
            return await super().structured(stage, schema, system, user)
        assert isinstance(out, schema)
        return cast(T, out)

    def _work_large(self, user: str) -> Candidate:
        agg = re.search(r"^instruction: query: (.+)$", user, flags=re.M)
        if agg:
            assert "an aggregate case over /orders" in user and "query_json" in self.tools
            expr = agg[1].strip()
            result = self.tools["query_json"].invoke({"expression": expr})
            cited = result if "FEEDBACK FROM EARLIER ATTEMPTS" in user else "5"  # first try: "counted by reading"
            return Candidate(case_input=f"Across all orders: {expr}?", expected_output=f"The answer is {cited}.",
                             evidence=[E(query=expr, result=cited)], rationale="computed with query_json")
        target = re.search(r"instruction: cover (\S+)", user)
        assert target, user[:300]
        leaf = dict(re.findall(r"^(/\S+) = (.*)$", user, flags=re.M))
        rec = _record_of(target[1])
        ev = [E(None, target[1], leaf.get(target[1]))]
        for extra in (f"{rec}/order_id", f"{rec}/status"):
            if extra in leaf and extra != target[1]:
                ev.append(E(None, extra, leaf[extra]))
        oid = leaf.get(f"{rec}/order_id", '"the export"').strip('"')
        return Candidate(case_input=f"What does {target[1]} say for {oid}?", expected_output=f"For {oid}: {leaf.get(target[1], 'see record')}.",
                         evidence=ev, rationale="r")

    async def decide(self, stage: str, shared: Sequence[HumanMessage], questions: dict[str, Question]) -> DecisionResponse:
        if stage != "sweep":
            return await super().decide(stage, shared, questions)
        self.ledger.calls[stage] += 1
        answers: dict[str, Any] = {name: PredicateAnswer(type="predicate", probability=0.05) for name in questions}
        if self.sweep_flags and not self.flagged_once and "CHUNK C02:" in str(shared[0].content):
            answers[next(iter(questions))] = PredicateAnswer(type="predicate", probability=0.8)
            self.flagged_once = True
        return DecisionResponse(model="gpt-6-luna", answers=answers, usage=Usage(input_tokens=50 * len(questions)))

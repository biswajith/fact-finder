"""Every record that crosses a boundary: model outputs, the todo list, verdicts, golden records.

Models the LLM fills (marked "model-facing") use only required fields, plain types and
`X | None`, so they work with OpenAI strict structured output.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

# --- inputs -----------------------------------------------------------------


class Source(BaseModel):
    id: str  # path relative to the sources dir, e.g. "orders/o-17.json"
    kind: Literal["text", "json"]
    text: str  # raw file text
    data: Any = None  # parsed JSON, for kind == "json"
    glossary: str | None = None  # markdown that explains the JSON keys
    glossary_id: str | None = None


class PromptSpec(BaseModel):
    id: str  # file stem
    text: str
    applies_to: list[str] = ["*"]  # globs over Source.id
    output_format: Literal["text", "json"] | None = None  # None: the planner decides
    cases: int | None = None  # overrides dataset.cases_per_task


class Task(BaseModel):
    """One (prompt, source) pair. The planner plans and reconciles per task."""

    id: str  # "<prompt_id>@<source_id>"
    prompt_id: str
    source_id: str
    mode: Literal["reference", "cases"] = "cases"
    output_format: Literal["text", "json"] = "text"
    rationale: str = ""


class Span(BaseModel):
    start_line: int | None = None  # 1-based, inclusive (text sources)
    end_line: int | None = None
    pointer: str | None = None  # RFC 6901 JSON pointer, "" = whole document (json sources)

    def key(self) -> str:
        return f"ptr:{self.pointer}" if self.pointer is not None else f"L{self.start_line}-{self.end_line}"


class Chunk(BaseModel):
    """A piece of a source, cut along its structure. Text: a line range. JSON: one or more subtrees."""

    id: str  # "C01"
    title: str
    start_line: int | None = None
    end_line: int | None = None
    pointers: list[str] = []
    size: int  # leaves (JSON) or characters (text)


class Unit(BaseModel):
    """One thing a comprehensive dataset must test at least once. Code derives units and decides coverage."""

    id: str  # e.g. 'value:/orders/*/status="CAN"'
    kind: Literal["chunk", "path", "value", "null", "missing"]
    pattern: str = ""  # JSON path pattern, for path/value/null/missing
    value: str | None = None  # JSON-encoded, for value units
    example: str  # a pointer (or "L12-40") where the planner can find it
    chunk_id: str  # the chunk that holds the example
    rarity: float = 1.0  # share of occurrences; lower = rarer edge case, listed first


# --- planner (model-facing) -------------------------------------------------


class PlannedItem(BaseModel):
    """One todo item as the planner writes it. Code assigns the id and status."""

    span_start_line: int | None = Field(description="Text sources: first line of the span (1-based). Null for JSON.")
    span_end_line: int | None = Field(description="Text sources: last line of the span, inclusive. Null for JSON.")
    span_pointer: str | None = Field(description='JSON sources: JSON pointer of the subtree, "" for the whole document. Null for text.')
    case_type: str = Field(description="Short kind of case, e.g. lookup, aggregation, multi_hop, edge_null, unanswerable, reference_output.")
    instruction: str = Field(description="What the worker must create for this case, specific enough that two workers would make the same case.")
    acceptance: list[str] = Field(description="1-5 observable criteria, one concern each, checkable from the source and the case alone.")
    aggregate: bool = Field(description="True for counts, sums, averages, filters or group-bys across many records. The worker computes "
                                        "them with a query tool, so the span may be the whole collection (e.g. /orders).")

    def span(self) -> Span:
        return Span(start_line=self.span_start_line, end_line=self.span_end_line, pointer=self.span_pointer)


class TaskPlan(BaseModel):
    mode: Literal["reference", "cases"] = Field(
        description="reference: the prompt maps the whole source to one output. cases: the prompt answers inputs about the source."
    )
    mode_rationale: str
    output_format: Literal["text", "json"] = Field(description="Format the TASK PROMPT requires for its output.")
    items: list[PlannedItem]


class ChunkBudget(BaseModel):
    chunk_id: str
    cases: int = Field(description="Cases to plan in this chunk (0 is allowed).")
    focus: str = Field(description="What the cases in this chunk should test, in one sentence.")


class Allocation(BaseModel):
    """First level of planning for a source too big to plan in one call."""

    mode: Literal["reference", "cases"] = Field(
        description="reference: the prompt maps the whole source to one output. cases: the prompt answers inputs about the source."
    )
    mode_rationale: str
    output_format: Literal["text", "json"] = Field(description="Format the TASK PROMPT requires for its output.")
    budgets: list[ChunkBudget] = Field(description="How the case budget is spread over the chunks.")
    aggregates: list[PlannedItem] = Field(description="Cases that count, sum, filter or group across many records (aggregate=true), "
                                                      "planned from the profile. Workers compute them with a query tool.")


class ChunkPlan(BaseModel):
    """Second level: the todo items for one chunk."""

    items: list[PlannedItem]


class ReconcileAction(BaseModel):
    item_id: str
    action: Literal["retry", "rewrite", "split", "drop"] = Field(
        description="retry: same spec plus feedback. rewrite: replace the spec. split: replace with smaller items. drop: the source cannot support it."
    )
    feedback: str = Field(description="For retry: concrete fix instructions for the worker. For drop: the reason.")
    replacement: PlannedItem | None = Field(description="For rewrite only, else null.")
    split_into: list[PlannedItem] = Field(description="For split only, else empty.")


class ReconcilePlan(BaseModel):
    actions: list[ReconcileAction] = Field(description="Exactly one action per failed item.")
    new_items: list[PlannedItem] = Field(description="Extra items for coverage gaps; empty if coverage is fine.")
    notes: str


# --- workers (model-facing) -------------------------------------------------


class Evidence(BaseModel):
    quote: str | None = Field(description="Text sources: a short passage copied verbatim from the source, without line numbers.")
    pointer: str | None = Field(description="JSON sources: JSON pointer of a leaf value, e.g. /orders/0/total.")
    value_json: str | None = Field(description='JSON sources: the value at that pointer, JSON-encoded, e.g. 42, "paid", null.')
    query: str | None = Field(description="JSON sources: a query_json expression you ran, for a computed fact (count, sum, filter).")
    result_json: str | None = Field(description="The query's result exactly as the tool returned it.")


class Candidate(BaseModel):
    case_input: str = Field(description='The input this case gives the TASK PROMPT. Empty string in reference mode.')
    expected_output: str = Field(description="The ideal response, exactly in the format the TASK PROMPT requires.")
    evidence: list[Evidence] = Field(description="Support for every factual claim in expected_output.")
    rationale: str = Field(description="One or two sentences on why this output is correct.")


class BlindAnswer(BaseModel):
    answer: str
    answerable: bool = Field(description="False if the source does not contain what the case asks for.")


class Verdict(BaseModel):
    decision: Literal["accept", "revise", "reject"] = Field(
        description="accept: the candidate is correct as is. revise: fixable, give the corrected candidate. reject: the item cannot be made right as specified."
    )
    reasons: list[str]
    fix_instructions: str = Field(description="For reject: what the planner should change. Else empty.")
    corrected: Candidate | None = Field(description="For revise only: the full corrected candidate. Else null.")


# --- verification and state -------------------------------------------------


class GateResult(BaseModel):
    scores: dict[str, float]  # predicate name -> probability
    agreement: str | None = None  # equivalent | minor_difference | conflict
    agreement_confidence: float = 0.0
    refusals: list[str] = []
    outcome: Literal["pass", "fail", "unsure"]
    failing: list[str] = []  # human-readable reasons
    sweep: dict[str, float] = {}  # chunk id -> probability it contradicts or changes the case (flagged chunks only)


class Attempt(BaseModel):
    round: int
    by: Literal["worker", "adjudicator"]
    candidate: Candidate
    check_errors: list[str] = []
    gate: GateResult | None = None
    verdict: Verdict | None = None
    outcome: Literal["accepted", "failed", "revised"] | None = None


ItemStatus = Literal["pending", "verify", "accepted", "failed", "dropped", "needs_human"]


class Item(BaseModel):
    id: str  # "T-003"
    task_id: str
    span: Span
    case_type: str
    instruction: str
    acceptance: list[str]
    status: ItemStatus = "pending"
    attempts: int = 0
    feedback: list[str] = []
    parent: str | None = None
    chunk_id: str | None = None
    aggregate: bool = False  # computed across many records with the query tool
    note: str | None = None  # drop reason or why a human must look
    candidate: Candidate | None = None
    blind: BlindAnswer | None = None
    blind_for: str | None = None  # case_input the blind answer was made for
    history: list[Attempt] = []


class GoldenRecord(BaseModel):
    id: str
    prompt_id: str
    source_id: str
    mode: Literal["reference", "cases"]
    case_type: str
    case_input: str
    expected_output: str
    evidence: list[Evidence]
    span: Span
    provenance: dict[str, Any]

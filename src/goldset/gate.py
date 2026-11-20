"""The Decisions API gate: turn candidates into predicate/choice questions, and answers into an outcome.

One request per (task, span) group. The shared input is the source span plus the task prompt,
identical across rounds, so the Decisions prompt cache can reuse it. Each candidate's own text
goes into its questions' instructions.
"""

import json

from langchain_core.messages import HumanMessage
from langchain_openai.decisions import Choice, DecisionResponse, Predicate, Question

from .config import GateCfg
from .schemas import GateResult, Item, PromptSpec, Source, Task

AGREEMENT: dict[str | bool, str | None] = {
    "equivalent": "Same facts and same conclusion; wording or format may differ.",
    "minor_difference": "Same conclusion and key facts; one adds or omits a non-essential detail.",
    "conflict": "They disagree on a fact, number or conclusion, or one says the source cannot answer and the other answers.",
}


def shared_input(source_view: str, prompt: PromptSpec) -> list[HumanMessage]:
    return [HumanMessage(source_view), HumanMessage(f"TASK PROMPT ({prompt.id})\n{prompt.text}")]


def candidate_block(item: Item, task: Task) -> str:
    c = item.candidate
    assert c is not None
    case = "(reference mode: the whole source is the input)" if task.mode == "reference" else c.case_input
    block = f"CANDIDATE {item.id} (case type: {item.case_type})\nCASE INPUT:\n{case}\nEXPECTED OUTPUT:\n{c.expected_output}"
    computed = [e for e in c.evidence if e.query]
    if computed:
        block += "\nCOMPUTED BY CODE OVER THE WHOLE SOURCE (each result re-run and verified):\n" + "\n".join(
            f"- {e.query}  =>  {e.result_json}" for e in computed)
    return block


def questions_for(item: Item, task: Task, source: Source, novelty: list[str]) -> dict[str, Question]:
    """Question keys are local ('grounded', 'criterion_1', ...); the caller prefixes them per item."""
    b = candidate_block(item, task)
    q: dict[str, Question] = {
        "grounded": Predicate(instructions=(
            f"{b}\n\nIs every factual claim in the EXPECTED OUTPUT directly supported by the SOURCE or by the facts COMPUTED BY "
            "CODE, with nothing invented, altered or taken from outside them? For an 'unanswerable' case: true only if the "
            "source really lacks the information and the output says so."
        )),
        "correct": Predicate(instructions=(
            f"{b}\n\nDoes the EXPECTED OUTPUT correctly and completely give what the TASK PROMPT asks for, for this case input "
            "(or, in reference mode, for this source)?"
        )),
        "format": Predicate(instructions=(
            f"{b}\n\nDoes the EXPECTED OUTPUT follow every format, length, style and content rule stated in the TASK PROMPT?"
        )),
    }
    if item.candidate is not None and any(e.query for e in item.candidate.evidence):
        q["query_fits"] = Predicate(instructions=(
            f"{b}\n\nDo the COMPUTED queries select exactly what the CASE INPUT asks about (the right records, filters, fields "
            "and codes, read as the FIELD GLOSSARY defines them), and does the EXPECTED OUTPUT report their results correctly, "
            "including unit conversions?"
        ))
    if source.kind == "json" and source.glossary:
        q["glossary"] = Predicate(instructions=(
            f"{b}\n\nDoes the EXPECTED OUTPUT interpret every field it relies on as the FIELD GLOSSARY defines it "
            "(meaning, units, enum values, null or missing handling)?"
        ))
    if task.mode == "cases":
        q["clear"] = Predicate(instructions=(
            f"{b}\n\nIs the CASE INPUT a clear, realistic, self-contained input with one defensible answer from the SOURCE?"
        ))
    for i, crit in enumerate(item.acceptance, 1):
        q[f"criterion_{i}"] = Predicate(instructions=f"{b}\n\nAcceptance criterion: {crit}\nIs this criterion met?")
    if novelty:
        listed = "\n".join(f"- {x}" for x in novelty)
        q["novel"] = Predicate(instructions=(
            f"{b}\n\nExisting cases:\n{listed}\n\nDoes the CASE INPUT ask for different information, or test a different "
            "behaviour, than every existing case?"
        ))
    if item.blind is not None:
        q["agreement"] = Choice(
            instructions=(
                f"{b}\n\nINDEPENDENT ANSWER (written by a separate solver that did not see the expected output; "
                f"it judged the case {'answerable' if item.blind.answerable else 'not answerable'} from the source):\n"
                f"{item.blind.answer}\n\nCompare the EXPECTED OUTPUT with the INDEPENDENT ANSWER on facts and conclusions only."
            ),
            choices=dict(AGREEMENT),
        )
    return q


def sweep_question(item: Item, task: Task) -> Predicate:
    """Asked with ANOTHER chunk of the source as the shared input: does that part change this case?"""
    b = candidate_block(item, task)
    if item.case_type == "unanswerable":
        return Predicate(instructions=f"{b}\n\nThis case claims the source does not contain what the CASE INPUT asks for. "
                                      "Does THIS part of the source contain that information?")
    return Predicate(instructions=(
        f"{b}\n\nThe case was written from another part of the source. Does THIS part of the source contain information "
        "that contradicts the EXPECTED OUTPUT, or that the EXPECTED OUTPUT would need to be correct and complete for this "
        "CASE INPUT (for example another record about the same order, customer or item)?"
    ))


def triage(answers: DecisionResponse, prefix: str, cfg: GateCfg) -> GateResult:
    """Pure: answers for one candidate -> pass / fail / unsure.

    fail: a predicate is clearly false (below `reject`). The worker retries with the reasons.
    unsure: a predicate is in the middle band, the agreement check says conflict, or the model
    refused. A reasoning model adjudicates. pass: everything clearly true and the answers agree.
    """
    mine = {k[len(prefix):]: v for k, v in answers.answers.items() if k.startswith(prefix)}
    scores = {k: v.probability for k, v in mine.items() if v.type == "predicate"}
    refusals = [k for k, v in mine.items() if v.type == "refusal"]
    agree = next((v for k, v in mine.items() if k == "agreement" and v.type == "choice"), None)

    failing = [f"{k}: p={p:.2f}" for k, p in scores.items() if p < cfg.reject]
    weak = [f"{k}: p={p:.2f}" for k, p in scores.items() if cfg.reject <= p < cfg.accept]
    agreement = str(agree.choice) if agree else None
    confidence = agree.confidence if agree else 1.0
    if agreement == "conflict":
        weak.append(f"agreement: conflict with the independent answer (confidence {confidence:.2f})")
    elif agree is not None and confidence < cfg.agree_confidence:
        weak.append(f"agreement: {agreement} but low confidence ({confidence:.2f})")
    weak += [f"{k}: refused" for k in refusals]

    outcome = "fail" if failing else "unsure" if weak else "pass"
    return GateResult(
        scores=scores, agreement=agreement, agreement_confidence=confidence if agree else 0.0,
        refusals=refusals, outcome=outcome, failing=failing + weak,
    )


def describe(result: GateResult) -> str:
    return json.dumps({"outcome": result.outcome, "failing": result.failing, "agreement": result.agreement})

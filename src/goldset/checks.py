"""Code checks that run before any model judges a candidate. They are cheap and never wrong
about what they check: quotes must be in the source, pointers must resolve to the cited value."""

import json
import re
import unicodedata

from .schemas import Candidate, Item, Source, Task
from .query import QueryError, run_query, same_result
from .sources import resolve_pointer

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def normalize(text: str) -> str:
    """Compare text the way a reader would: same characters, any whitespace, straight quotes."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).translate(_QUOTES)).strip()


def _same_value(cited: str, actual: object) -> bool:
    try:
        return json.loads(cited) == actual
    except ValueError:
        return cited.strip() == str(actual)  # model wrote a bare string without quotes


def check_candidate(cand: Candidate, item: Item, task: Task, source: Source, accepted_inputs: list[str]) -> list[str]:
    errors: list[str] = []
    if not cand.expected_output.strip():
        errors.append("expected_output is empty")
    if task.mode == "cases" and not cand.case_input.strip():
        errors.append("case_input is empty but the task is in cases mode")
    if task.output_format == "json":
        try:
            json.loads(cand.expected_output)
        except json.JSONDecodeError as e:
            errors.append(f"expected_output is not valid JSON ({e.msg} at char {e.pos})")
    if not cand.evidence and item.case_type != "unanswerable":
        errors.append("no evidence given")

    haystack = normalize(source.text) if source.kind == "text" else ""
    for i, ev in enumerate(cand.evidence, 1):
        if source.kind == "text":
            if not ev.quote or not ev.quote.strip():
                errors.append(f"evidence {i}: quote missing: text sources need a quote")
            elif normalize(ev.quote) not in haystack:
                errors.append(f"evidence {i}: quote not verbatim: {ev.quote[:120]!r} is not in the source")
        elif ev.query is not None:  # a computed fact: re-run it, the cited result must be exactly what the data gives
            try:
                actual = run_query(source.data, ev.query)
            except QueryError as e:
                errors.append(f"evidence {i}: query failed: {ev.query!r}: {e}")
                continue
            try:
                cited = json.loads(ev.result_json or "")
            except ValueError:
                errors.append(f"evidence {i}: query result missing: cite the tool's JSON result for {ev.query!r}")
                continue
            if not same_result(cited, actual):
                errors.append(f"evidence {i}: query result mismatch: {ev.query!r} gives {json.dumps(actual)[:200]}, not {ev.result_json}")
        else:
            if ev.pointer is None:
                errors.append(f"evidence {i}: pointer missing: JSON sources need a pointer or a query")
                continue
            try:
                actual = resolve_pointer(source.data, ev.pointer)
            except KeyError:
                errors.append(f"evidence {i}: pointer not found: {ev.pointer!r} does not exist")
                continue
            if ev.value_json is not None and not _same_value(ev.value_json, actual):
                errors.append(f"evidence {i}: value mismatch: {ev.pointer} is {json.dumps(actual)}, not {ev.value_json}")

    if item.aggregate and source.kind == "json" and not any(ev.query for ev in cand.evidence):
        errors.append("computed evidence missing: an aggregate case must cite the query_json query and result behind each number")

    if task.mode == "cases" and normalize(cand.case_input).lower() in {normalize(x).lower() for x in accepted_inputs}:
        errors.append("case_input duplicates an accepted case")
    return errors

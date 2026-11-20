"""Aggregates computed by code: a JMESPath query engine over a JSON source, and the LangChain tool workers call.

Counts, sums and filters across thousands of records are where a model reading text goes wrong, so
models never compute them. A worker writes a query, the tool runs it, and the worker cites the query
and its result as evidence. `checks.py` re-runs every cited query, so a golden aggregate is exactly
what the data says. JMESPath is declarative and side-effect free: a query can read the document and
nothing else.

Added functions (JMESPath has length, sum, avg, min, max, sort_by, max_by, min_by, contains, keys...):
  count_by(array, &key)          {key: count}
  sum_by(array, &key, &value)    {key: sum of value}
  unique(array)                  distinct values, in first-seen order
  mul(a, b) div(a, b) add(a, b) sub(a, b) round(n, digits)
  before(a, b) after(a, b)       ISO-8601 dates/times compared (JMESPath's < > only take numbers)
"""

import json
from datetime import datetime, timezone
from typing import Any

import jmespath
from jmespath import exceptions, functions
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

MAX_EXPR = 600


def _key(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v)


class _Functions(functions.Functions):
    @functions.signature({"types": ["array"]}, {"types": ["expref"]})
    def _func_count_by(self, array, expref):  # noqa: ANN001, ANN202 - jmespath's calling convention
        out: dict[str, int] = {}
        for x in array:
            k = _key(expref.visit(expref.expression, x))
            out[k] = out.get(k, 0) + 1
        return out

    @functions.signature({"types": ["array"]}, {"types": ["expref"]}, {"types": ["expref"]})
    def _func_sum_by(self, array, key_ref, value_ref):  # noqa: ANN001, ANN202
        out: dict[str, float] = {}
        for x in array:
            k, v = _key(key_ref.visit(key_ref.expression, x)), value_ref.visit(value_ref.expression, x)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise exceptions.JMESPathTypeError("sum_by", v, type(v).__name__, ["number"])
            out[k] = out.get(k, 0) + v
        return out

    @functions.signature({"types": ["array"]})
    def _func_unique(self, array):  # noqa: ANN001, ANN202
        seen: list[Any] = []
        for x in array:
            if x not in seen:
                seen.append(x)
        return seen

    @functions.signature({"types": ["number"]}, {"types": ["number"]})
    def _func_mul(self, a, b):  # noqa: ANN001, ANN202
        return a * b

    @functions.signature({"types": ["number"]}, {"types": ["number"]})
    def _func_div(self, a, b):  # noqa: ANN001, ANN202
        if b == 0:
            raise exceptions.JMESPathError("div: division by zero")
        return a / b

    @functions.signature({"types": ["number"]}, {"types": ["number"]})
    def _func_add(self, a, b):  # noqa: ANN001, ANN202
        return a + b

    @functions.signature({"types": ["number"]}, {"types": ["number"]})
    def _func_sub(self, a, b):  # noqa: ANN001, ANN202
        return a - b

    @functions.signature({"types": ["number"]}, {"types": ["number"]})
    def _func_round(self, n, digits):  # noqa: ANN001, ANN202
        return round(n, int(digits))


    @functions.signature({"types": ["string"]}, {"types": ["string"]})
    def _func_before(self, a, b):  # noqa: ANN001, ANN202
        return _iso(a) < _iso(b)

    @functions.signature({"types": ["string"]}, {"types": ["string"]})
    def _func_after(self, a, b):  # noqa: ANN001, ANN202
        return _iso(a) > _iso(b)


def _iso(s: str) -> datetime:
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise exceptions.JMESPathError(f"not an ISO-8601 date: {s!r}") from e
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


_OPTIONS = jmespath.Options(custom_functions=_Functions())


class QueryError(ValueError):
    pass


def run_query(data: Any, expression: str) -> Any:
    if len(expression) > MAX_EXPR:
        raise QueryError(f"expression longer than {MAX_EXPR} characters")
    try:
        return jmespath.search(expression, data, options=_OPTIONS)
    except exceptions.JMESPathError as e:
        raise QueryError(str(e).replace("\n", " ")) from e


def same_result(a: Any, b: Any) -> bool:
    """Equal as JSON, with numbers compared to 1e-9 (sums of floats)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_result(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same_result(a[k], b[k]) for k in a)
    return a == b


TOOL_DOC = """Run a JMESPath query over the WHOLE JSON source and get the result as JSON.
Use it for anything across many records: counts, sums, averages, min/max, filters, group-bys, and to find records.
The root is the whole document. String literals use single quotes; numbers in comparisons use backticks.
Extra functions: count_by(array, &key), sum_by(array, &key, &value), unique(array), mul(a,b), div(a,b), add(a,b), sub(a,b),
round(n,digits), before(a,b), after(a,b) (ISO-8601 dates and times; < and > only compare numbers).
Examples:
  length(orders[?status=='CAN'])
  count_by(orders, &status)
  sum(orders[?currency=='GBP'].shipping_minor)
  orders[?customer.id=='C-77'].order_id
  sum(orders[?order_id=='SO-2040'] | [0].lines[].mul(qty, unit_price_minor))
  length(orders[?delivered_at==null && status=='DLV'])
  length(orders[?delivered_at==null && before(promised_by, '2026-10-26')])"""


class _Args(BaseModel):
    expression: str = Field(description="A JMESPath expression.")


def query_tool(data: Any, max_chars: int) -> BaseTool:
    def run(expression: str) -> str:
        try:
            out = json.dumps(run_query(data, expression), ensure_ascii=False)
        except QueryError as e:
            return f"error: {e}"
        if len(out) > max_chars:
            return out[:max_chars] + f" ... (truncated: {len(out)} characters; narrow the query or aggregate it)"
        return out

    return StructuredTool.from_function(func=run, name="query_json", description=TOOL_DOC, args_schema=_Args)

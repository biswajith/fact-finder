"""A schema-level profile of a JSON document, computed by code.

Large JSON is too big to show a model, but its *shape* is small: a few hundred path patterns
(`/orders/*/status`) with types, counts, value distributions, nulls and missing keys. The planner
plans from this profile; coverage units are derived from it.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

_INDEX = re.compile(r"/\d+(?=/|$)")


def pattern(pointer: str) -> str:
    """/orders/17/lines/0/qty -> /orders/*/lines/*/qty"""
    return _INDEX.sub("/*", pointer)


def within(pointer: str, root: str) -> bool:
    """True if `pointer` is `root` or inside it ("" contains everything)."""
    return root == "" or pointer == root or pointer.startswith(root + "/")


def _type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


@dataclass
class PathStat:
    pattern: str
    count: int = 0
    nulls: int = 0
    types: Counter[str] = field(default_factory=Counter)
    values: Counter[str] = field(default_factory=Counter)  # JSON-encoded scalar -> count, while few distinct
    many_values: bool = False  # more distinct values than enum_max: not an enum
    value_example: dict[str, str] = field(default_factory=dict)  # JSON value -> first pointer holding it
    example: str = ""
    null_example: str = ""
    num_min: float | None = None
    num_max: float | None = None
    num_examples: dict[str, str] = field(default_factory=dict)  # "min" / "max" / "zero" -> pointer
    len_min: int | None = None  # arrays
    len_max: int | None = None
    missing: int = 0  # objects at the parent pattern that lack this key
    parents: int = 0  # objects at the parent pattern
    missing_example: str = ""  # pointer of an object that lacks the key

    @property
    def numeric(self) -> bool:
        return self.num_min is not None

    @property
    def is_enum(self) -> bool:
        """A field with a few distinct non-numeric values; numbers get boundary units instead."""
        return not self.many_values and len(self.values) >= 2 and not self.numeric


def profile(data: Any, enum_max: int = 12) -> dict[str, PathStat]:
    stats: dict[str, PathStat] = {}

    def stat(pat: str) -> PathStat:
        if pat not in stats:
            stats[pat] = PathStat(pattern=pat)
        return stats[pat]

    def walk(node: Any, ptr: str) -> None:
        s = stat(pattern(ptr) or "(root)")
        s.count += 1
        s.types[_type(node)] += 1
        s.example = s.example or ptr
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{ptr}/{k.replace('~', '~0').replace('/', '~1')}")
            return
        if isinstance(node, list):
            s.len_min = len(node) if s.len_min is None else min(s.len_min, len(node))
            s.len_max = len(node) if s.len_max is None else max(s.len_max, len(node))
            objs = [(i, x) for i, x in enumerate(node) if isinstance(x, dict)]
            if objs:  # keys some elements have and others lack
                keys = set().union(*(x.keys() for _, x in objs))
                for k in keys:
                    ks = stat(pattern(f"{ptr}/0/{k.replace('~', '~0').replace('/', '~1')}"))
                    ks.parents += len(objs)
                    for i, x in objs:
                        if k not in x:
                            ks.missing += 1
                            ks.missing_example = ks.missing_example or f"{ptr}/{i}"
            for i, v in enumerate(node):
                walk(v, f"{ptr}/{i}")
            return
        if node is None:
            s.nulls += 1
            s.null_example = s.null_example or ptr
            return
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            if s.num_min is None or node < s.num_min:
                s.num_min, s.num_examples["min"] = node, ptr
            if s.num_max is None or node > s.num_max:
                s.num_max, s.num_examples["max"] = node, ptr
            if node == 0:
                s.num_examples.setdefault("zero", ptr)
        enc = json.dumps(node, ensure_ascii=False)
        if not s.many_values:
            if enc not in s.values and len(s.values) >= enum_max:
                s.many_values = True
                s.values.clear()
                s.value_example.clear()
            else:
                s.values[enc] += 1
                s.value_example.setdefault(enc, ptr)

    walk(data, "")
    stats.pop("(root)", None)  # the document itself is not a field
    return stats


def _fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def render_profile(stats: dict[str, PathStat], max_lines: int = 400) -> str:
    lines = []
    for pat in sorted(stats):
        s = stats[pat]
        kinds = "|".join(t for t, _ in s.types.most_common())
        parts = [f"{pat}  {kinds}  {s.count}x"]
        if s.len_min is not None:
            parts.append(f"len {s.len_min}..{s.len_max}")
        if s.nulls:
            parts.append(f"null {s.nulls}")
        if s.missing:
            parts.append(f"missing in {s.missing} of {s.parents}")
        if not s.many_values and len(s.values) >= 2:
            parts.append("values: " + ", ".join(f"{v} {n}" for v, n in s.values.most_common()))
        if s.num_min is not None:
            parts.append(f"{_fmt_num(s.num_min)}..{_fmt_num(s.num_max or 0)}")
        elif s.many_values:
            parts.append(f"many distinct, e.g. at {s.example}")
        elif len(s.values) == 1:
            parts.append(f"always {next(iter(s.values))}")
        lines.append("  ".join(parts))
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... {len(lines) - max_lines} more paths"]
    return "\n".join(lines)

"""Coverage as a number code computes, not an opinion the planner gives.

Units (what a comprehensive golden set must test at least once):
  chunk    every chunk of the source
  path     every JSON field pattern, e.g. /orders/*/status
  value    every value of an enum-like field, e.g. /orders/*/status = "CAN"
  null     a field that is null somewhere
  missing  a key that some objects lack

An accepted case covers a unit through its evidence: the pointers it cites (their pattern and value),
the objects it cites that lack a key, and the chunks its span and evidence fall in.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass

from pydantic import BaseModel

from .checks import normalize
from .chunks import chunk_of, chunk_source
from .config import Config
from .profile import PathStat, pattern, profile
from .schemas import Chunk, Evidence, Item, Source, Span, Unit
from .sources import resolve_pointer


def _chunk_for_pointer(chunks: list[Chunk], ptr: str) -> str:
    return chunk_of(chunks, Span(pointer=ptr)) or chunks[0].id


def units_for(source: Source, chunks: list[Chunk], stats: dict[str, PathStat]) -> list[Unit]:
    units: list[Unit] = []
    for c in chunks:
        example = c.pointers[0] if c.pointers else f"L{c.start_line}-{c.end_line}"
        units.append(Unit(id=f"chunk:{c.id}", kind="chunk", example=example, chunk_id=c.id))
    if source.kind != "json":
        return units
    for pat, s in sorted(stats.items()):
        leafy = any(t not in ("object", "array") for t in s.types)
        if leafy:
            units.append(Unit(id=f"path:{pat}", kind="path", pattern=pat, example=s.example, chunk_id=_chunk_for_pointer(chunks, s.example)))
        if s.is_enum:
            for v, n in s.values.items():
                ex = s.value_example[v]
                units.append(Unit(id=f"value:{pat}={v}", kind="value", pattern=pat, value=v, example=ex,
                                  chunk_id=_chunk_for_pointer(chunks, ex), rarity=n / s.count))
        if s.numeric and s.num_min != s.num_max:  # boundary values, and zero (free item, no discount)
            for tag, ptr in sorted(s.num_examples.items()):
                v = json.dumps(resolve_pointer(source.data, ptr))
                if not any(u.id == f"value:{pat}={v}" for u in units):
                    units.append(Unit(id=f"value:{pat}={v}", kind="value", pattern=pat, value=v, example=ptr,
                                      chunk_id=_chunk_for_pointer(chunks, ptr), rarity=s.values.get(v, 1) / s.count))
        if s.nulls and len(s.types) > 1:  # a field that is sometimes null (always-null fields are just constants)
            units.append(Unit(id=f"null:{pat}", kind="null", pattern=pat, value="null", example=s.null_example,
                              chunk_id=_chunk_for_pointer(chunks, s.null_example), rarity=s.nulls / s.count))
        if s.missing:
            units.append(Unit(id=f"missing:{pat}", kind="missing", pattern=pat, example=s.missing_example,
                              chunk_id=_chunk_for_pointer(chunks, s.missing_example), rarity=s.missing / max(1, s.parents)))
    return units


def _quote_lines(source: Source, quote: str) -> int | None:
    q = normalize(quote)
    for n, line in enumerate(source.text.splitlines(), 1):
        if q[:40] and q[:40] in normalize(line):
            return n
    return None


def _query_hits(query: str, units: list[Unit]) -> set[str]:
    """What a computed fact tests: the fields a query names, and the values it filters on."""
    names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", query))
    flat = query.replace(" ", "")
    # field compared with a literal: status=='CAN', discount_pct>`0`, `0`==discount_pct
    compared: set[tuple[str, str]] = set()
    lit = r"'((?:[^'\\]|\\.)*)'|`([^`]*)`"
    for m in re.finditer(rf"([A-Za-z_][A-Za-z0-9_]*)(?:==|!=|<=|>=|<|>)(?:{lit})", flat):
        compared.add((m[1], m[2] if m[2] is not None else m[3]))
    for m in re.finditer(rf"(?:{lit})(?:==|!=|<=|>=|<|>)([A-Za-z_][A-Za-z0-9_]*)", flat):
        compared.add((m[3], m[1] if m[1] is not None else m[2]))
    hit: set[str] = set()
    for u in units:
        if u.kind == "chunk":
            continue
        key = u.pattern.rsplit("/", 1)[1]
        if key not in names:
            continue
        if u.kind == "path":
            hit.add(u.id)
        elif u.kind == "value" and u.value is not None:
            v = json.loads(u.value)
            if (key, v if isinstance(v, str) else json.dumps(v)) in compared:
                hit.add(u.id)
        elif u.kind == "null" and ((key, "null") in compared or f"{key}==null" in flat):
            hit.add(u.id)
        elif u.kind == "missing" and (f"?{key}" in flat or f"!{key}" in flat):
            hit.add(u.id)
    return hit


def covered_by(item: Item, evidence: list[Evidence], source: Source, chunks: list[Chunk], units: list[Unit]) -> set[str]:
    hit: set[str] = set()
    if item.chunk_id:
        hit.add(f"chunk:{item.chunk_id}")
    by_pattern: dict[str, list[Unit]] = {}
    for u in units:
        if u.kind != "chunk":
            by_pattern.setdefault(u.pattern, []).append(u)
    for ev in evidence:
        if source.kind == "text":
            if ev.quote and (n := _quote_lines(source, ev.quote)) is not None:
                if (cid := chunk_of(chunks, Span(start_line=n, end_line=n))) is not None:
                    hit.add(f"chunk:{cid}")
            continue
        if ev.query:
            hit |= _query_hits(ev.query, units)
            continue
        if ev.pointer is None:
            continue
        try:
            value = resolve_pointer(source.data, ev.pointer)
        except KeyError:
            continue
        if (cid := chunk_of(chunks, Span(pointer=ev.pointer))) is not None:
            hit.add(f"chunk:{cid}")
        pat = pattern(ev.pointer)
        enc = json.dumps(value, ensure_ascii=False)
        for u in by_pattern.get(pat, []):
            if u.kind == "path" or (u.kind in ("value", "null") and u.value == enc):
                hit.add(u.id)
        if isinstance(value, dict):  # citing an object shows which keys it lacks
            for u in units:
                if u.kind == "missing" and u.pattern.rsplit("/", 1)[0] == pat and u.pattern.rsplit("/", 1)[1] not in value:
                    hit.add(u.id)
    return hit


class CoverageReport(BaseModel):
    total: int
    covered: int
    by_kind: dict[str, tuple[int, int]]  # kind -> (covered, total)
    uncovered: list[Unit]  # rarest edge cases first

    @property
    def ratio(self) -> float:
        return self.covered / self.total if self.total else 1.0


def measure(units: list[Unit], hits: set[str]) -> CoverageReport:
    total, cov = Counter(u.kind for u in units), Counter(u.kind for u in units if u.id in hits)
    order = {"value": 0, "null": 0, "missing": 0, "path": 1, "chunk": 2}
    left = sorted((u for u in units if u.id not in hits), key=lambda u: (order[u.kind], u.rarity, u.id))
    return CoverageReport(total=len(units), covered=sum(cov.values()), by_kind={k: (cov[k], total[k]) for k in total}, uncovered=left)


def render_units(units: list[Unit], limit: int) -> str:
    lines = []
    for u in units[:limit]:
        what = {"chunk": "nothing tested in this chunk yet", "path": f"field {u.pattern}", "value": f"{u.pattern} = {u.value}",
                "null": f"{u.pattern} is null", "missing": f"key {u.pattern} is missing"}[u.kind]
        share = "" if u.kind in ("chunk", "path") else f" ({u.rarity:.1%} of occurrences)"
        lines.append(f"- [{u.chunk_id}] {what}{share}; e.g. at {u.example}")
    if len(units) > limit:
        lines.append(f"- ... {len(units) - limit} more")
    return "\n".join(lines) or "(none: everything is covered)"


@dataclass
class Atlas:
    """What code knows about one source before any model reads it."""

    chunks: list[Chunk]
    stats: dict[str, PathStat]
    units: list[Unit]

    @property
    def large(self) -> bool:
        return len(self.chunks) > 1

    def unit_counts(self) -> dict[str, int]:
        return dict(Counter(u.chunk_id for u in self.units))


def build_atlas(source: Source, cfg: Config) -> Atlas:
    chunks = chunk_source(source, cfg.chunking)
    stats = profile(source.data, cfg.coverage.enum_max_distinct) if source.kind == "json" else {}
    return Atlas(chunks=chunks, stats=stats, units=units_for(source, chunks, stats))

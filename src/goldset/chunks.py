"""Cut sources into chunks along their structure, so every part of a large source gets planned and checked.

JSON: a subtree that fits stays whole; a bigger one is split into its children, and runs of small
siblings (consecutive array elements, neighbouring keys) are packed into one chunk. Text: sections
start at headings and are packed paragraph by paragraph. Spans keep the source's own pointers and
line numbers, so nothing is renumbered.
"""

import json
from typing import Any

from .config import ChunkingCfg
from .profile import within
from .schemas import Chunk, Source, Span
from .sources import leaves, resolve_pointer


def _esc(k: str) -> str:
    return k.replace("~", "~0").replace("/", "~1")


def leaf_count(node: Any) -> int:
    if isinstance(node, dict) and node:
        return sum(leaf_count(v) for v in node.values())
    if isinstance(node, list) and node:
        return sum(leaf_count(v) for v in node)
    return 1


def _json_groups(data: Any, max_leaves: int) -> list[tuple[list[str], int]]:
    def walk(node: Any, ptr: str, size: int) -> list[tuple[list[str], int]]:
        if size <= max_leaves or not isinstance(node, (dict, list)) or not node:
            return [([ptr], size)]
        kids = [(f"{ptr}/{_esc(str(k))}", v) for k, v in node.items()] if isinstance(node, dict) else \
               [(f"{ptr}/{i}", v) for i, v in enumerate(node)]
        out: list[tuple[list[str], int]] = []
        cur: list[str] = []
        n = 0
        for kp, kv in kids:
            ks = leaf_count(kv)
            if ks > max_leaves:
                if cur:
                    out.append((cur, n))
                    cur, n = [], 0
                out += walk(kv, kp, ks)
                continue
            if cur and n + ks > max_leaves:
                out.append((cur, n))
                cur, n = [], 0
            cur.append(kp)
            n += ks
        if cur:
            out.append((cur, n))
        return out

    return walk(data, "", leaf_count(data))


def _title(pointers: list[str]) -> str:
    if len(pointers) == 1:
        return pointers[0] or "(whole document)"
    return f"{pointers[0]} .. {pointers[-1]} ({len(pointers)} subtrees)"


def _text_chunks(text: str, max_chars: int) -> list[Chunk]:
    lines = text.splitlines()
    # blocks: runs of lines split at blank lines and before headings
    blocks: list[tuple[int, int]] = []
    start = None
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith("#") and start is not None:
            blocks.append((start, n - 1))
            start = None
        if line.strip():
            start = start or n
        elif start is not None:
            blocks.append((start, n - 1))
            start = None
    if start is not None:
        blocks.append((start, len(lines)))

    def size(a: int, b: int) -> int:
        return sum(len(x) + 1 for x in lines[a - 1 : b])

    def heading(a: int) -> str:
        for n in range(a, 0, -1):
            if lines[n - 1].lstrip().startswith("#"):
                return lines[n - 1].strip("# ").strip()
        return f"line {a}"

    out: list[Chunk] = []
    cur: tuple[int, int] | None = None
    for a, b in blocks:
        top = lines[a - 1].lstrip().startswith(("# ", "## "))  # a section break: cut here once the chunk is half full
        if cur and (size(cur[0], b) > max_chars or (top and size(*cur) >= max_chars // 2)):
            out.append(Chunk(id="", title=heading(cur[0]), start_line=cur[0], end_line=cur[1], size=size(*cur)))
            cur = None
        cur = (cur[0], b) if cur else (a, b)
    if cur:
        out.append(Chunk(id="", title=heading(cur[0]), start_line=cur[0], end_line=cur[1], size=size(*cur)))
    return out or [Chunk(id="", title="(empty)", start_line=1, end_line=max(1, len(lines)), size=0)]


def chunk_source(source: Source, cfg: ChunkingCfg) -> list[Chunk]:
    if source.kind == "json":
        chunks = [Chunk(id="", title=_title(ps), pointers=ps, size=n) for ps, n in _json_groups(source.data, cfg.json_max_leaves)]
    else:
        chunks = _text_chunks(source.text, cfg.text_max_chars)
    width = max(2, len(str(len(chunks))))
    return [c.model_copy(update={"id": f"C{i:0{width}d}"}) for i, c in enumerate(chunks, 1)]


def chunk_of(chunks: list[Chunk], span: Span) -> str | None:
    """The chunk a span starts in (JSON: the chunk holding the pointer, or the first one inside it)."""
    for c in chunks:
        if span.pointer is not None:
            if any(within(span.pointer, p) or within(p, span.pointer) for p in c.pointers):
                return c.id
        elif c.start_line is not None and c.end_line is not None and span.start_line is not None:
            if c.start_line <= span.start_line <= c.end_line or (span.start_line < c.start_line and (span.end_line or 0) >= c.start_line):
                return c.id
    return None


def inside(chunk: Chunk, span: Span) -> bool:
    if span.pointer is not None:
        return any(within(span.pointer, p) for p in chunk.pointers)
    return (chunk.start_line or 0) <= (span.start_line or 0) and (span.end_line or 0) <= (chunk.end_line or 0)


def span_size(source: Source, span: Span) -> int:
    if source.kind == "json":
        return leaf_count(resolve_pointer(source.data, span.pointer or ""))
    return sum(len(x) + 1 for x in source.text.splitlines()[(span.start_line or 1) - 1 : span.end_line])


def render_chunk(source: Source, chunk: Chunk) -> str:
    if source.kind == "json":
        body = "\n".join(f"{p or '(root)'} = {json.dumps(v, ensure_ascii=False)}" for root in chunk.pointers for p, v in leaves(resolve_pointer(source.data, root), root))
        return f"SOURCE {source.id}, CHUNK {chunk.id}: {chunk.title} (one line per leaf: pointer = value)\n{body}"
    lines = source.text.splitlines()
    a, b = chunk.start_line or 1, chunk.end_line or len(lines)
    width = len(str(b))
    body = "\n".join(f"{n:>{width}} | {line}" for n, line in enumerate(lines[a - 1 : b], a))
    return f"SOURCE {source.id}, CHUNK {chunk.id}: {chunk.title} (lines {a}-{b})\n{body}"


def render_chunk_list(chunks: list[Chunk], unit_counts: dict[str, int]) -> str:
    return "\n".join(
        f"{c.id}  {c.title}  ({c.size} {'leaves' if c.pointers else 'chars'}; {unit_counts.get(c.id, 0)} coverage units)" for c in chunks
    )

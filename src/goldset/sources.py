"""Load sources and prompts from disk and render them for the models.

Pairing rule for structured input: `X.json` takes its glossary from `X.md`, `X.glossary.md`
or `X.schema.md` next to it; failing that, from `glossary.md` / `_glossary.md` in the same
folder (one glossary for many records). A markdown file used as a glossary is not a source.
"""

import fnmatch
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from .config import RenderCfg
from .schemas import PromptSpec, Source, Span, Task

DIR_GLOSSARIES = ("glossary.md", "_glossary.md")
PROMPT_SUFFIXES = {".md", ".txt", ".prompt"}


def _glossary_for(path: Path) -> Path | None:
    stem = path.with_suffix("")
    for cand in (stem.with_suffix(".md"), Path(f"{stem}.glossary.md"), Path(f"{stem}.schema.md")):
        if cand.is_file():
            return cand
    for name in DIR_GLOSSARIES:
        if (path.parent / name).is_file():
            return path.parent / name
    return None


def load_sources(root: Path) -> list[Source]:
    files = sorted(p for p in root.rglob("*") if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts))
    glossaries = {g for p in files if p.suffix == ".json" and (g := _glossary_for(p))}
    out: list[Source] = []
    for p in files:
        if p in glossaries:
            continue
        rel = p.relative_to(root).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary files are not sources
        if p.suffix == ".json":
            g = _glossary_for(p)
            out.append(Source(
                id=rel, kind="json", text=text, data=json.loads(text),
                glossary=g.read_text(encoding="utf-8") if g else None,
                glossary_id=g.relative_to(root).as_posix() if g else None,
            ))
        else:
            out.append(Source(id=rel, kind="text", text=text))
    return out


def _front_matter(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            meta = yaml.safe_load(text[4:end]) or {}
            return meta, text[end + 4 :].lstrip("\n")
    return {}, text


def load_prompts(root: Path) -> list[PromptSpec]:
    paths = [root] if root.is_file() else sorted(p for p in root.iterdir() if p.suffix in PROMPT_SUFFIXES)
    out: list[PromptSpec] = []
    for p in paths:
        meta, body = _front_matter(p.read_text(encoding="utf-8"))
        out.append(PromptSpec(id=p.stem, text=body.strip(), **meta))
    return out


def make_tasks(prompts: list[PromptSpec], sources: list[Source]) -> list[Task]:
    return [
        Task(id=f"{p.id}@{s.id}", prompt_id=p.id, source_id=s.id, output_format=p.output_format or "text")
        for p in prompts
        for s in sources
        if any(fnmatch.fnmatch(s.id, g) for g in p.applies_to)
    ]


# --- JSON pointers ------------------------------------------------------------


def _escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def resolve_pointer(data: Any, pointer: str) -> Any:
    """RFC 6901. Raises KeyError if the pointer does not resolve."""
    if pointer == "":
        return data
    if not pointer.startswith("/"):
        raise KeyError(f"pointer must start with '/': {pointer!r}")
    cur = data
    for raw in pointer[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        elif isinstance(cur, list) and key.isdigit() and int(key) < len(cur):
            cur = cur[int(key)]
        else:
            raise KeyError(f"{pointer!r} does not resolve at {key!r}")
    return cur


def leaves(data: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """(pointer, value) for every scalar and every empty container."""
    if isinstance(data, dict) and data:
        for k, v in data.items():
            yield from leaves(v, f"{prefix}/{_escape(str(k))}")
    elif isinstance(data, list) and data:
        for i, v in enumerate(data):
            yield from leaves(v, f"{prefix}/{i}")
    else:
        yield prefix, data


# --- rendering ----------------------------------------------------------------


def _numbered(lines: list[str], start: int) -> str:
    width = len(str(start + len(lines)))
    return "\n".join(f"{n:>{width}} | {line}" for n, line in enumerate(lines, start))


def _json_view(source: Source, pointer: str, cfg: RenderCfg) -> str:
    found = list(leaves(resolve_pointer(source.data, pointer), pointer))
    shown = found[: cfg.max_json_leaves]
    body = "\n".join(f"{p or '(root)'} = {json.dumps(v, ensure_ascii=False)}" for p, v in shown)
    if len(found) > len(shown):
        body += f"\n... {len(found) - len(shown)} more leaves not shown"
    parts = [f"SOURCE {source.id} (JSON, one line per leaf: pointer = value)\n{body}"]
    if source.glossary:
        parts.append(f"FIELD GLOSSARY ({source.glossary_id})\n{source.glossary.strip()}")
    return "\n\n".join(parts)


def render_for_planner(source: Source, cfg: RenderCfg) -> str:
    if source.kind == "json":
        return _json_view(source, "", cfg)
    lines = source.text.splitlines()
    if len(source.text) <= cfg.planner_max_chars:
        return f"SOURCE {source.id} ({len(lines)} lines)\n{_numbered(lines, 1)}"
    heads = [(n, line) for n, line in enumerate(lines, 1) if line.lstrip().startswith("#")]
    outline = "\n".join(f"{n:>6} | {line}" for n, line in heads) or "(no headings)"
    return f"SOURCE {source.id} ({len(lines)} lines, too long to show; outline of headings)\n{outline}"


def render_span(source: Source, span: Span, cfg: RenderCfg) -> str:
    if source.kind == "json":
        return _json_view(source, span.pointer or "", cfg)
    lines = source.text.splitlines()
    lo = max(1, (span.start_line or 1) - cfg.context_lines)
    hi = min(len(lines), (span.end_line or len(lines)) + cfg.context_lines)
    return f"SOURCE {source.id} (lines {lo}-{hi} of {len(lines)}; the case is about lines {span.start_line}-{span.end_line})\n{_numbered(lines[lo - 1 : hi], lo)}"


def span_error(source: Source, span: Span) -> str | None:
    if source.kind == "json":
        if span.pointer is None:
            return "JSON source needs span_pointer"
        try:
            resolve_pointer(source.data, span.pointer)
        except KeyError as e:
            return str(e)
        return None
    n = len(source.text.splitlines())
    if span.start_line is None or span.end_line is None:
        return "text source needs span_start_line and span_end_line"
    if not 1 <= span.start_line <= span.end_line <= n:
        return f"line span {span.start_line}-{span.end_line} is outside 1-{n}"
    return None

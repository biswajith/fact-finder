"""Wire inputs, models and the run folder together and run the graph once."""

from collections.abc import Callable
from pathlib import Path

from .brain import Brain, CachedBrain, LangChainBrain
from .config import Config
from .coverage import build_atlas
from .graph import Deps, State, build_graph
from .schemas import Item, Task
from .sources import load_prompts, load_sources, make_tasks
from .store import RunStore


async def run(
    sources_dir: Path,
    prompts_path: Path,
    out_dir: Path,
    cfg: Config,
    brain: Brain | None = None,
    log: Callable[[str], None] = print,
) -> State:
    """Run (or re-run) a dataset build. Re-running into the same folder replays cached model calls,
    so an interrupted run continues where it stopped and a finished one costs nothing."""
    sources = {s.id: s for s in load_sources(sources_dir)}
    prompts = {p.id: p for p in load_prompts(prompts_path)}
    tasks = make_tasks(list(prompts.values()), list(sources.values()))
    if not tasks:
        raise ValueError("no (prompt, source) pairs: check the folders and each prompt's applies_to")
    store = RunStore(out_dir)
    store.write_json("input.json", {
        "sources_dir": str(sources_dir), "prompts": str(prompts_path), "config": cfg,
        "sources": [{"id": s.id, "kind": s.kind, "glossary": s.glossary_id} for s in sources.values()],
        "prompts": [p.id for p in prompts.values()],
    })
    inner = brain if brain is not None else LangChainBrain(cfg)
    atlas = {sid: build_atlas(s, cfg) for sid, s in sources.items()}
    deps = Deps(cfg=cfg, brain=CachedBrain(inner, store.cache_dir, cfg), sources=sources, prompts=prompts, atlas=atlas,
                store=store, log=log)
    log(f"{len(sources)} source(s), {len(prompts)} prompt(s), {len(tasks)} task(s) -> {out_dir}")
    for sid, a in atlas.items():
        log(f"  {sid}: {len(a.chunks)} chunk(s), {len(a.units)} coverage unit(s)")
    graph = build_graph(deps)
    start: State = {"round": 0, "tasks": {t.id: t for t in tasks}, "items": dict[str, Item]()}
    final = await graph.ainvoke(start, {"recursion_limit": 4 * cfg.loop.max_rounds + 10})
    return State(round=final["round"], tasks=dict[str, Task](final["tasks"]), items=final["items"])

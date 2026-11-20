"""The only code that talks to models.

Nodes depend on the `Brain` protocol. `LangChainBrain` is the real one (Luna via ChatOpenAI on
the Responses API, the gate via OpenAIDecisions); `CachedBrain` wraps any brain with a file cache
in the run folder, so re-running a run replays finished calls for free; tests use a scripted brain.
"""

import asyncio
import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, TypeVar

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI, OpenAIDecisions
from langchain_openai.decisions import DecisionResponse, Question
from pydantic import BaseModel

from .config import Config, ModelCfg

T = TypeVar("T", bound=BaseModel)

MAX_QUESTIONS = 400  # Decisions API limit per request

# stage -> which configured model runs it
STAGE_MODEL = {"plan": "planner", "allocate": "planner", "plan_chunk": "planner", "reconcile": "planner", "work": "worker", "solve": "solver", "adjudicate": "adjudicator"}


class Ledger:
    """Counts calls and tokens per stage, for the run report."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.cached: Counter[str] = Counter()
        self.input_tokens: Counter[str] = Counter()
        self.output_tokens: Counter[str] = Counter()
        self.tool_calls: Counter[str] = Counter()

    def as_dict(self) -> dict[str, dict[str, int]]:
        stages = sorted(set(self.calls) | set(self.cached))
        return {
            s: {"calls": self.calls[s], "cached": self.cached[s], "input_tokens": self.input_tokens[s],
                "output_tokens": self.output_tokens[s], "tool_calls": self.tool_calls[s]}
            for s in stages
        }


class Brain(Protocol):
    ledger: Ledger

    async def structured(self, stage: str, schema: type[T], system: str, user: str) -> T: ...

    async def agent(self, stage: str, schema: type[T], system: str, user: str, tools: list[BaseTool], max_tool_calls: int) -> T:
        """Like `structured`, but the model may call `tools` (at most `max_tool_calls` times) before it answers."""
        ...

    async def decide(self, stage: str, shared: Sequence[HumanMessage], questions: dict[str, Question]) -> DecisionResponse: ...


def model_for(cfg: Config, stage: str) -> ModelCfg:
    return getattr(cfg.models, STAGE_MODEL[stage])


def _merge(parts: list[DecisionResponse]) -> DecisionResponse:
    merged = parts[0].model_copy(deep=True)
    for p in parts[1:]:
        merged.answers.update(p.answers)
        merged.usage.input_tokens = (merged.usage.input_tokens or 0) + (p.usage.input_tokens or 0)
    return merged


class LangChainBrain:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ledger = Ledger()
        self._sem = asyncio.Semaphore(cfg.models.max_parallel)
        self._decisions = OpenAIDecisions(model=cfg.models.decisions, max_retries=3)

    def _chat(self, m: ModelCfg) -> ChatOpenAI:
        return ChatOpenAI(
            model=m.name,
            use_responses_api=True,
            reasoning={"effort": m.effort},
            max_completion_tokens=self.cfg.models.max_output_tokens,
            max_retries=3,
        )

    async def structured(self, stage: str, schema: type[T], system: str, user: str) -> T:
        llm = self._chat(model_for(self.cfg, stage)).with_structured_output(schema, method="json_schema", strict=True, include_raw=True)
        async with self._sem:
            out = await llm.ainvoke([SystemMessage(system), HumanMessage(user)])
        assert isinstance(out, dict)
        usage = getattr(out["raw"], "usage_metadata", None) or {}
        self.ledger.calls[stage] += 1
        self.ledger.input_tokens[stage] += usage.get("input_tokens", 0)
        self.ledger.output_tokens[stage] += usage.get("output_tokens", 0)
        if out["parsing_error"] is not None:
            raise out["parsing_error"]
        return schema.model_validate(out["parsed"])

    async def agent(self, stage: str, schema: type[T], system: str, user: str, tools: list[BaseTool], max_tool_calls: int) -> T:
        graph = create_agent(
            self._chat(model_for(self.cfg, stage)),
            tools,
            system_prompt=system,
            response_format=schema,
            middleware=[ToolCallLimitMiddleware(run_limit=max_tool_calls)],
            name=stage,
        )
        async with self._sem:
            result = await graph.ainvoke({"messages": [HumanMessage(user)]})
        names = {t.name for t in tools}
        self.ledger.calls[stage] += 1
        self.ledger.tool_calls[stage] += sum(1 for m in result["messages"] if isinstance(m, ToolMessage) and m.name in names)
        for m in result["messages"]:
            usage = getattr(m, "usage_metadata", None) or {}
            self.ledger.input_tokens[stage] += usage.get("input_tokens", 0)
            self.ledger.output_tokens[stage] += usage.get("output_tokens", 0)
        return schema.model_validate(result["structured_response"])

    async def decide(self, stage: str, shared: Sequence[HumanMessage], questions: dict[str, Question]) -> DecisionResponse:
        names = list(questions)
        chunks = [names[i : i + MAX_QUESTIONS] for i in range(0, len(names), MAX_QUESTIONS)]

        async def one(chunk: list[str]) -> DecisionResponse:
            async with self._sem:
                return await self._decisions.ainvoke({"input": list(shared), "questions": {n: questions[n] for n in chunk}})

        parts = await asyncio.gather(*(one(c) for c in chunks))
        self.ledger.calls[stage] += len(parts)
        self.ledger.input_tokens[stage] += sum(p.usage.input_tokens or 0 for p in parts)
        return _merge(list(parts))


class CachedBrain:
    """Wraps a brain; each distinct request is answered once per run folder."""

    def __init__(self, inner: Brain, cache_dir: Path, cfg: Config):
        self.inner = inner
        self.ledger = inner.ledger
        self.dir = cache_dir
        self.cfg = cfg

    def _path(self, stage: str, payload: object) -> Path:
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:32]
        return self.dir / stage / f"{digest}.json"

    def _hit(self, stage: str, path: Path) -> str | None:
        if path.exists():
            self.ledger.cached[stage] += 1
            return path.read_text()
        return None

    def _put(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(path)

    async def structured(self, stage: str, schema: type[T], system: str, user: str) -> T:
        m = model_for(self.cfg, stage)
        path = self._path(stage, [m.model_dump(), schema.__name__, schema.model_json_schema(), system, user])
        if (hit := self._hit(stage, path)) is not None:
            return schema.model_validate_json(hit)
        out = await self.inner.structured(stage, schema, system, user)
        self._put(path, out.model_dump_json())
        return out

    async def agent(self, stage: str, schema: type[T], system: str, user: str, tools: list[BaseTool], max_tool_calls: int) -> T:
        m = model_for(self.cfg, stage)
        key = [m.model_dump(), schema.__name__, schema.model_json_schema(), system, user, sorted(t.name for t in tools), max_tool_calls]
        path = self._path(stage, key)
        if (hit := self._hit(stage, path)) is not None:
            return schema.model_validate_json(hit)
        out = await self.inner.agent(stage, schema, system, user, tools, max_tool_calls)
        self._put(path, out.model_dump_json())
        return out

    async def decide(self, stage: str, shared: Sequence[HumanMessage], questions: dict[str, Question]) -> DecisionResponse:
        payload = [self.cfg.models.decisions, [m.content for m in shared], {k: q.model_dump() for k, q in questions.items()}]
        path = self._path(stage, payload)
        if (hit := self._hit(stage, path)) is not None:
            return DecisionResponse.model_validate_json(hit)
        out = await self.inner.decide(stage, shared, questions)
        self._put(path, out.model_dump_json())
        return out

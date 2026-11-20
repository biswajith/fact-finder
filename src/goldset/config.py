"""Run settings, loaded from goldset.yaml. Every field has a default, so the file is optional."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

Effort = Literal["low", "medium", "high"]


class ModelCfg(BaseModel):
    name: str = "gpt-6-luna"
    effort: Effort = "medium"


class ModelsCfg(BaseModel):
    planner: ModelCfg = ModelCfg(effort="high")  # writes and revises the todo list
    worker: ModelCfg = ModelCfg()  # writes one candidate per todo item
    solver: ModelCfg = ModelCfg()  # answers the case blind, for the agreement check
    adjudicator: ModelCfg = ModelCfg(effort="high")  # settles cases the gate is unsure about
    decisions: str = "gpt-6-luna"  # the only model the Decisions API serves
    max_output_tokens: int = 8000
    max_parallel: int = 8


class DatasetCfg(BaseModel):
    cases_per_task: int = 6  # target accepted cases per (prompt, source) in "cases" mode
    max_items_per_task: int = 14  # hard cap on todo items, splits and additions included
    max_items_large: int = 80  # the cap for a source split into more than one chunk


class ChunkingCfg(BaseModel):
    json_max_leaves: int = 300  # leaves per JSON chunk (chunks follow the structure: keys, runs of array elements)
    text_max_chars: int = 6000  # characters per text chunk (chunks follow headings and paragraphs)


class CoverageCfg(BaseModel):
    target: float = Field(0.9, ge=0, le=1)  # share of coverage units an accepted case must touch
    enum_max_distinct: int = 12  # a field with at most this many distinct values is an enum: each value is a unit
    max_listed: int = 40  # uncovered units shown to the planner per call
    max_new_per_round: int = 10  # coverage items the reconciler may add per task per round


class ToolsCfg(BaseModel):
    query: bool = True  # JSON sources: workers, solver and adjudicator get the query_json tool
    max_calls: int = 8  # tool calls per worker run
    max_result_chars: int = 4000  # a longer result is cut, and the model is told to narrow the query


class SweepCfg(BaseModel):
    enabled: bool = True  # check each case against every other chunk with the Decisions API
    flag: float = Field(0.5, ge=0, le=1)  # a chunk at or above this probability sends the case to the adjudicator
    max_passages: int = 3  # flagged chunks shown to the adjudicator


class LoopCfg(BaseModel):
    max_rounds: int = 4  # work -> verify -> reconcile passes
    max_attempts: int = 3  # candidates per todo item before it goes to a human


class GateCfg(BaseModel):
    accept: float = Field(0.85, ge=0, le=1)  # every predicate at or above: pass
    reject: float = Field(0.25, ge=0, le=1)  # any predicate below: fail without adjudication
    agree_confidence: float = Field(0.6, ge=0, le=1)  # agreement choice needs this confidence to pass


class RenderCfg(BaseModel):
    context_lines: int = 3  # lines shown around a text span
    planner_max_chars: int = 60_000  # longer sources are shown to the planner as an outline
    max_json_leaves: int = 1500


class Config(BaseModel):
    models: ModelsCfg = ModelsCfg()
    dataset: DatasetCfg = DatasetCfg()
    loop: LoopCfg = LoopCfg()
    gate: GateCfg = GateCfg.model_validate({})
    render: RenderCfg = RenderCfg()
    chunking: ChunkingCfg = ChunkingCfg()
    coverage: CoverageCfg = CoverageCfg.model_validate({})
    sweep: SweepCfg = SweepCfg.model_validate({})
    tools: ToolsCfg = ToolsCfg()


def load_config(path: Path | None) -> Config:
    if path is None or not path.exists():
        return Config()
    return Config.model_validate(yaml.safe_load(path.read_text()) or {})

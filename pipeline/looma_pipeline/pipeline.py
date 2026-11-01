"""Runs the build stages in order and returns what they produced.

Import only; `python -m looma_pipeline build` calls `run_build()`. Side effects are those of the stages: reads
MongoDB (read only) and writes into `data/runs/<run_id>/`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from looma_pipeline.chunking import HfTokenCounter, TokenCounter
from looma_pipeline.config import ConfigError, Settings
from looma_pipeline.logs import add_file_log
from looma_pipeline.mongo_readonly import connect_readonly
from looma_pipeline.runctx import RunContext
from looma_pipeline.source import DataSource, MongoSource
from looma_pipeline.stages import f01_snapshot, f02_content_map, f03_extract, f04_clean, f05_nepali, f06_chunk

log = logging.getLogger(__name__)

STAGES = ("f01", "f02", "f03", "f04", "f05", "f06")


@dataclass
class BuildResult:
    run_id: str
    run_dir: Path
    seconds: float
    outputs: dict[str, Any] = field(default_factory=dict)


def open_mongo_source(settings: Settings) -> MongoSource:
    return MongoSource(connect_readonly(settings.mongo_uri, settings.mongo_db))


def model_token_counter(settings: Settings) -> HfTokenCounter:
    """The embedder's own tokenizer, from the prepared model folder.

    Raises:
        ConfigError: if the model has not been prepared yet.
    """
    path = settings.model_dir / "tokenizer.json"
    if not path.is_file():
        raise ConfigError(f"no tokenizer at {path}: run `make pipeline-model` first")
    return HfTokenCounter(path)


def _run_stages(ctx: RunContext, source: DataSource, outputs: dict[str, Any], until: str | None,
                counter: TokenCounter | None) -> None:
    """Run the stages in order, storing each result in `outputs`; stop after `until`."""
    outputs["snapshot"] = f01_snapshot.run(ctx, source)
    if until == "f01":
        return
    outputs["content_map"] = f02_content_map.run(ctx, outputs["snapshot"])
    if until == "f02":
        return
    raw_pieces = f03_extract.run(ctx, outputs["snapshot"], outputs["content_map"])
    if until == "f03":
        outputs["pieces"] = raw_pieces
        return
    outputs["items"], outputs["pieces"] = f04_clean.run(ctx, outputs["snapshot"], raw_pieces)
    if until == "f04":
        return
    outputs["pieces"] = f05_nepali.run(ctx, outputs["pieces"])
    if until == "f05":
        return
    outputs["passages"] = f06_chunk.run(ctx, outputs["pieces"], counter or model_token_counter(ctx.settings))


def run_build(settings: Settings, scope: str, source: DataSource | None = None, until: str | None = None,
              run_id: str | None = None, counter: TokenCounter | None = None) -> BuildResult:
    """Run the stages for `scope` up to and including `until` (default: all stages).

    Raises:
        ValueError: for an unknown scope or stage name.
    """
    if until is not None and until not in STAGES:
        raise ValueError(f"unknown stage {until!r}; choose one of {', '.join(STAGES)}")
    started = time.perf_counter()
    ctx = RunContext.create(settings, scope, run_id)
    file_log = add_file_log(ctx.run_dir / "run.log")
    try:
        source = source or open_mongo_source(settings)
        result = BuildResult(run_id=ctx.run_id, run_dir=ctx.run_dir, seconds=0.0)
        _run_stages(ctx, source, result.outputs, until, counter)
        result.seconds = round(time.perf_counter() - started, 2)
        log.info("build finished", extra={"run_id": ctx.run_id, "scope": scope, "seconds": result.seconds,
                                          "stages": list(ctx.stage_seconds)})
        return result
    finally:
        logging.getLogger().removeHandler(file_log)
        file_log.close()

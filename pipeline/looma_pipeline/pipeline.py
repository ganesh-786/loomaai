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

from looma_pipeline.config import Settings
from looma_pipeline.logs import add_file_log
from looma_pipeline.mongo_readonly import connect_readonly
from looma_pipeline.runctx import RunContext
from looma_pipeline.source import DataSource, MongoSource
from looma_pipeline.stages import f01_snapshot

log = logging.getLogger(__name__)

STAGES = ("f01",)


@dataclass
class BuildResult:
    run_id: str
    run_dir: Path
    seconds: float
    outputs: dict[str, Any] = field(default_factory=dict)


def open_mongo_source(settings: Settings) -> MongoSource:
    return MongoSource(connect_readonly(settings.mongo_uri, settings.mongo_db))


def run_build(settings: Settings, scope: str, source: DataSource | None = None, until: str | None = None,
              run_id: str | None = None) -> BuildResult:
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
        snapshot = f01_snapshot.run(ctx, source)
        result.outputs["snapshot"] = snapshot
        result.seconds = round(time.perf_counter() - started, 2)
        log.info("build finished", extra={"run_id": ctx.run_id, "scope": scope, "seconds": result.seconds,
                                          "activities_in_scope": snapshot.counts["activities_in_scope"]})
        return result
    finally:
        logging.getLogger().removeHandler(file_log)
        file_log.close()

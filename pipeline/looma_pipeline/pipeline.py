"""Runs the build stages F1 to F13 in order and returns what they produced.

Import only; `python -m looma_pipeline build` calls `run_build()`. Side effects are those of the stages: reads
MongoDB (read only), writes into `data/runs/<run_id>/`, and (F13) writes a signed bundle into `data/bundles/`.
Dependencies can be injected (data source, token counter, embedder, model folder) so every stage runs in tests
without a database or a model.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from looma_pipeline.chunking import HfTokenCounter, TokenCounter
from looma_pipeline.config import ConfigError, Settings
from looma_pipeline.embedder import OnnxEmbedder
from looma_pipeline.logs import add_file_log
from looma_pipeline.mongo_readonly import connect_readonly
from looma_pipeline.runctx import RunContext
from looma_pipeline.source import DataSource, MongoSource
from looma_pipeline.stages import (f01_snapshot, f02_content_map, f03_extract, f04_clean, f05_nepali, f06_chunk,
                                   f07_embed, f08_word_index, f09_suggestions, f12_checks, f13_bundle)

log = logging.getLogger(__name__)

STAGES = ("f01", "f02", "f03", "f04", "f05", "f06", "f07", "f08", "f09", "f12", "f13")
STAGE_REPORTS = ("f01_snapshot", "f02_content_map", "f03_extract", "f04_clean", "f05_nepali", "f06_chunk",
                 "f07_embed", "f08_word_index", "f09_suggestions", "f12_checks", "f13_bundle")


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


def int8_embedder(settings: Settings) -> OnnxEmbedder:
    """The prepared int8 embedder (about 430 MB resident once warmed, measured on the dev VM).

    Raises:
        ConfigError: if the model has not been prepared yet.
    """
    try:
        return OnnxEmbedder.from_settings(settings)
    except FileNotFoundError as exc:
        raise ConfigError(str(exc)) from exc


def full_size_embedder(settings: Settings) -> OnnxEmbedder | None:
    """The full-size embedder for F7's int8 agreement report, or None if its file is absent (about 746 MB)."""
    path = settings.model_dir / "model.fp32.onnx"
    return OnnxEmbedder.from_settings(settings, model_file=path.name) if path.is_file() else None


def _run_stages(ctx: RunContext, source: DataSource, out: dict[str, Any], until: str | None,
                counter: TokenCounter | None, embedder: f07_embed.Embedder | None,
                int8_agreement: bool | None, model_dir: Path) -> None:
    """Run the stages in order, storing each result in `out`; stop after `until`."""
    def done(stage: str) -> bool:
        return until == stage

    out["snapshot"] = f01_snapshot.run(ctx, source)
    if done("f01"):
        return
    out["content_map"] = f02_content_map.run(ctx, out["snapshot"])
    if done("f02"):
        return
    out["pieces"] = f03_extract.run(ctx, out["snapshot"], out["content_map"])
    if done("f03"):
        return
    out["items"], out["pieces"] = f04_clean.run(ctx, out["snapshot"], out["pieces"])
    if done("f04"):
        return
    out["pieces"] = f05_nepali.run(ctx, out["pieces"])
    if done("f05"):
        return
    out["passages"] = f06_chunk.run(ctx, out["pieces"], counter or model_token_counter(ctx.settings))
    if done("f06"):
        return
    if int8_agreement is None:
        int8_agreement = embedder is None
    if embedder is None:
        embedder = int8_embedder(ctx.settings)
    full_model = full_size_embedder(ctx.settings) if int8_agreement else None
    out["vectors"] = f07_embed.run(ctx, out["passages"], embedder, full_model)
    full_model = None  # only F7's int8 agreement report uses it; free it before the later stages
    if done("f07"):
        return
    f08_word_index.run(ctx, out["snapshot"], out["items"], out["passages"])
    if done("f08"):
        return
    out["proposals"] = f09_suggestions.run(ctx, out["snapshot"], out["items"], embedder)
    if done("f09"):
        return
    out["checks"] = f12_checks.run(ctx, out["snapshot"], out["items"], embedder)
    if done("f12"):
        return
    out["bundle"] = f13_bundle.run(ctx, out["snapshot"], embedder, out["checks"], model_dir)


def run_build(settings: Settings, scope: str, source: DataSource | None = None, until: str | None = None,
              run_id: str | None = None, counter: TokenCounter | None = None,
              embedder: f07_embed.Embedder | None = None, model_dir: Path | None = None,
              int8_agreement: bool | None = None) -> BuildResult:
    """Run the stages for `scope` up to and including `until` (default: all stages, ending with a signed bundle).

    Without `embedder`, the prepared int8 model is loaded. `int8_agreement` decides whether F7 also loads the
    full-size model, compares the two on a sample and releases it; by default only when no `embedder` is given.
    The e2e run passes one shared int8 embedder to both builds and asks for the comparison in build 1 only.

    Raises:
        ValueError: for an unknown scope or stage name.
        ConfigError: when the model has not been prepared.
        ChecksFailed: when an F12 gate fails (no bundle is written).
    """
    if until is not None and until not in STAGES:
        raise ValueError(f"unknown stage {until!r}; choose one of {', '.join(STAGES)}")
    started = time.perf_counter()
    ctx = RunContext.create(settings, scope, run_id)
    file_log = add_file_log(ctx.run_dir / "run.log")
    try:
        source = source or open_mongo_source(settings)
        result = BuildResult(run_id=ctx.run_id, run_dir=ctx.run_dir, seconds=0.0)
        _run_stages(ctx, source, result.outputs, until, counter, embedder, int8_agreement,
                    model_dir or settings.model_dir)
        result.seconds = round(time.perf_counter() - started, 2)
        log.info("build finished", extra={
            "run_id": ctx.run_id, "scope": scope, "seconds": result.seconds,
            "passages": len(result.outputs.get("passages", [])),
            "bundle": str(result.outputs["bundle"]) if "bundle" in result.outputs else None})
        return result
    finally:
        logging.getLogger().removeHandler(file_log)
        file_log.close()

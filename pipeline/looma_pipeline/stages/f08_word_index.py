"""F8 word index: write the staged bundle's SQLite file (items, passages, FTS5, dictionary).

Import only (called by looma_pipeline.pipeline). See looma_pipeline.word_index for the schema and the Devanagari
tokenizer setting. Side effects: writes `staging/meta/chunks.db` and `f08_word_index.json` in the run folder.
"""

from __future__ import annotations

from looma_pipeline.models import Item, Passage
from looma_pipeline.runctx import RunContext
from looma_pipeline.stages.f01_snapshot import Snapshot
from looma_pipeline.word_index import FTS_TOKENIZER, build_word_index

DB_RELATIVE_PATH = "meta/chunks.db"


def run(ctx: RunContext, snapshot: Snapshot, items: dict[str, Item], passages: list[Passage]) -> None:
    with ctx.stage("f08_word_index") as report:
        path = ctx.staging_dir / DB_RELATIVE_PATH
        counts = build_word_index(path, items, passages, snapshot.dictionary, {
            "snapshot_hash": snapshot.snapshot_hash, "scope": ctx.scope, "fts_tokenizer": FTS_TOKENIZER})
        report.counts.update(counts)
        report.counts["dictionary_pairs_dropped"] = len(snapshot.dictionary) - counts["dictionary_pairs"]
        report.details["bytes"] = path.stat().st_size

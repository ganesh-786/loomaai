"""F13 pack and sign: turn the checked staging folder into a signed bundle in `data/bundles/`.

Import only (called by looma_pipeline.pipeline, only after F12 passed). Puts the staged vectors, SQLite file and
self-test queries plus the int8 model files into `data/bundles/.incoming-<name>/`, writes `manifest.json`,
`SHA256SUMS` and the ed25519 signature, then renames the folder to `data/bundles/<name>/` in one step, so a reader
never sees a half-written bundle. Files are hard-linked where possible (looma_pipeline.fsutil): the bundle shares
bytes with the run's staging folder and the prepared model instead of copying them; copying the bundle elsewhere
still copies every byte. The first build creates the signing key pair in `data/keys/` (ignored by Git).
Side effects: writes the bundle folder, possibly the key pair, and `f13_bundle.json`.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from looma_pipeline import BUNDLE_SCHEMA_VERSION, __version__
from looma_pipeline.bundle import (MANIFEST_FILE, content_hash, ensure_keys, load_private_key,
                                   write_checksums_and_sign)
from looma_pipeline.embedder import INT8_NAME, ModelInfo
from looma_pipeline.fsutil import copy_tree_linked, link_or_copy
from looma_pipeline.hashing import sha256_of_file
from looma_pipeline.runctx import RunContext, utc_now
from looma_pipeline.stages.f01_snapshot import Snapshot
from looma_pipeline.stages.f07_embed import Embedder
from looma_pipeline.word_index import FTS_TOKENIZER

STAGED_FOLDERS = ("vectors", "meta", "tests")
MODEL_FILES = (INT8_NAME, "tokenizer.json", "README.md")


def bundle_name(bundles_dir: Path, scope: str, now: datetime | None = None) -> str:
    """`looma-ai-bundle-YYYY.MM.DD-<scope>-rN`, with N the next free number for that day and scope."""
    stem = f"looma-ai-bundle-{(now or datetime.now(timezone.utc)):%Y.%m.%d}-{scope}"
    number = 1
    while (bundles_dir / f"{stem}-r{number}").exists():
        number += 1
    return f"{stem}-r{number}"


def _passage_counts(bundle_dir: Path) -> dict:
    import sqlite3

    db = sqlite3.connect(f"file:{bundle_dir / 'meta' / 'chunks.db'}?mode=ro", uri=True)
    try:
        return {
            "items": db.execute("SELECT COUNT(*) FROM items").fetchone()[0],
            "passages": db.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
            "dictionary_pairs": db.execute("SELECT COUNT(*) FROM dictionary").fetchone()[0],
            "passages_by_language": dict(db.execute("SELECT lang, COUNT(*) FROM passages GROUP BY lang")),
        }
    finally:
        db.close()


def run(ctx: RunContext, snapshot: Snapshot, embedder: Embedder, checks: dict, model_dir: Path) -> Path:
    """Write and sign the bundle. Returns its folder."""
    settings = ctx.settings
    with ctx.stage("f13_bundle") as report:
        settings.bundles_dir.mkdir(parents=True, exist_ok=True)
        name = bundle_name(settings.bundles_dir, ctx.scope)
        incoming = settings.bundles_dir / f".incoming-{name}"
        if incoming.exists():
            shutil.rmtree(incoming)
        linked = copied = 0
        for folder in STAGED_FOLDERS:
            folder_linked, folder_copied = copy_tree_linked(ctx.staging_dir / folder, incoming / folder)
            linked, copied = linked + folder_linked, copied + folder_copied
        (incoming / "model").mkdir()
        for file_name in MODEL_FILES:
            if link_or_copy(model_dir / file_name, incoming / "model" / file_name):
                linked += 1
            else:
                copied += 1
        info = ModelInfo.load(model_dir)
        model_sha, tokenizer_sha = (sha256_of_file(incoming / "model" / f) for f in (INT8_NAME, "tokenizer.json"))
        (incoming / "model" / "model_info.json").write_text(json.dumps({
            "repo": info.repo, "revision": info.revision, "license": info.license,
            "files": {f: sha256_of_file(incoming / "model" / f) for f in MODEL_FILES},
            "quantization": info.quantization}, indent=2) + "\n", encoding="utf-8")

        key = ensure_keys(settings.signing_key_path, settings.signing_pubkey_path)
        vectors_info = json.loads((incoming / "vectors" / "vectors_info.json").read_text(encoding="utf-8"))
        manifest = {
            "bundle_name": name, "schema_version": BUNDLE_SCHEMA_VERSION, "created_at": utc_now(),
            "run_id": ctx.run_id, "builder": {"version": __version__, "git_sha": settings.git_sha},
            "snapshot": {"id": snapshot.snapshot_id, "hash": snapshot.snapshot_hash, "scope": ctx.scope,
                         "curated_checksum": snapshot.curated_checksum},
            "embedding": {"repo": info.repo, "revision": info.revision, "license": info.license,
                          "model_file": INT8_NAME, "model_sha256": model_sha, "tokenizer_sha256": tokenizer_sha,
                          "model_key": embedder.model_key, "dims": vectors_info["dims"], "pooling": "mean",
                          "normalized": True, "query_prefix": settings.query_prefix,
                          "passage_prefix": settings.passage_prefix, "batch_size": 1,
                          "vector_storage": vectors_info["quantization"]},
            "chunking": {"target_tokens": settings.chunk_target_tokens, "max_tokens": settings.chunk_max_tokens,
                         "overlap_tokens": settings.chunk_overlap_tokens, "tokenizer": "the model's tokenizer.json"},
            "word_index": {"engine": "SQLite FTS5", "tokenizer": FTS_TOKENIZER},
            "counts": _passage_counts(incoming),
            "content_hash": content_hash(incoming, model_sha, tokenizer_sha),
            "checks": checks,
            "signing": {"algorithm": "ed25519", "key_id": key, "signed_file": "SHA256SUMS"},
        }
        (incoming / MANIFEST_FILE).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8")
        write_checksums_and_sign(incoming, load_private_key(settings.signing_key_path))
        final = settings.bundles_dir / name
        os.replace(incoming, final)  # one rename: readers see the whole bundle or none of it

        files = [p for p in final.rglob("*") if p.is_file()]
        report.counts.update({"files": len(files), "bytes": sum(p.stat().st_size for p in files),
                              "files_hard_linked": linked, "files_copied": copied})
        report.details.update({"bundle": name, "path": str(final), "content_hash": manifest["content_hash"],
                               "key_id": key})
        return final

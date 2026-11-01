"""Verify a bundle the way a reader must before using it: signature, checksums, model, content hash, self-test.

Import only; `python -m looma_pipeline verify <bundle>` calls `verify()`. The self-test loads the bundle's own int8
model (offline) and repeats the queries F12 saved in `tests/self_test.jsonl`.
Side effects: none.
"""

from __future__ import annotations

import json
from pathlib import Path

from looma_pipeline.bundle import VerifyResult, verify_bundle
from looma_pipeline.config import Settings
from looma_pipeline.embedder import OnnxEmbedder
from looma_pipeline.search import SearchEngine
from looma_pipeline.stages.f07_embed import Embedder
from looma_pipeline.stages.f12_checks import SELF_TEST_FILE, self_test_passes


def resolve_bundle(settings: Settings, name_or_path: str) -> Path:
    path = Path(name_or_path)
    return path if path.is_absolute() or path.exists() else settings.bundles_dir / name_or_path


def bundle_embedder(bundle_dir: Path, manifest: dict, settings: Settings) -> OnnxEmbedder:
    """The bundle's own model, configured exactly as the manifest says."""
    embedding = manifest["embedding"]
    return OnnxEmbedder(bundle_dir / "model" / embedding["model_file"], bundle_dir / "model" / "tokenizer.json",
                        embedding["model_key"], embedding["query_prefix"], embedding["passage_prefix"],
                        settings.embed_threads, batch_size=int(embedding.get("batch_size", 1)))


def run_self_test(bundle_dir: Path, embedder: Embedder) -> tuple[int, int]:
    tests = [json.loads(line) for line in (bundle_dir / SELF_TEST_FILE).read_text(encoding="utf-8").splitlines()
             if line.strip()]
    engine = SearchEngine(bundle_dir, embedder)
    try:
        return sum(self_test_passes(engine, test) for test in tests), len(tests)
    finally:
        engine.close()


def verify(bundle_dir: Path, settings: Settings, with_self_test: bool = True,
           embedder: Embedder | None = None) -> VerifyResult:
    """Run every check. `embedder` overrides the bundle's model (tests use a stand-in)."""
    def self_test(directory: Path, manifest: dict) -> tuple[int, int]:
        return run_self_test(directory, embedder or bundle_embedder(directory, manifest, settings))

    return verify_bundle(bundle_dir, settings.signing_pubkey_path,
                         expect_model=(settings.embed_model_repo, settings.embed_model_revision),
                         self_test=self_test if with_self_test else None)

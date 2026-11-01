"""Shared test fixtures. Tests never write to MongoDB; anything written goes to pytest's tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest

from looma_pipeline.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings that write only under tmp_path and point at an empty content folder."""
    content = tmp_path / "content"
    content.mkdir()
    return Settings.from_env({
        "PIPELINE_DATA_DIR": str(tmp_path / "data"),
        "PIPELINE_CONTENT_DIR": str(content),
        "CHUNK_TARGET_TOKENS": "40",
        "CHUNK_MAX_TOKENS": "60",
        "CHUNK_OVERLAP_TOKENS": "8",
        "LOOMA_WEB_URL": "http://127.0.0.1:9",  # nothing listens here: tests never depend on Looma being up
    })


@pytest.fixture
def fake_model_dir(settings: Settings) -> Path:
    """A prepared-model folder with stand-in files, so F13 and verify can run without the real model."""
    import json

    from looma_pipeline.hashing import sha256_of_file

    model_dir = settings.model_dir
    model_dir.mkdir(parents=True)
    (model_dir / "model.int8.onnx").write_bytes(b"stand-in for the int8 ONNX model")
    (model_dir / "tokenizer.json").write_text("{}")
    (model_dir / "README.md").write_text("---\nlicense: mit\n---\n")
    files = {name: sha256_of_file(model_dir / name) for name in ("model.int8.onnx", "tokenizer.json", "README.md")}
    (model_dir / "model_info.json").write_text(json.dumps({
        "repo": settings.embed_model_repo, "revision": settings.embed_model_revision, "license": "mit",
        "files": files, "quantization": {"method": "test stand-in"}}))
    return model_dir

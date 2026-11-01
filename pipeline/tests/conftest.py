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

import json

import looma_fixture as fx
import pytest

from looma_pipeline.chunking import WhitespaceCounter
from looma_pipeline.config import ConfigError
from looma_pipeline.pipeline import run_build
from looma_pipeline.source import DictSource


def test_stages_run_in_order_and_each_writes_a_report(settings):
    result = run_build(settings, "pilot", source=DictSource(fx.looma_data()), until="f06",
                       counter=WhitespaceCounter())
    for stage in ("f01_snapshot", "f02_content_map", "f03_extract", "f04_clean", "f05_nepali", "f06_chunk"):
        report = json.loads((result.run_dir / f"{stage}.json").read_text())
        assert report["status"] == "ok", stage
    passages = result.outputs["passages"]
    assert {p.item_id for p in passages} >= {fx.A_LESSON, fx.A_GAME, fx.A_CH_6S0102, fx.A_IMG_NEPALI}
    assert all(":" in p.passage_id for p in passages)
    assert (result.run_dir / "run.log").stat().st_size > 0


def test_until_stops_early(settings):
    result = run_build(settings, "pilot", source=DictSource(fx.looma_data()), until="f02")
    assert set(result.outputs) == {"snapshot", "content_map"}
    assert not (result.run_dir / "f03_extract.json").exists()


def test_missing_model_fails_fast_with_how_to_fix(settings):
    with pytest.raises(ConfigError, match="make pipeline-model"):
        run_build(settings, "pilot", source=DictSource(fx.looma_data()), until="f06")


def test_unknown_stage_is_rejected(settings):
    with pytest.raises(ValueError, match="unknown stage"):
        run_build(settings, "pilot", source=DictSource(fx.looma_data()), until="f99")


@pytest.mark.parametrize("int8_agreement, compared", [(None, False), (False, False), (True, True)])
def test_full_size_model_is_loaded_for_f7_only_when_asked(settings, monkeypatch, int8_agreement, compared):
    from fake_embedder import FakeEmbedder

    from looma_pipeline import pipeline

    loads = []
    monkeypatch.setattr(pipeline, "full_size_embedder", lambda _settings: loads.append(1) or FakeEmbedder())
    result = run_build(settings, "pilot", source=DictSource(fx.looma_data()), until="f07",
                       counter=WhitespaceCounter(), embedder=FakeEmbedder(), int8_agreement=int8_agreement)
    report = json.loads((result.run_dir / "f07_embed.json").read_text())
    assert ("int8_vs_full" in report["details"]) is compared
    assert len(loads) == int(compared)

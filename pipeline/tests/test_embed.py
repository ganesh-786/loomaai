import json

import numpy as np
import pytest
from fake_embedder import FakeEmbedder

from looma_pipeline.config import Settings
from looma_pipeline.embedder import INT8_NAME, OnnxEmbedder
from looma_pipeline.embedding_cache import EmbeddingCache
from looma_pipeline.models import Passage
from looma_pipeline.runctx import RunContext
from looma_pipeline.stages import f07_embed


def _passages(texts, source="lesson"):
    return [Passage(f"i{n}:en:0", f"i{n}", "en", source, t, None, None, len(t.split())) for n, t in enumerate(texts)]


def test_int8_round_trip_stays_within_one_step():
    rng = np.random.default_rng(0)
    vectors = rng.normal(size=(20, 32)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    restored = f07_embed.from_int8(f07_embed.to_int8(vectors))
    assert np.max(np.abs(restored - vectors)) <= 0.5 / 127 + 1e-6


def test_cache_embeds_each_passage_once_per_model(tmp_path):
    cache = EmbeddingCache(tmp_path / "cache.sqlite")
    passages = _passages(["length is measured in metres", "mass is measured in kilograms",
                          "length is measured in metres"])
    model = FakeEmbedder()
    first, new = f07_embed.embed_with_cache(passages, model, cache)
    assert new == 2 and model.embedded == 2  # the duplicate text is embedded once
    again, new_again = f07_embed.embed_with_cache(passages, model, cache)
    assert new_again == 0 and np.array_equal(first, again)
    changed, n_changed = f07_embed.embed_with_cache(_passages(["a brand new passage"]), model, cache)
    assert n_changed == 1
    _vectors, other_model_new = f07_embed.embed_with_cache(passages, FakeEmbedder(model_key="other@2"), cache)
    assert other_model_new == 2  # a different model never reuses vectors


def test_stage_writes_int8_vectors_and_counts(settings):
    ctx = RunContext.create(settings, "pilot", run_id="r")
    passages = _passages([f"title number {n}" for n in range(12)], source="title")
    vectors = f07_embed.run(ctx, passages, FakeEmbedder(), full_model=FakeEmbedder())
    saved = np.load(ctx.staging_dir / "vectors" / "passages.i8.npy")
    assert saved.dtype == np.int8 and saved.shape == (12, 64) and np.array_equal(saved, vectors)
    report = json.loads((ctx.run_dir / "f07_embed.json").read_text())
    assert report["counts"] == {"passages": 12, "embedded_new": 12, "reused": 0, "dims": 64}
    assert report["details"]["int8_vs_full"]["top10_overlap_mean"] == 1.0
    second = RunContext.create(settings, "pilot", run_id="r2")
    f07_embed.run(second, passages, FakeEmbedder())
    assert json.loads((second.run_dir / "f07_embed.json").read_text())["counts"]["embedded_new"] == 0


@pytest.fixture(scope="module")
def real_model():
    settings = Settings.from_env()
    if not (settings.model_dir / INT8_NAME).is_file():
        pytest.skip("model not prepared (make pipeline-model)")
    return OnnxEmbedder.from_settings(settings)


@pytest.mark.model
def test_real_model_vectors_are_normalized_and_384_wide(real_model):
    vectors = real_model.embed_passages(["Length is measured in metres.", "लम्बाइ मिटरमा नापिन्छ।"])
    assert vectors.shape == (2, 384)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


@pytest.mark.model
def test_real_model_matches_english_to_its_nepali_translation(real_model):
    query = real_model.embed_queries(["measurement and unit"])[0]
    nepali_same, unrelated = real_model.embed_passages(["नाप र एकाइ", "family tree of a village household"])
    assert float(query @ nepali_same) > float(query @ unrelated)


@pytest.mark.model
def test_real_model_batching_does_not_change_results(real_model):
    texts = ["short", "a much longer passage about plants making food from sunlight and water", "मिटर"]
    together = real_model.embed_passages(texts)
    alone = np.stack([real_model.embed_passages([t])[0] for t in texts])
    assert np.allclose(together, alone, atol=1e-4)

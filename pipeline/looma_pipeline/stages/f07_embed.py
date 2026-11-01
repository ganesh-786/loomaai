"""F7 embed: one vector per passage, stored as int8 in the staged bundle.

Import only (called by looma_pipeline.pipeline). Vectors come from the embedding cache when the same model has seen
the same passage before; only new passages are embedded ("reused" counts cache hits and duplicate texts). Vectors are L2-normalized, so each component is in [-1, 1];
they are stored as int8 by `round(v * 127)` (4x smaller than float32) and read back as `int8 / 127`.
When the full-size model file is available, a sample is also embedded with it to record how close int8 stays.
Side effects: reads and writes `data/cache/embeddings.sqlite`; writes `staging/vectors/passages.i8.npy`,
`staging/vectors/vectors_info.json` and `f07_embed.json`.
"""

from __future__ import annotations

import json
import time
from typing import Protocol

import numpy as np

from looma_pipeline.embedding_cache import EmbeddingCache, cache_key
from looma_pipeline.models import Passage
from looma_pipeline.runctx import RunContext

INT8_SCALE = 127.0
QUANT_SAMPLE_PASSAGES = 200   # passages embedded with both models for the int8-vs-full-size check
QUANT_SAMPLE_QUERIES = 50
TOP_K_AGREEMENT = 10


class Embedder(Protocol):
    model_key: str
    dims: int
    passage_prefix: str

    def embed_passages(self, texts: list[str]) -> np.ndarray: ...
    def embed_queries(self, texts: list[str]) -> np.ndarray: ...


def to_int8(vectors: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(vectors * INT8_SCALE), -127, 127).astype(np.int8)


def from_int8(vectors: np.ndarray) -> np.ndarray:
    return vectors.astype(np.float32) / INT8_SCALE


def embed_with_cache(passages: list[Passage], embedder: Embedder, cache: EmbeddingCache) -> tuple[np.ndarray, int]:
    """Float32 vectors in passage order. Returns (vectors, number newly embedded)."""
    texts = [embedder.passage_prefix + p.text for p in passages]
    keys = [cache_key(embedder.model_key, t) for t in texts]
    cached = cache.get_many(keys)
    missing = sorted({k for k in keys if k not in cached})
    if missing:
        first_index = {k: i for i, k in reversed(list(enumerate(keys)))}
        new = embedder.embed_passages([passages[first_index[k]].text for k in missing])
        fresh = dict(zip(missing, new))
        cache.put_many(fresh)
        cached.update(fresh)
    vectors = np.stack([cached[k] for k in keys]) if keys else np.zeros((0, embedder.dims), dtype=np.float32)
    return vectors.astype(np.float32), len(missing)


def int8_agreement(passages: list[Passage], int8_model: Embedder, full_model: Embedder) -> dict:
    """How close int8 vectors stay to full-size ones on a fixed sample (first passages and title queries)."""
    sample = passages[:QUANT_SAMPLE_PASSAGES]
    queries = [p.text for p in sample if p.source == "title"][:QUANT_SAMPLE_QUERIES]
    if len(sample) < TOP_K_AGREEMENT or not queries:
        return {"skipped": "sample too small"}
    a = int8_model.embed_passages([p.text for p in sample])
    b = full_model.embed_passages([p.text for p in sample])
    qa, qb = int8_model.embed_queries(queries), full_model.embed_queries(queries)
    top_a = np.argsort(-(qa @ a.T), axis=1)[:, :TOP_K_AGREEMENT]
    top_b = np.argsort(-(qb @ b.T), axis=1)[:, :TOP_K_AGREEMENT]
    overlap = [len(set(x) & set(y)) / TOP_K_AGREEMENT for x, y in zip(top_a, top_b)]
    return {"passages": len(sample), "queries": len(queries),
            "mean_cosine_int8_vs_full": round(float(np.mean(np.sum(a * b, axis=1))), 4),
            "top10_overlap_mean": round(float(np.mean(overlap)), 4),
            "queries_with_identical_top10": round(float(np.mean([o == 1.0 for o in overlap])), 4)}


def run(ctx: RunContext, passages: list[Passage], embedder: Embedder,
        full_model: Embedder | None = None) -> np.ndarray:
    """Embed every passage and stage the int8 vectors. Returns them (int8, passage order)."""
    with ctx.stage("f07_embed") as report:
        cache = EmbeddingCache(ctx.settings.cache_dir / "embeddings.sqlite")
        started = time.perf_counter()
        try:
            vectors, embedded = embed_with_cache(passages, embedder, cache)
        finally:
            cache.close()
        seconds = time.perf_counter() - started
        quantized = to_int8(vectors)
        out_dir = ctx.staging_dir / "vectors"
        out_dir.mkdir(parents=True, exist_ok=True)
        np.save(out_dir / "passages.i8.npy", quantized, allow_pickle=False)
        info = {"count": int(quantized.shape[0]), "dims": int(embedder.dims), "dtype": "int8",
                "quantization": "round(v * 127), v L2-normalized", "model_key": embedder.model_key}
        (out_dir / "vectors_info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        report.counts.update({"passages": len(passages), "embedded_new": embedded,
                              "reused": len(passages) - embedded, "dims": int(embedder.dims)})
        report.details["embed_seconds"] = round(seconds, 2)
        report.details["passages_per_second_new"] = round(embedded / seconds, 1) if embedded and seconds else None
        report.details["model_key"] = embedder.model_key
        if full_model is not None:
            report.details["int8_vs_full"] = int8_agreement(passages, embedder, full_model)
        return quantized

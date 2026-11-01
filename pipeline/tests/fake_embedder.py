"""A deterministic stand-in for the ONNX embedder: bag-of-words hashing, L2-normalized.

Texts that share words get similar vectors, which is enough to test caching, storage and search plumbing without
downloading a model. It records how many texts it embedded, so tests can check the cache.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np

_WORD = re.compile(r"[\w\u0900-\u097F]+")


class FakeEmbedder:
    def __init__(self, dims: int = 64, model_key: str = "fake-model@1") -> None:
        self.dims = dims
        self.model_key = model_key
        self.query_prefix = "query: "
        self.passage_prefix = "passage: "
        self.embedded = 0

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dims, dtype=np.float32)
        for word in _WORD.findall(text.lower()):
            if word in ("query", "passage"):
                continue
            slot = int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.dims
            vector[slot] += 1.0
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def embed(self, texts: list[str]) -> np.ndarray:
        self.embedded += len(texts)
        return np.stack([self._vector(t) for t in texts]) if texts else np.zeros((0, self.dims), np.float32)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self.embed([self.passage_prefix + t for t in texts])

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self.embed([self.query_prefix + t for t in texts])

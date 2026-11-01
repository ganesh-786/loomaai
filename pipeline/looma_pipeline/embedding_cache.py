"""Embedding cache: never embed the same passage with the same model twice.

Import only. A SQLite file per data folder (`data/cache/embeddings.sqlite`). The key is SHA-256 of the model key
(repo, revision and the int8 file's hash) plus the exact prefixed text, so a new model or a changed passage is always
re-embedded and nothing stale is reused. Side effects: reads and writes that SQLite file.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import numpy as np


def cache_key(model_key: str, prefixed_text: str) -> str:
    return hashlib.sha256(f"{model_key}\n{prefixed_text}".encode("utf-8")).hexdigest()


class EmbeddingCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, dims INTEGER, vec BLOB)")

    def get_many(self, keys: list[str]) -> dict[str, np.ndarray]:
        found: dict[str, np.ndarray] = {}
        for start in range(0, len(keys), 500):  # stay under SQLite's limit on query parameters
            batch = keys[start:start + 500]
            marks = ",".join("?" * len(batch))
            for key, dims, blob in self._db.execute(f"SELECT key, dims, vec FROM vectors WHERE key IN ({marks})", batch):
                found[key] = np.frombuffer(blob, dtype=np.float32, count=dims)
        return found

    def put_many(self, entries: dict[str, np.ndarray]) -> None:
        self._db.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?)",
                             [(k, int(v.shape[0]), v.astype(np.float32).tobytes()) for k, v in entries.items()])
        self._db.commit()

    def close(self) -> None:
        self._db.close()

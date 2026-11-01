"""Deterministic hashing helpers: canonical JSON and SHA-256 of data and files.

Import only; pure functions plus file reads. Canonical JSON (sorted keys, no extra spaces, UTF-8) means the same
data always gives the same hash, which is what makes snapshot hashes and bundle content hashes repeatable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

CHUNK_BYTES = 1 << 20  # read files in 1 MiB blocks


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def sha256_of_values(values: Iterable[Any]) -> str:
    """SHA-256 over a sequence of JSON-able values, each written canonically and newline-separated."""
    digest = hashlib.sha256()
    for value in values:
        digest.update(canonical_json(value))
        digest.update(b"\n")
    return digest.hexdigest()


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

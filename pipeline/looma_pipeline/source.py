"""Where the pipeline gets Looma's records: MongoDB (read only) or an in-memory set for tests.

Import only. `MongoSource` reads through `ReadOnlyDatabase`, so it cannot write. `DictSource` holds plain dicts and
lets every stage be tested without a database. Both return JSON-safe dicts (ObjectId and dates become strings).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterator, Protocol

from looma_pipeline.mongo_readonly import ReadOnlyDatabase


def to_plain(value: Any) -> Any:
    """Convert BSON values (ObjectId, datetime, nested documents) into JSON-safe Python values."""
    if isinstance(value, dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)  # ObjectId, Decimal128, bytes-like ids


class DataSource(Protocol):
    def activities(self) -> Iterator[dict]: ...
    def lessons(self) -> Iterator[dict]: ...
    def games(self) -> Iterator[dict]: ...
    def chapters(self) -> Iterator[dict]: ...
    def textbooks(self) -> Iterator[dict]: ...
    def dictionary(self) -> Iterator[dict]: ...


class MongoSource:
    """Reads Looma's collections through the read-only wrapper."""

    def __init__(self, db: ReadOnlyDatabase) -> None:
        self._db = db

    def _find(self, collection: str, projection: dict | None = None) -> Iterator[dict]:
        cursor = self._db.collection(collection).find({}, projection).sort("_id", 1)
        for document in cursor:
            yield to_plain(document)

    def activities(self) -> Iterator[dict]:
        # BOM-prefixed keys (e.g. "﻿cl_lo") must survive the projection, so read whole documents.
        yield from self._find("activities")

    def lessons(self) -> Iterator[dict]:
        yield from self._find("lessons", {"dn": 1, "ndn": 1, "data": 1, "ch_id": 1, "translator": 1, "translated": 1})

    def games(self) -> Iterator[dict]:
        yield from self._find("games")

    def chapters(self) -> Iterator[dict]:
        yield from self._find("chapters")

    def textbooks(self) -> Iterator[dict]:
        yield from self._find("textbooks")

    def dictionary(self) -> Iterator[dict]:
        yield from self._find("dictionary", {"en": 1, "np": 1})


class DictSource:
    """In-memory records for tests. Keys: activities, lessons, games, chapters, textbooks, dictionary."""

    def __init__(self, data: dict[str, list[dict]]) -> None:
        self._data = {name: [to_plain(row) for row in rows] for name, rows in data.items()}

    def _rows(self, name: str) -> Iterator[dict]:
        yield from sorted(self._data.get(name, []), key=lambda row: str(row.get("_id", "")))

    def activities(self) -> Iterator[dict]:
        yield from self._rows("activities")

    def lessons(self) -> Iterator[dict]:
        yield from self._rows("lessons")

    def games(self) -> Iterator[dict]:
        yield from self._rows("games")

    def chapters(self) -> Iterator[dict]:
        yield from self._rows("chapters")

    def textbooks(self) -> Iterator[dict]:
        yield from self._rows("textbooks")

    def dictionary(self) -> Iterator[dict]:
        yield from self._rows("dictionary")

"""Read-only access to Looma's MongoDB.

Import only. The pipeline never writes to MongoDB (.claude/rules/data-safety.md). This wrapper makes that a property
of the code: it exposes only read methods, and aggregation pipelines that write (`$out`, `$merge`) are rejected.
Side effects: opens a MongoDB connection (network) when `connect_readonly()` is called.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

READ_METHODS = frozenset({"find", "find_one", "count_documents", "estimated_document_count", "distinct"})
WRITE_STAGES = frozenset({"$out", "$merge"})


class ReadOnlyViolation(PermissionError):
    """Raised when code tries to write through the read-only wrapper."""


class ReadOnlyCollection:
    """Wraps a pymongo Collection (or any object with the same read methods) and allows reads only."""

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    @property
    def name(self) -> str:
        return str(self._collection.name)

    def __getattr__(self, attribute: str) -> Any:
        if attribute in READ_METHODS:
            return getattr(self._collection, attribute)
        raise ReadOnlyViolation(f"'{attribute}' is not allowed: the pipeline only reads MongoDB")

    def aggregate(self, pipeline: Sequence[Mapping[str, Any]], **kwargs: Any) -> Iterable[Mapping[str, Any]]:
        """Run an aggregation that only reads.

        Raises:
            ReadOnlyViolation: if any stage would write (`$out`, `$merge`).
        """
        for stage in pipeline:
            writing = WRITE_STAGES.intersection(stage)
            if writing:
                raise ReadOnlyViolation(f"aggregation stage {sorted(writing)} writes data and is not allowed")
        return self._collection.aggregate(list(pipeline), **kwargs)


class ReadOnlyDatabase:
    """Wraps a pymongo Database; every collection comes back wrapped in ReadOnlyCollection."""

    def __init__(self, database: Any) -> None:
        self._database = database

    def collection(self, name: str) -> ReadOnlyCollection:
        return ReadOnlyCollection(self._database[name])

    def list_collection_names(self) -> list[str]:
        return list(self._database.list_collection_names())

    def __getattr__(self, attribute: str) -> Any:
        raise ReadOnlyViolation(f"'{attribute}' is not allowed on the database: the pipeline only reads MongoDB")


def connect_readonly(mongo_uri: str, database: str, timeout_ms: int = 10_000) -> ReadOnlyDatabase:
    """Open MongoDB for reading. Fails fast (ServerSelectionTimeoutError) if the server is unreachable."""
    from pymongo import MongoClient  # imported here so pure-logic tests don't need a driver connection

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=timeout_ms, appname="looma-pipeline-readonly")
    client.admin.command("ping")
    return ReadOnlyDatabase(client[database])

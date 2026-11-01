"""Integration test against the local looma-db, read only. Skipped when the database is unreachable."""

import pytest

from looma_pipeline.config import Settings
from looma_pipeline.mongo_readonly import ReadOnlyViolation, connect_readonly
from looma_pipeline.runctx import RunContext
from looma_pipeline.source import MongoSource
from looma_pipeline.stages import f01_snapshot

pytestmark = pytest.mark.mongo


@pytest.fixture(scope="module")
def source():
    live = Settings.from_env()
    try:
        db = connect_readonly(live.mongo_uri, live.mongo_db, timeout_ms=3000)
    except Exception as exc:  # any connection failure means "no local database": skip, don't fail
        pytest.skip(f"looma-db not reachable: {type(exc).__name__}")
    return db, MongoSource(db)


def test_real_database_rejects_writes_through_the_wrapper(source):
    db, _ = source
    with pytest.raises(ReadOnlyViolation):
        db.collection("activities").insert_one({"x": 1})


def test_pilot_snapshot_reads_real_data_and_changes_nothing(settings, source):
    _db, mongo = source
    before = f01_snapshot.read_curated_checksum(mongo)
    ctx = RunContext.create(settings, "pilot", run_id="live")
    snap = f01_snapshot.run(ctx, mongo)
    after = f01_snapshot.read_curated_checksum(mongo)
    assert snap.counts["activities_in_scope"] > 100
    assert snap.counts["chapters_in_scope"] > 50
    assert before == snap.curated_checksum == after

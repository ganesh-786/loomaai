import pytest

from looma_pipeline.mongo_readonly import ReadOnlyCollection, ReadOnlyDatabase, ReadOnlyViolation


class FakeCollection:
    """Stands in for a pymongo Collection and records any call, so a test can prove writes never reach it."""

    name = "activities"

    def __init__(self):
        self.calls = []

    def find(self, *args, **kwargs):
        self.calls.append("find")
        return []

    def aggregate(self, pipeline, **kwargs):
        self.calls.append("aggregate")
        return []

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append(name)
        return method


class FakeDatabase:
    def __init__(self):
        self.collection = FakeCollection()

    def __getitem__(self, name):
        return self.collection

    def list_collection_names(self):
        return ["activities"]


@pytest.mark.parametrize("write_method", [
    "insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one", "delete_many",
    "bulk_write", "find_one_and_update", "find_one_and_replace", "find_one_and_delete", "drop", "create_index",
    "rename",
])
def test_write_methods_are_rejected_before_reaching_mongo(write_method):
    fake = FakeCollection()
    collection = ReadOnlyCollection(fake)
    with pytest.raises(ReadOnlyViolation):
        getattr(collection, write_method)({})
    assert fake.calls == []


def test_reads_pass_through():
    fake = FakeCollection()
    ReadOnlyCollection(fake).find({})
    assert fake.calls == ["find"]


@pytest.mark.parametrize("stage", [{"$out": "copy"}, {"$merge": {"into": "copy"}}])
def test_aggregations_that_write_are_rejected(stage):
    fake = FakeCollection()
    with pytest.raises(ReadOnlyViolation):
        ReadOnlyCollection(fake).aggregate([{"$match": {}}, stage])
    assert fake.calls == []


def test_reading_aggregation_is_allowed():
    fake = FakeCollection()
    ReadOnlyCollection(fake).aggregate([{"$match": {"ft": "video"}}, {"$count": "n"}])
    assert fake.calls == ["aggregate"]


@pytest.mark.parametrize("db_method", ["drop_collection", "create_collection", "command"])
def test_database_level_writes_are_rejected(db_method):
    db = ReadOnlyDatabase(FakeDatabase())
    with pytest.raises(ReadOnlyViolation):
        getattr(db, db_method)("activities")


def test_database_hands_out_read_only_collections():
    db = ReadOnlyDatabase(FakeDatabase())
    assert isinstance(db.collection("activities"), ReadOnlyCollection)
    assert db.list_collection_names() == ["activities"]

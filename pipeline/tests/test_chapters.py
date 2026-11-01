import pytest

from looma_pipeline.chapters import chapter_grade, chapter_prefix, is_chapter_id, normalize_ch_ids


@pytest.mark.parametrize("value, grade, prefix", [
    ("6S01.02", 6, "6S"), ("10SS03", 10, "10SS"), ("12CS01", 12, "12CS"), ("1EN09.95", 1, "1EN"),
    ("5SSa02", 5, "5SSa"), ("9Ma04.01", 9, "9Ma"),
])
def test_valid_chapter_ids_give_grade_and_prefix(value, grade, prefix):
    assert is_chapter_id(value)
    assert chapter_grade(value) == grade
    assert chapter_prefix(value) == prefix


@pytest.mark.parametrize("value", ["", "13S01", "6X01", "6S1", "6S01.2", "S01", " 6S01"])
def test_invalid_chapter_ids_are_rejected(value):
    assert not is_chapter_id(value)
    assert chapter_grade(value) is None


def test_normalize_accepts_every_shape_looma_uses():
    ids, invalid = normalize_ch_ids("6S01.02", ["5S01", " 6SS02 ", ""], [{"S": "6S04.01"}], None, ["bad id"])
    assert ids == ("5S01", "6S01.02", "6S04.01", "6SS02")
    assert invalid == 1


def test_normalize_deduplicates():
    ids, invalid = normalize_ch_ids(["6S01", "6S01"], "6S01")
    assert ids == ("6S01",)
    assert invalid == 0

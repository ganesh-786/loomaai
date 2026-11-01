import pytest

from looma_pipeline.grades import GradeBand, band_from_chapters, band_from_pair, choose_band, parse_grade


@pytest.mark.parametrize("raw, grade", [
    (6, 6), ("6", 6), (7.0, 7), (" 12 ", 12),
    (0, None), (13, None), (6.5, None), ("six", None), ("", None), (None, None), (True, None),
])
def test_parse_grade_accepts_looma_storage_types(raw, grade):
    assert parse_grade(raw) == grade


def test_pair_needs_both_ends_in_order():
    assert band_from_pair("6", 7.0, "curated") == GradeBand(6, 7, "curated")
    assert band_from_pair(8, 6, "curated") is None
    assert band_from_pair(6, None, "curated") is None
    assert band_from_pair(0, 0, "game") is None  # 0 means "not set"


def test_band_from_linked_chapters_spans_their_grades():
    assert band_from_chapters(["6S01.02", "5S01", "bad"]) == GradeBand(5, 6, "chapter")
    assert band_from_chapters(["bad"]) is None


def test_precedence_curated_then_chapter_then_game():
    curated, chapter, game = GradeBand(3, 4, "curated"), GradeBand(6, 6, "chapter"), GradeBand(1, 2, "game")
    assert choose_band(curated, chapter, game) is curated
    assert choose_band(None, chapter, game) is chapter
    assert choose_band(None, None, game) is game
    assert choose_band(None, None, None).source == "unknown"

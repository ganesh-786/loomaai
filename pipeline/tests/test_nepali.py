import pytest

from looma_pipeline.models import TextPiece
from looma_pipeline.stages.f05_nepali import check_pieces
from looma_pipeline.text.preeti import PreetiConverter, english_word_share


@pytest.fixture(scope="module")
def converter():
    return PreetiConverter()


@pytest.mark.parametrize("preeti, unicode_text", [("g]kfn", "नेपाल"), ("gfk / PsfO", "नाप र एकाइ")])
def test_preeti_text_becomes_unicode(converter, preeti, unicode_text):
    assert converter.to_unicode(preeti) == unicode_text
    assert converter.should_convert(preeti) == (True, unicode_text)


def test_english_is_never_converted(converter):
    english = "Mass is measured in kilograms and length in metres."
    assert english_word_share(english) >= 0.15
    assert converter.should_convert(english) == (False, english)


def test_text_that_is_already_devanagari_is_left_alone(converter):
    assert converter.should_convert("नाप र एकाइ") == (False, "नाप र एकाइ")


def test_only_nepali_pdf_pages_are_converted(converter):
    pieces = [
        TextPiece("t", "textbook", 12, "gfk / PsfO", lang="en", page=12, expect_nepali=True),
        TextPiece("l", "lesson", 0, "Mass is measured in kilograms.", lang="en", expect_nepali=True),
        TextPiece("n", "title", 1, "g]kfn", lang="en", expect_nepali=True),  # a DB field: count, don't convert
        TextPiece("e", "textbook", 8, "Length is measured in metres.", lang="en", page=8),
    ]
    checked, counts, examples = check_pieces(pieces, converter)
    assert checked[0].text == "नाप र एकाइ" and checked[0].lang == "np" and checked[0].page == 12
    assert checked[1].text == "Mass is measured in kilograms."
    assert checked[2].text == "g]kfn"
    assert checked[3] == pieces[3]
    assert counts["converted_from_preeti"] == 1
    assert counts["not_devanagari_lesson"] == 1 and counts["not_devanagari_title"] == 1
    assert {e["item_id"] for e in examples} == {"l", "n"}

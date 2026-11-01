import pytest

from looma_pipeline.text.normalize import html_to_text, normalize_text, strip_data_uris
from looma_pipeline.text.script import devanagari_share, language_of


def test_nfc_and_zero_width_characters_make_nepali_words_equal():
    typed_with_joiner = "क्\u200dष"
    assert normalize_text("\ufeffनाप\u200b") == "नाप"
    assert normalize_text(typed_with_joiner) == "क्ष"


def test_whitespace_is_collapsed_but_paragraphs_survive():
    assert normalize_text("  a \t b \u00a0c\n\n\n\nd ") == "a b c\n\nd"


def test_data_uris_are_removed_before_text_extraction():
    html = '<p>Length</p><img src="data:image/png;base64,AAAABBBB==">'
    assert "base64" not in strip_data_uris(html)
    assert html_to_text(html) == "Length"


def test_html_to_text_drops_scripts_and_navigation():
    html = "<nav>Menu</nav><h1>Plants</h1><script>x()</script><p>Leaves make food.</p><footer>c</footer>"
    assert html_to_text(html) == "Plants\nLeaves make food."


@pytest.mark.parametrize("text, lang", [
    ("Measurement and unit", "en"),
    ("नाप र एकाइ", "np"),
    ("Photosynthesis प्रकाश संश्लेषण हो", "mixed"),
    ("12345 !!!", "none"),
])
def test_language_is_decided_by_script(text, lang):
    assert language_of(text) == lang


def test_vowel_signs_count_as_devanagari_letters():
    assert devanagari_share("नाप") == 1.0

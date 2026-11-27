"""Tests for text/markers.py: turning page-transcript markers into plain searchable text (issue #3).

Pure functions; no files, MongoDB, model or network. The marker forms are the ones run D uses (its report.json,
"conventions"). The sample lines are made up in the same form, not copied from a textbook.
"""

from looma_pipeline.text.markers import clean_markers


def test_text_without_markers_is_unchanged():
    result = clean_markers("Cells divide by mitosis.\nEach cell has 46 (2×23) chromosomes.")
    assert result.text == "Cells divide by mitosis.\nEach cell has 46 (2×23) chromosomes."
    assert not result.counts and not result.unknown


def test_a_figure_caption_keeps_its_label_and_words():
    result = clean_markers("[Figure 4.6: Structure of a leaf]")
    assert result.text == "Figure 4.6: Structure of a leaf"
    assert result.counts["figure_caption"] == 1


def test_words_inside_figures_callouts_and_screenshots_lose_only_the_tag():
    result = clean_markers("[Figure text: root; stem; leaf]\n[Callouts: MIX colours; OBSERVE]\n"
                           "[Screenshot text: Toolbox; Reset]")
    assert result.text == "root; stem; leaf\nMIX colours; OBSERVE\nToolbox; Reset"
    assert (result.counts["figure_text"], result.counts["callouts"], result.counts["screenshot_text"]) == (1, 1, 1)


def test_a_cut_off_label_keeps_its_visible_letters_even_inside_figure_text():
    result = clean_markers("[Figure text: petal; sepa[cut off]; stamen]")
    assert result.text == "petal; sepa; stamen"
    assert result.counts["cut_off"] == 1 and result.counts["figure_text"] == 1


def test_blanks_and_illegible_words_are_removed_without_leaving_double_spaces():
    result = clean_markers("Seed → [blank] growth → plant\nThe [illegible] was green.")
    assert result.text == "Seed → growth → plant\nThe was green."
    assert result.counts["blank"] == 1 and result.counts["illegible"] == 1


def test_a_table_loses_its_tags_and_empty_cells():
    result = clean_markers("Compare them.\n[Table]\nPart | Plant | Animal\nWall | yes | \nCell |  | \n"
                           "[End table]\nNext.")
    assert result.text == "Compare them.\nPart; Plant; Animal\nWall; yes\nCell\nNext."
    assert result.counts["table"] == 1


def test_pipes_outside_a_table_are_left_alone():
    assert clean_markers("Use a | b as a separator.").text == "Use a | b as a separator."


def test_a_table_without_an_end_tag_is_cleaned_to_the_end_and_reported():
    result = clean_markers("[Table]\nPart | Use\nRoot | water")
    assert result.text == "Part; Use\nRoot; water"
    assert result.counts["table_unclosed"] == 1


def test_a_concept_map_loses_its_tags_and_keeps_its_arrows():
    result = clean_markers("[Concept map]\nA: Seed → [blank] → plant\n[End concept map]")
    assert result.text == "A: Seed → → plant"
    assert result.counts["concept_map"] == 1 and result.counts["blank"] == 1


def test_an_unknown_bracket_is_kept_counted_and_shown():
    result = clean_markers("Acids give [H+] ions.")
    assert result.text == "Acids give [H+] ions."
    assert result.counts["unknown"] == 1 and result.unknown == ["[H+]"]


def test_no_known_tag_survives_a_mixed_page():
    page = ("4 Plants\n[Figure text: root; ste[cut off]]\n[Figure 4.1: Parts of a plant]\n[Table]\nA | B\n"
            "[End table]\n[Concept map]\nX → [blank]\n[End concept map]")
    text = clean_markers(page).text
    assert "[" not in text and "]" not in text

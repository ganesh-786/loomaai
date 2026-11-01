import random
import sqlite3

import pytest

from looma_pipeline.spelling import (MAX_DISTANCE, PREFIX_CHARS, SpellCheck, Speller, build_spelling_tables,
                                     deletes, edit_distance, is_word)
from looma_pipeline.word_index import FTS_TOKENIZER

# Proportions follow the real index: "make" appears with "plan" about as often as with "plant", "food" mostly with
# "plant", and "plant" is the more frequent word. "budhi" is more frequent than "buddha" but never next to "gautam".
CORPUS = [
    "Plants make their own food using sunlight",
    "A plant needs water and light to make food",
    "Green plant leaves make food by photosynthesis",
    "The plant grows tall",
    "Every plant needs sunlight",
    "Plant cells have walls",
    "Food from plants and animals",
    "Make a plan for the week",
    "Make a plan to save water",
    "We make a plan for the trip",
    "The five year plan of Nepal",
    "Photosynthesis in green plants",
    "Photosynthesis and respiration",
    "Photosyntesis and digestion",
    "Gautam Buddha was born in Lumbini",
    "Buddha statue in Lumbini",
    "Budhi Gandaki river",
    "Budhi Gandaki valley",
    "Budhi Gandaki dam",
    "Bhimsen Thapa was a prime minister of Nepal",
    "Environment pollution in Kathmandu",
    "Nutrition and healthy food",
    "पानीको चक्र",
    "पानीको स्रोत र पानीको प्रयोग",
    "Old Nepal 00094",
]


def _db(corpus=CORPUS, dictionary=(("volcano", "ज्वालामुखी"),), spelling=True):
    db = sqlite3.connect(":memory:")
    db.executescript(f"""
        CREATE VIRTUAL TABLE passages_fts USING fts5 (title, body, content='', tokenize="{FTS_TOKENIZER}");
        CREATE TABLE dictionary (en TEXT NOT NULL, np TEXT NOT NULL);
    """)
    db.executemany("INSERT INTO passages_fts (rowid, title, body) VALUES (?, '', ?)", list(enumerate(corpus)))
    db.executemany("INSERT INTO dictionary VALUES (?, ?)", dictionary)
    if spelling:
        build_spelling_tables(db)
    return db


@pytest.fixture
def speller():
    return Speller(_db())


def _changes(check):
    return [(c.original, c.replacement) for c in check.changes]


def test_edit_distance_counts_a_neighbour_swap_as_one_edit():
    assert edit_distance("plan", "plant") == 1
    assert edit_distance("nutritoin", "nutrition") == 1
    assert edit_distance("fotosynthesis", "photosynthesis") == 2
    assert edit_distance("same", "same") == 0
    assert edit_distance("पनीको", "पानीको") == 1


def test_deletes_use_the_prefix_only():
    assert deletes("photosynthesis", 0) == {"photosy"}
    assert {"hotosy", "potosy", "photos"} <= deletes("photosynthesis", 1)
    assert all(len(key) >= PREFIX_CHARS - MAX_DISTANCE for key in deletes("photosynthesis"))


def test_only_words_with_letters_and_no_digits_get_spelling_help():
    assert is_word("plant") and is_word("पानीको")
    assert not is_word("pla") and not is_word("00094") and not is_word("covid19")


def test_symmetric_delete_lookup_finds_exactly_the_words_a_full_scan_finds(speller):
    """The 7-character prefix trick must not miss any word within the edit limit."""
    vocabulary = [w for (w,) in speller.db.execute("SELECT word FROM spell_words")]
    rng = random.Random(7)
    probes = vocabulary + ["".join(rng.sample(w, len(w))) for w in vocabulary] + \
        [w[:i] + "x" + w[i + 1:] for w in vocabulary for i in (0, len(w) // 2, len(w) - 1)]
    for probe in probes:
        for limit in (1, 2):
            expected = {w for w in vocabulary if w != probe and edit_distance(probe, w) <= limit}
            assert {w for w, _d, _df in speller.candidates(probe, limit)} == expected, (probe, limit)


def test_unknown_words_are_corrected_to_the_nearest_index_word(speller):
    assert speller.check("nutritoin").corrected == "nutrition"
    assert speller.check("fotosynthesis").corrected == "photosynthesis"      # 2 edits: long word
    assert speller.check("enviroment pollution").corrected == "environment pollution"
    assert _changes(speller.check("plnt")) == [("plnt", "plant")]


def test_corrections_keep_the_case_the_word_was_typed_in(speller):
    """The meaning model is case-sensitive: "Dablam" and "dablam" are different inputs to it."""
    assert speller.check("Enviroment pollution").corrected == "Environment pollution"
    assert speller.check("NUTRITOIN facts").corrected == "NUTRITION facts"


def test_other_query_words_break_ties_between_equally_near_words(speller):
    assert speller.check("budha").corrected == "budhi"                  # alone: the more frequent word
    assert speller.check("gautam budha").corrected == "gautam buddha"   # next to "gautam": the word seen with it


def test_real_words_typed_by_mistake_are_left_alone(speller):
    """Known limitation, measured: corpus co-occurrence cannot tell "plan" from "plant" without also changing
    correct queries such as "five year plan" (docs/experiments/2026-11-01-typo-tolerance.md)."""
    assert speller.check("How does plan make food?").changes == ()


def test_correct_queries_are_left_alone(speller):
    for query in ("plan", "five year plan", "make a plan", "plant food", "how do plants make food",
                  "photosynthesis", "Bhimsen Thapa", "old nepal 00094", "पानीको चक्र"):
        assert speller.check(query).changes == (), query


def test_numbers_short_words_and_dictionary_words_are_never_changed(speller):
    assert speller.check("old nepal 00095").changes == ()
    assert speller.check("pln").changes == ()
    assert speller.check("volcano").changes == ()   # a real word Looma has no passage for


def test_devanagari_typos_are_corrected(speller):
    assert speller.check("पनीको चक्र").corrected == "पानीको चक्र"


def test_bundles_without_spelling_tables_get_no_spelling_help():
    speller = Speller(_db(spelling=False))
    assert not speller.available
    assert speller.check("nutritoin") == SpellCheck("nutritoin")


def test_two_builds_write_the_same_spelling_tables():
    a, b = _db(), _db(list(reversed(CORPUS)))
    for table in ("spell_words", "spell_deletes"):
        rows = [db.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall() for db in (a, b)]
        assert rows[0] == rows[1], table

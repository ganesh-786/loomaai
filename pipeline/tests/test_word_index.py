import re
import sqlite3

import pytest

from looma_pipeline.config import Settings
from looma_pipeline.models import Item, Passage
from looma_pipeline.query_terms import expand, match_expression, query_terms
from looma_pipeline.text.normalize import html_to_text
from looma_pipeline.word_index import FTS_TOKENIZER, build_word_index

NEPALI_DOCS = ["पानी पिउनुहोस्", "पाना पल्टाउनुहोस्", "पानीमा माछा बस्छ", "नयाँ पुस्तक"]


def _fts(tokenizer):
    db = sqlite3.connect(":memory:")
    db.execute(f'CREATE VIRTUAL TABLE t USING fts5(body, tokenize="{tokenizer}")')
    db.executemany("INSERT INTO t (body) VALUES (?)", [(d,) for d in NEPALI_DOCS])
    return db


def _hits(db, expression):
    return sorted(row[0] for row in db.execute("SELECT body FROM t WHERE t MATCH ?", (expression,)))


def test_default_tokenizer_splits_nepali_words_at_vowel_signs():
    """The 2026-10-28 finding: the default tokenizer matches unrelated words."""
    assert "पाना पल्टाउनुहोस्" in _hits(_fts("unicode61"), '"पानी"')  # पाना (page) is not पानी (water)


def test_project_tokenizer_keeps_whole_words_and_prefix_absorbs_postpositions():
    db = _fts(FTS_TOKENIZER)
    assert _hits(db, '"पानी"') == ["पानी पिउनुहोस्"]
    assert _hits(db, '"पानी" *') == ["पानी पिउनुहोस्", "पानीमा माछा बस्छ"]


def test_query_terms_drop_stop_words_and_are_quoted_safely():
    assert query_terms("How do plants make food?") == ["plants", "make", "food"]
    assert query_terms("नाप र एकाइ") == ["नाप", "एकाइ"]
    assert match_expression(['x" OR body:*']) == '"x"" OR body:*" *'  # quote doubled: stays one string
    assert match_expression([]) is None
    assert match_expression(["नाप", "e"]) == '"नाप" * OR "e"'


def _index(tmp_path):
    items = {"a": Item("a", "chapter", "Measurement and unit", "नाप र एकाइ", "Science", ("Science",), ("6S01.02",),
                       "6S01.02", 6, 6, "chapter", "", "both", False, None),
             "b": Item("b", "video", "Photosynthesis", "", "Science", ("Science",), ("5S01",), None, 5, 6,
                       "curated", "khan", "en", False, None)}
    passages = [Passage("a:en:0", "a", "en", "title", "Measurement and unit", None, None, 3),
                Passage("a:np:0", "a", "np", "title", "नाप र एकाइ", None, None, 3),
                Passage("b:en:0", "b", "en", "title", "Photosynthesis (Science)", None, None, 3)]
    path = tmp_path / "chunks.db"
    counts = build_word_index(path, items, passages, [("measurement", "नाप"), ("unit", "एकाइ"),
                                                      ("a very long english sentence here", "लामो")], {"k": "v"})
    return path, counts


def test_index_rows_line_up_with_vector_rows(tmp_path):
    path, counts = _index(tmp_path)
    assert counts == {"items": 2, "passages": 3, "dictionary_pairs": 2, "item_chapter_links": 2}
    db = sqlite3.connect(path)
    assert [r[0] for r in db.execute("SELECT passage_id FROM passages ORDER BY vrow")] == ["a:en:0", "a:np:0", "b:en:0"]
    rows = [r[0] for r in db.execute("SELECT rowid FROM passages_fts WHERE passages_fts MATCH ?", ('"photosynthesis" *',))]
    assert rows == [2]


def test_dictionary_expansion_crosses_languages(tmp_path):
    path, _ = _index(tmp_path)
    db = sqlite3.connect(path)
    assert expand(["measurement"], db) == ["measurement", "नाप"]
    assert expand(["एकाइ"], db) == ["एकाइ", "unit"]
    hits = {r[0] for r in db.execute("SELECT rowid FROM passages_fts WHERE passages_fts MATCH ?",
                                     (match_expression(expand(["measurement"], db)),))}
    assert hits == {0, 1}  # the Nepali passage is found from an English word


@pytest.mark.mongo
def test_real_lesson_slides_prefix_matches_are_all_true_hits():
    """Regression on real data: every FTS hit for पानी* really contains a word starting with पानी."""
    from looma_pipeline.mongo_readonly import connect_readonly

    live = Settings.from_env()
    try:
        source = connect_readonly(live.mongo_uri, live.mongo_db, timeout_ms=3000)
    except Exception as exc:  # no local database: skip, don't fail
        pytest.skip(f"looma-db not reachable: {type(exc).__name__}")
    texts = [html_to_text(slide.get("nepali")) for lesson in source.collection("lessons").find({}, {"data": 1})
             for slide in lesson.get("data") or [] if isinstance(slide, dict) and slide.get("ft") == "inline"]
    db = sqlite3.connect(":memory:")
    db.execute(f'CREATE VIRTUAL TABLE t USING fts5(body, tokenize="{FTS_TOKENIZER}")')
    db.executemany("INSERT INTO t (body) VALUES (?)", [(t,) for t in texts if t])
    hits = [row[0] for row in db.execute("SELECT body FROM t WHERE t MATCH ?", ('"पानी" *',))]
    words = re.compile(r"[\wऀ-ॿ]+")
    assert len(hits) > 100
    assert all(any(word.startswith("पानी") for word in words.findall(hit)) for hit in hits)

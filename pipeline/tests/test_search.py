import json

import looma_fixture as fx
import numpy as np
import pytest
from fake_embedder import FakeEmbedder

from looma_pipeline.chunking import WhitespaceCounter
from looma_pipeline.pipeline import run_build
from looma_pipeline.query_terms import expand, match_expression, query_terms
from looma_pipeline.search import DEFAULT_DEPTH, Filters, SearchEngine
from looma_pipeline.source import DictSource

FILTER_CASES = {
    "default": Filters(),
    "cehrd-server": Filters(cehrd_server=True),
    "grade-5": Filters(grade=5),
    "grade-6-known-only": Filters(grade=6, include_unknown_grade=False),
    "chapter": Filters(chapter_id="6SS02"),
    "videos": Filters(types=frozenset({"video"})),
}
QUERIES = ["Measurement and unit", "नाप र एकाइ", "photosynthesis",
           "family village tools", "unit"]


@pytest.fixture
def engine(settings):
    result = run_build(settings, "pilot", source=DictSource(fx.looma_data()), until="f08",
                       counter=WhitespaceCounter(), embedder=FakeEmbedder())
    engine = SearchEngine(result.run_dir / "staging", FakeEmbedder())
    yield engine
    engine.close()


def _ids(hits):
    return [h.item_id for h in hits]


def _restricted_inside_sql(engine, query, filters, depth):
    """The earlier word search, which sent the allowed passages to SQLite. Kept here as the reference."""
    rows = np.flatnonzero(engine.item_mask(filters)[engine.row_item])
    expression = match_expression(expand(query_terms(query), engine.db))
    if expression is None or len(rows) == 0:
        return []
    sql = ("SELECT rowid FROM passages_fts WHERE passages_fts MATCH ? AND rowid IN (SELECT value FROM json_each(?)) "
           "ORDER BY rank, rowid LIMIT ?")
    return [row[0] for row in engine.db.execute(sql, (expression, json.dumps([int(r) for r in rows]), depth))]


@pytest.mark.parametrize("case", FILTER_CASES)
def test_word_search_returns_what_restricting_inside_sql_returned(engine, case):
    filters = FILTER_CASES[case]
    allowed = engine.item_mask(filters)[engine.row_item]
    compared_nonempty = 0
    for query in QUERIES:
        for depth in (1, 3, DEFAULT_DEPTH):
            expected = _restricted_inside_sql(engine, query, filters, depth)
            assert engine._lexical(query, allowed, depth) == expected, (query, depth)
            compared_nonempty += bool(expected)
    assert compared_nonempty, "every comparison was empty, so this case proved nothing"


@pytest.mark.parametrize("case", FILTER_CASES)
def test_meaning_scores_equal_scoring_only_the_allowed_passages(engine, case):
    allowed = engine.item_mask(FILTER_CASES[case])[engine.row_item]
    rows = np.flatnonzero(allowed)
    vector = engine.embedder.embed_queries(["Measurement and unit"])[0]
    _top, similarity = engine._dense("Measurement and unit", rows, DEFAULT_DEPTH)
    np.testing.assert_allclose(similarity[rows], engine.vectors[rows] @ vector, rtol=0, atol=1e-6)
    assert np.isnan(similarity[~allowed]).all()


def test_filtered_search_does_not_send_the_allowed_passages_to_sqlite(engine):
    """Regression: with the allowed rows in SQL (json_each), SQLite re-ran the match once per allowed row,
    about 6 s per query at 40,000 passages. The statements must not depend on the filter."""
    engine.search("Measurement and unit")  # FTS5 reads its config on a connection's first query; not counted
    statements = []
    engine.db.set_trace_callback(statements.append)
    try:
        engine.search("Measurement and unit", Filters())
        broad = len(statements)
        engine.search("Measurement and unit", Filters(chapter_id="6SS02"))
        narrow = len(statements) - broad
    finally:
        engine.db.set_trace_callback(None)
    assert broad == narrow
    assert not [s for s in statements if "json_each" in s]


def test_exact_title_ranks_its_item_first(engine):
    assert _ids(engine.search("Measurement and unit"))[0] == fx.A_CH_6S0102


def test_nepali_title_is_found(engine):
    assert fx.A_CH_6S0102 in _ids(engine.search("नाप र एकाइ"))


def test_dictionary_lets_an_english_word_find_nepali_text(engine):
    hits = engine.search("unit", Filters(types=frozenset({"chapter"})))
    assert fx.A_CH_6S0102 in _ids(hits)


def test_cehrd_items_only_appear_on_the_cehrd_server(engine):
    assert fx.A_HTML_CEHRD not in _ids(engine.search("Community helpers"))
    assert fx.A_HTML_CEHRD in _ids(engine.search("Community helpers", Filters(cehrd_server=True)))


def test_chapter_filter_returns_only_that_chapters_items(engine):
    hits = engine.search("family village tools", Filters(chapter_id="6SS02"))
    assert hits and set(_ids(hits)) <= {fx.A_PDF_TOOLS, fx.A_IMG_FAMILY, fx.A_IMG_NEPALI}


def test_filters_apply_before_the_cut(engine):
    """Even keeping just one passage per list, a narrow filter still returns its own best match."""
    hits = engine.search("Photosynthesis", Filters(chapter_id="6SS02"), depth=1)
    assert len(hits) == 1 and hits[0].item_id in {fx.A_PDF_TOOLS, fx.A_IMG_FAMILY, fx.A_IMG_NEPALI}


def test_grade_and_type_filters(engine):
    grade5 = _ids(engine.search("video units photosynthesis", Filters(grade=5)))
    assert fx.A_VID_PHOTO in grade5 and fx.A_VID_UNITS not in grade5
    videos = engine.search("measurement photosynthesis", Filters(types=frozenset({"video"})))
    assert videos and all(h.ft == "video" for h in videos)


def test_grade_window_keeps_bands_that_overlap_it(engine):
    """Chapter search looks at the chapter's grade plus or minus a window; the units video is curated 6-7."""
    exact = _ids(engine.search("units", Filters(grade=5, include_unknown_grade=False)))
    window = _ids(engine.search("units", Filters(grade=5, grade_window=1, include_unknown_grade=False)))
    assert fx.A_VID_UNITS not in exact and fx.A_VID_UNITS in window


def test_subject_filter_accepts_several_subjects(engine):
    science = _ids(engine.search("measuring tools units", Filters(subjects=frozenset({"Science"}))))
    either = _ids(engine.search("measuring tools units", Filters(subjects=frozenset({"science", "Language"}))))
    assert fx.A_VID_UNITS in science and fx.A_PDF_TOOLS not in science
    assert {fx.A_VID_UNITS, fx.A_PDF_TOOLS} <= set(either)


def test_hits_carry_their_best_passage(engine):
    hit = engine.search("Length is measured in metres")[0]
    assert hit.item_id == fx.A_LESSON and "metres" in hit.passage and hit.passage_id.startswith(fx.A_LESSON)


def test_results_are_deterministic_and_empty_queries_return_nothing(engine):
    assert _ids(engine.search("measuring")) == _ids(engine.search("measuring"))
    assert engine.search("   ") == []


def test_a_bundle_and_embedder_of_different_sizes_are_refused(settings, engine):
    with pytest.raises(ValueError, match="dims"):
        SearchEngine(engine.bundle_dir, FakeEmbedder(dims=32))


def test_an_unknown_word_is_corrected_and_its_item_found(engine):
    result = engine.respond("Mesurement and unit")
    assert result.spelling.corrected == "Measurement and unit"
    assert _ids(result.hits)[0] == fx.A_CH_6S0102
    assert engine.respond("Mesurement and unit", spelling=False).spelling.changes == ()


def test_a_corrected_search_also_looks_for_the_words_as_typed(engine, monkeypatch):
    """The meaning search gets the corrected query; the word search gets both wordings."""
    seen = {}
    real_lexical = engine._lexical
    monkeypatch.setattr(engine, "_lexical", lambda q, allowed, depth, also=None:
                        seen.update(query=q, also=also) or real_lexical(q, allowed, depth, also))
    engine.respond("Mesurement and unit")
    assert seen == {"query": "Measurement and unit", "also": "Mesurement and unit"}


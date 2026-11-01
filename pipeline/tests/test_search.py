import looma_fixture as fx
import pytest
from fake_embedder import FakeEmbedder

from looma_pipeline.chunking import WhitespaceCounter
from looma_pipeline.pipeline import run_build
from looma_pipeline.search import Filters, SearchEngine
from looma_pipeline.source import DictSource


@pytest.fixture
def engine(settings):
    result = run_build(settings, "pilot", source=DictSource(fx.looma_data()), until="f08",
                       counter=WhitespaceCounter(), embedder=FakeEmbedder())
    engine = SearchEngine(result.run_dir / "staging", FakeEmbedder())
    yield engine
    engine.close()


def _ids(hits):
    return [h.item_id for h in hits]


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


def test_hits_carry_their_best_passage(engine):
    hit = engine.search("Length is measured in metres")[0]
    assert hit.item_id == fx.A_LESSON and "metres" in hit.passage and hit.passage_id.startswith(fx.A_LESSON)


def test_results_are_deterministic_and_empty_queries_return_nothing(engine):
    assert _ids(engine.search("measuring")) == _ids(engine.search("measuring"))
    assert engine.search("   ") == []


def test_a_bundle_and_embedder_of_different_sizes_are_refused(settings, engine):
    with pytest.raises(ValueError, match="dims"):
        SearchEngine(engine.bundle_dir, FakeEmbedder(dims=32))

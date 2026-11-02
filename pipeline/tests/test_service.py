"""Tests for the search service (serve plane): routes, modes, the provisional age and cutoff policy, limits, errors
and logging.

The WSGI app is called directly, so these need no network. The bundle is built from the test fixture with the fake
embedder in the "all" scope, plus one item with no grade, so every mode and the unknown-grade policy can be checked.
"""

import io
import json
import logging
from urllib.parse import urlencode

import looma_fixture as fx
import pytest
from fake_embedder import FakeEmbedder

from looma_pipeline.chunking import WhitespaceCounter
from looma_pipeline.pipeline import run_build
from looma_pipeline.search import SearchEngine
from looma_pipeline.service import Policy, SearchService, make_app
from looma_pipeline.source import DictSource

A_NO_GRADE = "a00000000000000000000099"
LINKED_TO_6S0102 = {fx.A_CH_6S0102, fx.A_VID_UNITS, fx.A_LESSON, fx.A_GAME, fx.A_PDF_TOOLS}
MANIFEST = {"bundle_name": "test-bundle", "schema_version": "1.1", "created_at": "2026-11-02T00:00:00+00:00",
            "embedding": {"repo": "fake/model", "revision": "1", "dims": 64}}


@pytest.fixture
def engine(settings):
    data = fx.looma_data()
    data["activities"].append({"_id": A_NO_GRADE, "ft": "image", "dn": "Measuring cylinder", "fn": "cylinder.jpg",
                               "key1": "Science"})
    result = run_build(settings, "all", source=DictSource(data), until="f08", counter=WhitespaceCounter(),
                       embedder=FakeEmbedder())
    engine = SearchEngine(result.run_dir / "staging", FakeEmbedder())
    yield engine
    engine.close()


def _service(engine, **policy):
    return SearchService(engine, MANIFEST, Policy(**policy))


def _call(service, path, query="", method="GET"):
    """Call the WSGI app the way a server does; returns (status code, headers, raw body)."""
    seen = {}

    def start_response(status, headers):
        seen["status"], seen["headers"] = int(status.split()[0]), dict(headers)

    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO()}
    raw = b"".join(make_app(service)(environ, start_response))
    return seen["status"], seen["headers"], raw


def _get(service, path, query="", method="GET"):
    status, headers, raw = _call(service, path, query, method)
    return status, headers, json.loads(raw)


def _search(service, **params):
    return _get(service, "/search", urlencode(params, doseq=True))


def _ids(body):
    return [result["id"] for result in body["results"]]


def test_health_reports_the_bundle_model_counts_and_policy(engine):
    status, headers, body = _get(_service(engine), "/health")
    assert status == 200 and body["status"] == "ok"
    assert body["bundle"] == "test-bundle" and body["model"] == {"repo": "fake/model", "revision": "1"}
    assert body["items"] == len(engine.item_ids) and body["passages"] == engine.vectors.shape[0]
    assert body["policy"]["grade_window"] == 1 and body["policy"]["min_similarity"] is None
    assert headers["Content-Type"] == "application/json; charset=utf-8" and headers["Cache-Control"] == "no-store"


def test_library_search_ranks_the_exact_title_first(engine):
    status, _, body = _search(_service(engine), q="Measurement and unit")
    assert status == 200 and body["mode"] == "library" and body["widened"] is False
    assert body["results"][0]["id"] == fx.A_CH_6S0102 and body["count"] == len(body["results"])
    assert set(body["results"][0]) == {"id", "ft", "title", "score", "similarity", "page", "passage"}


def test_nepali_queries_and_results_stay_readable(engine):
    status, _, raw = _call(_service(engine), "/search", urlencode({"q": "नाप र एकाइ"}))
    body = json.loads(raw)
    assert status == 200 and body["query"] == "नाप र एकाइ" and body["results"][0]["id"] == fx.A_CH_6S0102
    assert "नाप".encode() in raw  # not escaped as \\uXXXX


def test_spelling_correction_is_reported_and_can_be_turned_off(engine):
    _, _, corrected = _search(_service(engine), q="Mesurement and unit")
    _, _, exact = _search(_service(engine), q="Mesurement and unit", spelling="0")
    assert corrected["spelling"]["searched_for"] == "Measurement and unit"
    assert corrected["results"][0]["id"] == fx.A_CH_6S0102 and exact["spelling"] is None


def test_open_search_keeps_items_with_no_grade(engine):
    """Provisional policy (open question S7): open search shows items with no grade, even with a grade filter."""
    _, _, body = _search(_service(engine), q="Measuring cylinder", grade=6)
    assert A_NO_GRADE in _ids(body)


def test_chapter_mode_searches_only_the_chapters_own_resources(engine):
    _, _, body = _search(_service(engine), q="measuring units cylinder", mode="chapter", chapter="6S01.02", k=20)
    assert body["count"] and set(_ids(body)) <= LINKED_TO_6S0102 and body["chapter"] == "6S01.02"


def test_related_mode_uses_the_chapter_subject_and_grade_window(engine):
    """6S01.02 is grade 6 Science: related items are Science, grades 5 to 7, with a known grade."""
    _, _, body = _search(_service(engine), q="photosynthesis newton units measuring", mode="related",
                         chapter="6S01.02", k=20)
    ids = set(_ids(body))
    assert {fx.A_VID_PHOTO, fx.A_VID_NEWTON, fx.A_VID_UNITS} <= ids and body["widened"] is False
    assert not ids & {A_NO_GRADE, fx.A_PDF_TOOLS, fx.A_IMG_FAMILY, fx.A_HTML_CEHRD}


def test_related_mode_with_no_window_keeps_only_the_chapter_grade(engine):
    _, _, body = _search(_service(engine, grade_window=0), q="photosynthesis newton", mode="related",
                         chapter="6S01.02", k=20)
    assert fx.A_VID_PHOTO in _ids(body) and fx.A_VID_NEWTON not in _ids(body)  # photo is 5-6, Newton grade 7


def test_related_mode_widens_to_all_subjects_and_says_so(engine):
    _, _, body = _search(_service(engine, related_min_results=50), q="measuring tools", mode="related",
                         chapter="6S01.02", k=20)
    assert body["widened"] is True and fx.A_PDF_TOOLS in _ids(body) and A_NO_GRADE not in _ids(body)


def test_min_similarity_drops_weak_matches_and_can_return_nothing(engine):
    _, _, everything = _search(_service(engine), q="Measurement and unit", k=20)
    similarities = sorted({r["similarity"] for r in everything["results"]}, reverse=True)
    cutoff = (similarities[0] + similarities[1]) / 2
    _, _, strong = _search(_service(engine, min_similarity=cutoff), q="Measurement and unit", k=20)
    _, _, none = _search(_service(engine, min_similarity=1.01), q="Measurement and unit")
    assert 1 <= strong["count"] < everything["count"] and all(r["similarity"] >= cutoff for r in strong["results"])
    assert none["count"] == 0 and none["results"] == []


def test_cehrd_only_items_appear_only_on_a_cehrd_server(engine):
    _, _, normal = _search(_service(engine), q="Community helpers")
    _, _, cehrd = _search(_service(engine, cehrd_server=True), q="Community helpers")
    assert fx.A_HTML_CEHRD not in _ids(normal) and fx.A_HTML_CEHRD in _ids(cehrd)


def test_type_filter_can_repeat(engine):
    _, _, body = _search(_service(engine), q="measuring units photosynthesis", type=["video", "pdf"], k=20)
    assert body["count"] and {r["ft"] for r in body["results"]} <= {"video", "pdf"}


@pytest.mark.parametrize("params, status, message", [
    ({}, 400, "q is required"),
    ({"q": "   "}, 400, "q is required"),
    ({"q": "x" * 201}, 400, "q is longer than 200 characters"),
    ({"q": "units", "mode": "everything"}, 400, "mode must be"),
    ({"q": "units", "mode": "chapter"}, 400, "chapter is required"),
    ({"q": "units", "mode": "related", "chapter": "not-a-chapter"}, 400, "not a Looma chapter id"),
    ({"q": "units", "mode": "chapter", "chapter": "9S01"}, 404, "unknown chapter"),
    ({"q": "units", "k": "0"}, 400, "k must be"),
    ({"q": "units", "k": "51"}, 400, "k must be"),
    ({"q": "units", "k": "ten"}, 400, "k must be"),
    ({"q": "units", "grade": "13"}, 400, "grade must be"),
    ({"q": "units", "mode": "related", "chapter": "6S01.02", "grade": "6"}, 400, "grade comes from the chapter"),
    ({"q": "units", "type": "spaceship"}, 400, "unknown type"),
    ({"q": "units", "spelling": "maybe"}, 400, "spelling must be"),
    ({"q": "units", "colour": "red"}, 400, "unknown parameter"),
    ({"q": ["units", "photosynthesis"]}, 400, "q given more than once"),
])
def test_bad_requests_get_a_clear_json_error(engine, params, status, message):
    got, _, body = _search(_service(engine), **params)
    assert got == status and message in body["error"]


def test_unknown_paths_and_methods_are_refused(engine):
    service = _service(engine)
    assert _get(service, "/nothing")[0] == 404
    status, headers, body = _get(service, "/search", "q=units", method="POST")
    assert status == 405 and headers["Allow"] == "GET" and body["error"] == "method not allowed"


def test_an_internal_error_returns_json_without_details(engine, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("disk path /secret/bundle failed")

    monkeypatch.setattr(engine, "timed_respond", broken)
    status, _, body = _search(_service(engine), q="units")
    assert status == 500 and body == {"error": "internal error"}


def test_logs_record_the_query_length_never_its_text(engine, caplog):
    caplog.set_level(logging.INFO, logger="looma_pipeline.service")
    _search(_service(engine), q="my secret question")
    [record] = [r for r in caplog.records if r.getMessage() == "request"]
    assert (record.path, record.status, record.query_chars) == ("/search", 200, 18)
    assert "secret" not in json.dumps({key: str(value) for key, value in vars(record).items()})

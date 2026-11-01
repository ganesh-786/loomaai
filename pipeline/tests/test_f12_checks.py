import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import looma_fixture as fx
import pytest
from fake_embedder import FakeEmbedder

from looma_pipeline.baseline import BaselineUnavailable, today_search
from looma_pipeline.chunking import WhitespaceCounter
from looma_pipeline.pipeline import run_build
from looma_pipeline.source import DictSource
from looma_pipeline.stages import f12_checks


def _build(settings, until="f12"):
    return run_build(settings, "pilot", source=DictSource(fx.looma_data()), until=until,
                     counter=WhitespaceCounter(), embedder=FakeEmbedder())


def test_checks_pass_on_the_fixture_and_save_self_test_queries(settings):
    result = _build(settings)
    report = json.loads((result.run_dir / "f12_checks.json").read_text())
    assert report["status"] == "ok", report["details"].get("gates_failed")
    details = report["details"]
    assert details["G5_self_test"]["passed"] == details["G5_self_test"]["queries"] > 0
    assert details["G6_english"]["recall_at_10"] == 1.0
    assert details["G6_cehrd_results"]["count"] == 0
    assert details["G7_chapter_filter"]["results_outside_chapter"] == 0
    assert all("not_run" in row["today"] for row in details["G8_comparison"])  # no Looma in unit tests
    lines = (result.run_dir / "staging" / "tests" / "self_test.jsonl").read_text().splitlines()
    assert len(lines) == details["G5_self_test"]["queries"]


def test_a_failed_gate_stops_the_run(settings, monkeypatch):
    monkeypatch.setattr(f12_checks, "ENGLISH_MIN_RECALL", 1.01)  # impossible to meet
    with pytest.raises(f12_checks.ChecksFailed, match="G6_english"):
        _build(settings)


def _details(**overrides):
    details = {"G5_self_test": {"queries": 20, "passed": 20},
               "G6_english": {"queries": 200, "recall_at_10": 0.97}, "G6_nepali": {"queries": 50, "recall_at_10": 0.91},
               "G6_cehrd_results": {"count": 0},
               "G7_chapter_filter": {"nonempty_share": 0.98, "results_outside_chapter": 0}}
    details.update(overrides)
    return details


def test_gate_logic():
    assert f12_checks.gate_failures(_details()) == []
    assert f12_checks.gate_failures(_details(G5_self_test={"queries": 20, "passed": 19}))
    assert f12_checks.gate_failures(_details(G6_nepali={"queries": 50, "recall_at_10": 0.89}))
    assert f12_checks.gate_failures(_details(G6_cehrd_results={"count": 1}))
    assert f12_checks.gate_failures(_details(G7_chapter_filter={"nonempty_share": 0.94, "results_outside_chapter": 0}))
    assert f12_checks.gate_failures(_details(G7_chapter_filter={"nonempty_share": 1.0, "results_outside_chapter": 2}))
    assert f12_checks.gate_failures(_details(G6_nepali={"queries": 0, "recall_at_10": None})) == []


class _FakeLooma(BaseHTTPRequestHandler):
    reply = b'{"count": 2, "list": [{"dn": "Photosynthesis"}, {"ndn": "\\u092a\\u093e\\u0928\\u0940"}]}'

    def do_POST(self):  # noqa: N802 (http.server naming)
        length = int(self.headers["Content-Length"])
        _FakeLooma.last_body = self.rfile.read(length).decode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(self.reply)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_looma():
    server = HTTPServer(("127.0.0.1", 0), _FakeLooma)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_today_search_sends_the_form_and_reads_titles(fake_looma):
    count, titles = today_search("photosynthesis", fake_looma)
    assert count == 2 and titles == ["Photosynthesis", "पानी"]
    assert "cmd=search" in _FakeLooma.last_body and _FakeLooma.last_body.count("type%5B%5D=") == 14


def test_today_search_reports_unreachable_and_non_json(fake_looma, monkeypatch):
    with pytest.raises(BaselineUnavailable):
        today_search("x", "http://127.0.0.1:9", timeout=2)
    monkeypatch.setattr(_FakeLooma, "reply", b"<html>error</html>")
    with pytest.raises(BaselineUnavailable, match="not JSON"):
        today_search("x", fake_looma)

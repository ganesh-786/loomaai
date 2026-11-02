"""Integration tests for the search service over real HTTP: the waitress server under parallel requests, start-up
verification of the bundle, and the `serve` command as a separate process stopped the way `docker stop` stops it.

They use the fake embedder and a signed test bundle, so they need no model; they open local ports only.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import looma_fixture as fx
import pytest
from fake_embedder import FakeEmbedder
from test_service import MANIFEST, engine  # noqa: F401 (engine is a fixture used below)
from waitress.server import create_server

from looma_pipeline.chunking import WhitespaceCounter
from looma_pipeline.pipeline import run_build
from looma_pipeline.service import BundleRefused, Policy, SearchService, load_service, make_app
from looma_pipeline.source import DictSource

TESTS = Path(__file__).resolve().parent


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, json.loads(response.read())


def _ids(body):
    return [result["id"] for result in body["results"]]


def _signed_bundle(settings, fake_model_dir):
    result = run_build(settings, "pilot", source=DictSource(fx.looma_data()), counter=WhitespaceCounter(),
                       embedder=FakeEmbedder(), model_dir=fake_model_dir)
    return result.outputs["bundle"]


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_the_server_gives_parallel_requests_the_same_answers_as_one_at_a_time(engine):  # noqa: F811
    server = create_server(make_app(SearchService(engine, MANIFEST, Policy())), host="127.0.0.1", port=0, threads=4)
    threading.Thread(target=server.run, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.effective_port}/search?q="
        queries = ["Measurement and unit", "नाप र एकाइ", "photosynthesis", "Community helpers"] * 6
        expected = {query: _ids(_get(base + quote(query))[1]) for query in set(queries)}
        with ThreadPoolExecutor(max_workers=8) as pool:
            answers = list(pool.map(lambda query: (query, _get(base + quote(query))), queries))
        assert all(status == 200 and _ids(body) == expected[query] for query, (status, body) in answers)
    finally:
        server.close()


def test_a_changed_bundle_is_refused_and_a_good_one_is_served(settings, fake_model_dir, tmp_path):
    bundle = _signed_bundle(settings, fake_model_dir)
    service = load_service(bundle, settings, Policy(), embedder=FakeEmbedder())
    assert service.health()["bundle"] == bundle.name and service.health()["items"] > 0
    service.engine.close()

    changed = shutil.copytree(bundle, tmp_path / "changed")
    database = changed / "meta" / "chunks.db"
    data = bytearray(database.read_bytes())
    data[200] ^= 1
    database.write_bytes(bytes(data))
    with pytest.raises(BundleRefused, match="checksums"):
        load_service(changed, settings, Policy(), embedder=FakeEmbedder())


def test_the_serve_command_verifies_answers_and_stops_on_sigterm(settings, fake_model_dir):
    """Runs `python -m looma_pipeline serve <bundle>` in its own process (with the fake embedder swapped in), waits
    for /health, then sends SIGTERM as `docker stop` does: the process must exit at once with 143."""
    bundle = _signed_bundle(settings, fake_model_dir)
    port = _free_port()
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(TESTS)!r})\n"
        "from fake_embedder import FakeEmbedder\n"
        "import looma_pipeline.service as service\n"
        "real_load = service.load_service\n"
        "service.load_service = lambda *args: real_load(*args, embedder=FakeEmbedder())\n"
        "from looma_pipeline.cli import main\n"
        f"sys.exit(main(['serve', {str(bundle)!r}]))\n")
    env = {**os.environ, "PIPELINE_DATA_DIR": str(settings.data_dir), "PIPELINE_CONTENT_DIR": str(settings.content_dir),
           "SEARCH_HOST": "127.0.0.1", "SEARCH_PORT": str(port)}
    process = subprocess.Popen([sys.executable, "-c", script], env=env, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 30
        while True:
            assert process.poll() is None, process.stderr.read()
            try:
                status, health = _get(f"http://127.0.0.1:{port}/health")
                break
            except (urllib.error.URLError, ConnectionError):
                assert time.monotonic() < deadline, "the service did not start within 30 s"
                time.sleep(0.2)
        assert status == 200 and health["bundle"] == bundle.name
        assert _get(f"http://127.0.0.1:{port}/search?q=units")[0] == 200
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=10) == 128 + signal.SIGTERM
    finally:
        if process.poll() is None:
            process.kill()
    logs = process.stderr.read()
    assert '"msg": "serving"' in logs and '"query_chars": 5' in logs and "units" not in logs.replace("/search", "")

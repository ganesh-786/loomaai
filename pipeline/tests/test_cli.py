import json
import shutil
import signal

import looma_fixture as fx
import pytest
from fake_embedder import FakeEmbedder

from looma_pipeline import __version__, cli, service
from looma_pipeline.chunking import WhitespaceCounter
from looma_pipeline.pipeline import run_build
from looma_pipeline.source import DictSource


def _use(monkeypatch, settings):
    """Point the command line at the same folders as the `settings` fixture."""
    monkeypatch.setenv("PIPELINE_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("PIPELINE_CONTENT_DIR", str(settings.content_dir))


def _signed_bundle(settings, fake_model_dir):
    return run_build(settings, "pilot", source=DictSource(fx.looma_data()), counter=WhitespaceCounter(),
                     embedder=FakeEmbedder(), model_dir=fake_model_dir).outputs["bundle"]


def _changed_copy(bundle, folder):
    changed = shutil.copytree(bundle, folder)
    database = changed / "meta" / "chunks.db"
    data = bytearray(database.read_bytes())
    data[200] ^= 1
    database.write_bytes(bytes(data))
    return changed


def test_sigterm_becomes_system_exit_143():
    with pytest.raises(SystemExit) as stopped:
        cli.stop_on_sigterm(signal.SIGTERM, None)
    assert stopped.value.code == 143


def test_main_installs_the_sigterm_handler(monkeypatch, tmp_path):
    installed = {}
    monkeypatch.setattr(cli.signal, "signal", lambda signum, handler: installed.update({signum: handler}))
    monkeypatch.setenv("PIPELINE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PIPELINE_CONTENT_DIR", str(tmp_path))
    assert cli.main(["info"]) == 0
    assert installed[signal.SIGTERM] is cli.stop_on_sigterm


def test_info_prints_the_effective_settings(monkeypatch, settings, capsys):
    _use(monkeypatch, settings)
    assert cli.main(["info"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["version"] == __version__


def test_keygen_creates_the_key_pair_once(monkeypatch, settings, capsys):
    _use(monkeypatch, settings)
    assert cli.main(["keygen"]) == 0
    first = capsys.readouterr().out
    assert cli.main(["keygen"]) == 0
    assert capsys.readouterr().out == first and settings.signing_pubkey_path.exists()


def test_verify_accepts_a_signed_bundle_and_refuses_a_changed_one(monkeypatch, settings, fake_model_dir, tmp_path):
    bundle = _signed_bundle(settings, fake_model_dir)
    _use(monkeypatch, settings)
    assert cli.main(["verify", str(bundle), "--no-self-test"]) == 0
    assert cli.main(["verify", str(_changed_copy(bundle, tmp_path / "changed")), "--no-self-test"]) == 1


def test_clean_deletes_nothing_without_apply(monkeypatch, settings, fake_model_dir, capsys):
    for _ in range(3):
        _signed_bundle(settings, fake_model_dir)
    _use(monkeypatch, settings)
    before = sorted(path.name for path in settings.bundles_dir.iterdir())
    assert cli.main(["clean", "--keep", "1"]) == 0
    assert "Dry run: nothing deleted" in capsys.readouterr().out
    assert sorted(path.name for path in settings.bundles_dir.iterdir()) == before


def test_serve_returns_2_for_a_bad_setting_or_a_refused_bundle(monkeypatch, settings, fake_model_dir, tmp_path):
    bundle = _signed_bundle(settings, fake_model_dir)
    _use(monkeypatch, settings)
    monkeypatch.setenv("SEARCH_MIN_SIMILARITY", "high")
    assert cli.main(["serve", str(bundle)]) == 2
    monkeypatch.delenv("SEARCH_MIN_SIMILARITY")
    assert cli.main(["serve", str(_changed_copy(bundle, tmp_path / "changed"))]) == 2


def test_the_service_entry_point_installs_its_stop_handler_and_reports_bad_settings(monkeypatch, settings):
    installed = {}
    monkeypatch.setattr(service.signal, "signal", lambda signum, handler: installed.update({signum: handler}))
    _use(monkeypatch, settings)
    monkeypatch.setenv("MONGO_URI", "http://not-mongo")
    assert service.main(["any-bundle"]) == 2
    assert installed[signal.SIGTERM] is service._stop
    with pytest.raises(SystemExit) as stopped:
        service._stop(signal.SIGTERM, None)
    assert stopped.value.code == 143

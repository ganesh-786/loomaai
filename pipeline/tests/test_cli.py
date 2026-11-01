import signal

import pytest

from looma_pipeline import cli


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

import json

import pytest

from looma_pipeline.runctx import RunContext


def test_stage_report_records_counts_and_time(settings):
    ctx = RunContext.create(settings, "pilot", run_id="test-run")
    with ctx.stage("f99_demo") as report:
        report.count("items", 3)
        report.details["note"] = "hello"
    data = json.loads((ctx.run_dir / "f99_demo.json").read_text())
    assert data["status"] == "ok"
    assert data["counts"] == {"items": 3}
    assert data["details"]["note"] == "hello"
    assert data["seconds"] >= 0
    assert (ctx.run_dir / "run.json").exists()


def test_failed_stage_still_writes_its_report(settings):
    ctx = RunContext.create(settings, "pilot", run_id="test-fail")
    with pytest.raises(RuntimeError):
        with ctx.stage("f99_broken"):
            raise RuntimeError("boom")
    data = json.loads((ctx.run_dir / "f99_broken.json").read_text())
    assert data["status"] == "failed"
    assert "boom" in data["error"]


@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit])
def test_stopped_stage_is_reported_as_interrupted_not_ok(settings, stop):
    """Regression: Ctrl+C raised KeyboardInterrupt, which is not an Exception, so the report said "ok"."""
    ctx = RunContext.create(settings, "pilot", run_id=f"test-{stop.__name__}")
    with pytest.raises(stop):
        with ctx.stage("f99_stopped") as report:
            report.count("done_before_stop")
            raise stop()
    data = json.loads((ctx.run_dir / "f99_stopped.json").read_text())
    assert data["status"] == "interrupted"
    assert data["error"] == stop.__name__
    assert data["counts"] == {"done_before_stop": 1}


def test_stage_report_records_peak_memory(settings):
    ctx = RunContext.create(settings, "pilot", run_id="test-memory")
    with ctx.stage("f99_memory"):
        pass
    assert json.loads((ctx.run_dir / "f99_memory.json").read_text())["peak_rss_mb"] > 0


def test_run_ids_are_unique(settings):
    a = RunContext.create(settings, "pilot")
    b = RunContext.create(settings, "pilot")
    assert a.run_id != b.run_id

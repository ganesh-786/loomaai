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


def test_run_ids_are_unique(settings):
    a = RunContext.create(settings, "pilot")
    b = RunContext.create(settings, "pilot")
    assert a.run_id != b.run_id

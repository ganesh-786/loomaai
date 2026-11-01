import json
import os

import pytest

from looma_pipeline.retention import plan, remove


def _bundle(settings, name, run_id="", size=5000):
    folder = settings.bundles_dir / name
    (folder / "meta").mkdir(parents=True)
    (folder / "meta" / "chunks.db").write_bytes(b"x" * size)
    (folder / "manifest.json").write_text(json.dumps({"run_id": run_id}))
    return folder


def _run(settings, name):
    folder = settings.runs_dir / name
    folder.mkdir(parents=True)
    (folder / "items.jsonl").write_bytes(b"y" * 3000)
    return folder


def _names(paths):
    return sorted(p.name for p in paths)


def test_the_newest_bundles_and_runs_of_each_kind_stay(settings):
    for name in ("looma-ai-bundle-2026.11.01-pilot-r1", "looma-ai-bundle-2026.11.01-pilot-r2",
                 "looma-ai-bundle-2026.11.01-pilot-r3", "looma-ai-bundle-2026.10.31-all-r7",
                 "looma-ai-bundle-2026.11.01-all-r9"):
        _bundle(settings, name)
    _bundle(settings, "looma-ai-bundle-2026.11.01-all-r10", run_id="20261030T100000Z-all-aaaa")
    for name in ("20261030T100000Z-all-aaaa", "20261101T100000Z-all-bbbb", "20261101T110000Z-all-cccc",
                 "20261101T120000Z-all-dddd", "20261101T100000Z-pilot-eeee", "e2e-20261101T090000Z",
                 "e2e-20261101T100000Z", "e2e-20261101T110000Z", "eval-typos-20261101T100000Z"):
        _run(settings, name)
    planned = plan(settings, keep=2)
    assert _names(r.path for r in planned.removals) == [
        "20261101T100000Z-all-bbbb",                 # the oldest all run stays: it built a bundle that stays
        "e2e-20261101T090000Z",
        "looma-ai-bundle-2026.10.31-all-r7",
        "looma-ai-bundle-2026.11.01-pilot-r1",       # r10 sorts after r9, not before r2
    ]
    assert "20261030T100000Z-all-aaaa" in _names(planned.kept)


def test_models_cache_keys_unknown_folders_and_symlinks_are_never_planned(settings, tmp_path):
    for folder in (settings.models_dir, settings.data_dir / "cache", settings.data_dir / "keys"):
        folder.mkdir(parents=True)
    for i in range(4):
        _bundle(settings, f"looma-ai-bundle-2026.11.01-pilot-r{i + 1}")
    (settings.bundles_dir / "my-notes").mkdir()
    _run(settings, "my-experiment")
    outside = _bundle(settings, "looma-ai-bundle-2026.10.01-pilot-r1")
    moved = outside.rename(tmp_path / "elsewhere")
    os.symlink(moved, settings.bundles_dir / "looma-ai-bundle-2026.10.01-pilot-r1")
    planned = plan(settings, keep=2)
    assert _names(r.path for r in planned.removals) == ["looma-ai-bundle-2026.11.01-pilot-r1",
                                                         "looma-ai-bundle-2026.11.01-pilot-r2"]


def test_half_written_bundles_can_go(settings):
    _bundle(settings, "looma-ai-bundle-2026.11.01-all-r1")
    (settings.bundles_dir / ".incoming-looma-ai-bundle-2026.11.01-all-r2").mkdir()
    assert _names(r.path for r in plan(settings).removals) == [".incoming-looma-ai-bundle-2026.11.01-all-r2"]


def test_freed_space_counts_shared_files_only_when_every_link_goes(settings):
    settings.models_dir.mkdir(parents=True)
    model = settings.models_dir / "model.int8.onnx"
    model.write_bytes(b"m" * 20000)
    old = _bundle(settings, "looma-ai-bundle-2026.11.01-all-r1")
    (old / "model").mkdir()
    os.link(model, old / "model" / "model.int8.onnx")
    for i in (2, 3):
        _bundle(settings, f"looma-ai-bundle-2026.11.01-all-r{i}")
    planned = plan(settings, keep=2)
    own_files = [old / "meta" / "chunks.db", old / "manifest.json"]
    assert planned.freed_bytes == sum(p.stat().st_blocks * 512 for p in own_files)
    assert remove(planned) == 1
    assert not old.exists() and model.read_bytes() == b"m" * 20000


def test_keep_must_be_at_least_one(settings):
    with pytest.raises(ValueError):
        plan(settings, keep=0)

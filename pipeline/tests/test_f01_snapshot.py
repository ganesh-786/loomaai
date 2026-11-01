import json

import looma_fixture as fx

from looma_pipeline.runctx import RunContext
from looma_pipeline.source import DictSource
from looma_pipeline.stages import f01_snapshot


def _snapshot(settings, data=None, scope="pilot", run_id="r1"):
    ctx = RunContext.create(settings, scope, run_id=run_id)
    return ctx, f01_snapshot.run(ctx, DictSource(data or fx.looma_data()))


def test_pilot_keeps_grades_5_6_science_and_social_studies_only(settings):
    _ctx, snap = _snapshot(settings)
    ids = {doc["_id"] for doc in snap.activities}
    assert fx.A_VID_NEWTON not in ids and fx.A_CH_7S01 not in ids  # grade 7
    assert fx.A_QUIZ not in ids  # quizzes are hidden, as in today's search
    assert {fx.A_CH_6S0102, fx.A_VID_UNITS, fx.A_LESSON, fx.A_GAME, fx.A_VID_PHOTO, fx.A_CH_5S01} <= ids
    assert fx.A_PDF_TOOLS in ids  # linked only through a BOM-prefixed ch_id and nch_id
    assert snap.scope_chapter_ids == {fx.CH_5S01, fx.CH_6S01, fx.CH_6S0102, fx.CH_6SS02}
    assert set(snap.lessons) == {fx.LESSON_DOC} and set(snap.games) == {fx.GAME_DOC}


def test_all_scope_keeps_everything_but_quizzes(settings):
    _ctx, snap = _snapshot(settings, scope="all")
    assert len(snap.activities) == len(fx.looma_data()["activities"]) - 1


def test_dictionary_drops_empty_pairs(settings):
    _ctx, snap = _snapshot(settings)
    assert ("", "खाली") not in snap.dictionary
    assert ("measurement", "नाप") in snap.dictionary


def test_snapshot_hash_is_repeatable_and_tracks_content(settings):
    _c1, first = _snapshot(settings, run_id="a")
    _c2, second = _snapshot(settings, run_id="b")
    assert first.snapshot_hash == second.snapshot_hash
    data = fx.looma_data()
    data["activities"][1]["dn"] = "Changed title"
    _c3, changed = _snapshot(settings, data, run_id="c")
    assert changed.snapshot_hash != first.snapshot_hash


def test_curated_checksum_changes_only_when_curated_fields_change(settings):
    _c1, base = _snapshot(settings, run_id="a")
    data = fx.looma_data()
    data["activities"][1]["thumb"] = "new-thumbnail.png"  # not a curated field
    _c2, same = _snapshot(settings, data, run_id="b")
    assert same.curated_checksum == base.curated_checksum
    data["activities"][1]["cl_lo"] = 3
    _c3, changed = _snapshot(settings, data, run_id="c")
    assert changed.curated_checksum != base.curated_checksum


def test_curated_checksum_covers_bom_keys_and_lesson_nepali(settings):
    _c1, base = _snapshot(settings, run_id="a")
    data = fx.looma_data()
    data["activities"][4]["\ufeffch_id"] = ["6SS03"]
    _c2, bom_changed = _snapshot(settings, data, run_id="b")
    data = fx.looma_data()
    data["lessons"][0]["data"][0]["nepali"] = "अर्को"
    _c3, nepali_changed = _snapshot(settings, data, run_id="c")
    assert bom_changed.curated_checksum != base.curated_checksum
    assert nepali_changed.curated_checksum != base.curated_checksum


def test_report_is_written(settings):
    ctx, snap = _snapshot(settings)
    report = json.loads((ctx.run_dir / "f01_snapshot.json").read_text())
    assert report["status"] == "ok"
    assert report["details"]["snapshot_hash"] == snap.snapshot_hash
    assert report["counts"]["activities_in_scope"] == len(snap.activities)

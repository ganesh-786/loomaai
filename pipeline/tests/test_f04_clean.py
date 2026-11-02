import json

import looma_fixture as fx

from looma_pipeline.models import TextPiece
from looma_pipeline.runctx import RunContext
from looma_pipeline.source import DictSource
from looma_pipeline.stages import f01_snapshot, f04_clean


def _clean(settings, pieces=(), scope="pilot"):
    ctx = RunContext.create(settings, scope, run_id="r")
    snap = f01_snapshot.run(ctx, DictSource(fx.looma_data()))
    items, cleaned = f04_clean.run(ctx, snap, list(pieces))
    return ctx, items, cleaned


def test_curated_grades_stored_as_text_and_decimal_are_parsed(settings):
    _ctx, items, _ = _clean(settings)
    video = items[fx.A_VID_UNITS]
    assert (video.grade_lo, video.grade_hi, video.grade_source) == (6, 7, "curated")


def test_bom_keys_typos_and_language_variants_are_normalized(settings):
    _ctx, items, _ = _clean(settings)
    pdf = items[fx.A_PDF_TOOLS]
    assert pdf.ch_ids == ("6S01.02", "6SS02")  # BOM-prefixed ch_id merged with nch_id
    assert pdf.subject == "Language" and pdf.taxonomy[0] == "Language"  # 'Lamguage ' fixed in memory
    assert pdf.lang == "en"  # 'english'
    assert (pdf.grade_lo, pdf.grade_hi, pdf.grade_source) == (6, 6, "chapter")


def test_only_real_subjects_are_kept():
    assert f04_clean.known_subject(" science ") == "Science"
    assert f04_clean.known_subject("Math") == "Mathematics"
    assert f04_clean.known_subject("Celebrating_Topi_Diwas.jpg") == ""  # a key1 value seen once in the database
    assert f04_clean.known_subject(None) == ""


def test_a_file_name_in_key1_does_not_become_the_subject(settings):
    data = fx.looma_data()
    video = next(a for a in data["activities"] if a["_id"] == fx.A_VID_UNITS)
    video["key1"] = "Celebrating_Topi_Diwas.jpg"
    ctx = RunContext.create(settings, "pilot", run_id="r")
    items, _ = f04_clean.run(ctx, f01_snapshot.run(ctx, DictSource(data)), [])
    assert items[fx.A_VID_UNITS].subject in f04_clean.KNOWN_SUBJECTS | {""}


def test_chapter_items_include_their_own_chapter_and_grade(settings):
    _ctx, items, _ = _clean(settings)
    chapter = items[fx.A_CH_6S0102]
    assert chapter.chapter_id == "6S01.02" and "6S01.02" in chapter.ch_ids
    assert chapter.grade_source == "chapter" and chapter.grade_lo == 6


def test_cehrd_files_are_flagged(settings):
    _ctx, items, _ = _clean(settings)
    assert items[fx.A_HTML_CEHRD].cehrd
    assert not items[fx.A_VID_UNITS].cehrd


def test_subject_falls_back_to_the_linked_textbook(settings):
    _ctx, items, _ = _clean(settings)
    assert items[fx.A_LESSON].subject == "Science"  # no key1; textbook 6S is 'Grade 6 Science'


def test_nepali_only_title_is_kept(settings):
    _ctx, items, _ = _clean(settings)
    village = items[fx.A_IMG_NEPALI]
    assert village.title_en == "" and village.title_np == "हाम्रो गाउँ" and village.lang == "np"


def test_text_pieces_are_cleaned_tagged_and_empty_ones_dropped(settings):
    pieces = [TextPiece("x", "title", 0, " Measurement\u200b and unit "), TextPiece("x", "title", 1, "नाप र एकाइ"),
              TextPiece("x", "lesson", 0, " \u200b ")]
    _ctx, _items, cleaned = _clean(settings, pieces)
    assert [(p.text, p.lang) for p in cleaned] == [("Measurement and unit", "en"), ("नाप र एकाइ", "np")]


def test_report_counts_grade_sources_and_quality_issues(settings):
    ctx, items, _ = _clean(settings)
    report = json.loads((ctx.run_dir / "f04_clean.json").read_text())
    assert report["counts"]["items"] == len(items)
    assert report["counts"]["grade_curated"] >= 2
    assert report["counts"]["bom_keys_merged"] == 1
    assert report["counts"]["cehrd_items"] == 1
    assert (ctx.run_dir / "items.jsonl").exists()

import json

import looma_fixture as fx

from looma_pipeline.runctx import RunContext
from looma_pipeline.source import DictSource
from looma_pipeline.stages import f01_snapshot, f02_content_map


def _map(settings, run_id="r"):
    ctx = RunContext.create(settings, "pilot", run_id=run_id)
    snap = f01_snapshot.run(ctx, DictSource(fx.looma_data()))
    return ctx, f02_content_map.run(ctx, snap)


def test_empty_content_folder_gives_reasons_not_crashes(settings):
    ctx, entries = _map(settings)
    assert entries[fx.A_LESSON].kind == "database" and entries[fx.A_LESSON].reason is None
    assert entries[fx.A_GAME].kind == "database"
    assert entries[fx.A_VID_UNITS].kind == "captions" and entries[fx.A_VID_UNITS].reason == "file missing"
    assert entries[fx.A_PDF_TOOLS].files[0].looma_path == "../content/pdfs/tools.pdf"  # default folder
    assert entries[fx.A_IMG_FAMILY].kind == "title_only"
    report = json.loads((ctx.run_dir / "f02_content_map.json").read_text())
    assert report["counts"]["files_found"] == 0
    assert report["details"]["missing_reasons"]["file missing"] >= 3
    assert (ctx.run_dir / "content_map.jsonl").exists()


def test_textbook_chapter_points_at_both_page_ranges(settings):
    _ctx, entries = _map(settings)
    chapter = entries[fx.A_CH_6S0102]
    assert chapter.kind == "textbook_pages"
    english, nepali = chapter.files
    assert (english.role, english.page_start, english.page_count) == ("textbook_en", 8, 2)
    assert english.looma_path == "../content/textbooks/Class6/Science/Science_6_0036.pdf"
    assert (nepali.role, nepali.page_start, nepali.page_count) == ("textbook_np", 12, 2)


def test_present_files_are_found_and_fingerprinted(settings):
    (settings.content_dir / "pdfs").mkdir()
    (settings.content_dir / "pdfs" / "tools.pdf").write_bytes(b"%PDF-1.4 test")
    (settings.content_dir / "captions").mkdir()
    (settings.content_dir / "captions" / "units.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
    _ctx, entries = _map(settings)
    pdf = entries[fx.A_PDF_TOOLS].files[0]
    assert pdf.exists and pdf.size == 13 and len(pdf.sha256) == 64
    assert entries[fx.A_PDF_TOOLS].reason is None
    assert entries[fx.A_VID_UNITS].files[0].exists

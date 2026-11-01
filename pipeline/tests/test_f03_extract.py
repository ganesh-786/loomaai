import json

import looma_fixture as fx
import pdf_fixtures as pf

from looma_pipeline.runctx import RunContext
from looma_pipeline.source import DictSource
from looma_pipeline.stages import f01_snapshot, f02_content_map, f03_extract


def _extract(settings):
    ctx = RunContext.create(settings, "pilot", run_id="r")
    snap = f01_snapshot.run(ctx, DictSource(fx.looma_data()))
    pieces = f03_extract.run(ctx, snap, f02_content_map.run(ctx, snap))
    return ctx, pieces


def _by_item(pieces, item_id, source=None):
    return [p for p in pieces if p.item_id == item_id and (source is None or p.source == source)]


def test_without_content_files_titles_lessons_and_games_still_come_through(settings):
    ctx, pieces = _extract(settings)
    assert _by_item(pieces, fx.A_LESSON, "lesson") and _by_item(pieces, fx.A_GAME, "game")
    assert _by_item(pieces, fx.A_IMG_NEPALI, "title")[0].expect_nepali
    report = json.loads((ctx.run_dir / "f03_extract.json").read_text())
    assert report["counts"]["files_missing_skipped"] >= 3
    assert report["counts"].get("items_failed", 0) == 0


def test_files_are_extracted_with_pages_and_times(settings):
    content = settings.content_dir
    pf.text_pdf(content / "pdfs" / "tools.pdf", [["A ruler and a measuring tape."], ["A balance measures mass."]])
    (content / "captions").mkdir()
    (content / "captions" / "units.srt").write_text("1\n00:00:03,000 --> 00:00:05,000\nOne metre is 100 cm.\n")
    english_book = [[f"Page {n} intro"] for n in range(1, 14)]
    english_book[7] = ["Length is measured in metres."]
    english_book[8] = ["A kilometre is 1000 metres."]
    pf.text_pdf(content / "textbooks" / "Class6" / "Science" / "Science_6_0036.pdf", english_book)
    nepali_book = ["पृष्ठ"] * 13
    nepali_book[11], nepali_book[12] = "लम्बाइ मिटरमा नापिन्छ।", "एक किलोमिटर हजार मिटर हो।"
    pf.nepali_pdf(content / "textbooks" / "Class6" / "Science" / "Science_6_Nepali_9589.pdf", nepali_book)

    _ctx, pieces = _extract(settings)
    pdf = _by_item(pieces, fx.A_PDF_TOOLS, "document")
    assert [(p.page, p.text) for p in pdf] == [(1, "A ruler and a measuring tape."), (2, "A balance measures mass.")]
    [caption] = _by_item(pieces, fx.A_VID_UNITS, "captions")
    assert caption.t_start == 3.0 and "metre" in caption.text
    textbook = _by_item(pieces, fx.A_CH_6S0102, "textbook")
    assert [(p.page, p.expect_nepali) for p in textbook] == [(8, False), (9, False), (12, True), (13, True)]
    assert "मिटर" in textbook[2].text


def test_an_unreadable_file_is_counted_not_fatal(settings):
    (settings.content_dir / "pdfs").mkdir()
    (settings.content_dir / "pdfs" / "tools.pdf").write_bytes(b"this is not a pdf")
    ctx, pieces = _extract(settings)
    report = json.loads((ctx.run_dir / "f03_extract.json").read_text())
    assert report["counts"]["items_failed"] == 1
    assert report["details"]["failures"][0]["item_id"] == fx.A_PDF_TOOLS
    assert _by_item(pieces, fx.A_PDF_TOOLS, "title")  # the title still made it

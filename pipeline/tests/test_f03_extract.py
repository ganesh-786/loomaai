import json
from dataclasses import replace

import looma_fixture as fx
import pdf_fixtures as pf
import pytest

from looma_pipeline.extractors.transcripts import TranscriptError
from looma_pipeline.hashing import sha256_of_file
from looma_pipeline.runctx import RunContext
from looma_pipeline.source import DictSource
from looma_pipeline.stages import f01_snapshot, f02_content_map, f03_extract


def _extract(settings, run_id="r"):
    ctx = RunContext.create(settings, "pilot", run_id=run_id)
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


# --- Page transcripts (issue #2): reviewed transcript text replaces the text layer, page by page ---

def _tools_pdf(settings):
    """The fixture's Measuring tools PDF (two text pages); returns its sha256."""
    path = pf.text_pdf(settings.content_dir / "pdfs" / "tools.pdf",
                       [["A ruler and a measuring tape."], ["A balance measures mass."]])
    return sha256_of_file(path)


def _write_transcripts(settings, rows):
    settings.transcripts_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"file": "pdfs/tools.pdf", "run": "D-test", "method": "visual-transcription",
                         "model": "test-model", "review_status": "reviewed", **r}) for r in rows]
    (settings.transcripts_dir / "run.jsonl").write_text("\n".join(lines) + "\n")


def _report(ctx):
    return json.loads((ctx.run_dir / "f03_extract.json").read_text())


def test_a_reviewed_transcript_replaces_the_text_layer_for_its_page_only(settings):
    sha = _tools_pdf(settings)
    _write_transcripts(settings, [{"file_sha256": sha, "page": 2, "text": "A balance (×2) measures mass."}])
    ctx, pieces = _extract(settings)
    pdf = _by_item(pieces, fx.A_PDF_TOOLS, "document")
    assert [(p.page, p.text) for p in pdf] == [(1, "A ruler and a measuring tape."),
                                               (2, "A balance (×2) measures mass.")]
    counts = _report(ctx)["counts"]
    # Page 1 keeps its own extraction method: these short fixture lines (< 40 letters) go to OCR when Tesseract
    # is installed, and to the text layer when it is not.
    assert counts["pages_transcript"] == 1
    assert counts.get("pages_text", 0) + counts.get("pages_ocr", 0) == 1
    assert counts["transcript_rows_used"] == 1


def test_an_unreviewed_transcript_is_used_only_with_the_setting(settings):
    sha = _tools_pdf(settings)
    _write_transcripts(settings, [{"file_sha256": sha, "page": 1, "text": "Transcribed page one.",
                                   "review_status": "unreviewed"}])
    ctx, pieces = _extract(settings)
    assert _by_item(pieces, fx.A_PDF_TOOLS, "document")[0].text == "A ruler and a measuring tape."
    assert _report(ctx)["counts"]["transcript_rows_unreviewed_skipped"] == 1

    _ctx, pieces = _extract(replace(settings, transcripts_allow_unreviewed=True), run_id="r2")
    assert _by_item(pieces, fx.A_PDF_TOOLS, "document")[0].text == "Transcribed page one."


def test_a_transcript_of_an_older_version_of_the_pdf_is_reported_stale_and_not_used(settings):
    _tools_pdf(settings)
    _write_transcripts(settings, [{"file_sha256": "0" * 64, "page": 1, "text": "Text of an older file."}])
    ctx, pieces = _extract(settings)
    assert _by_item(pieces, fx.A_PDF_TOOLS, "document")[0].text == "A ruler and a measuring tape."
    counts = _report(ctx)["counts"]
    assert counts["transcript_rows_stale"] == 1 and counts.get("pages_transcript", 0) == 0


def test_a_transcript_for_a_file_outside_the_build_is_counted_unmatched(settings):
    _tools_pdf(settings)
    _write_transcripts(settings, [{"file": "pdfs/other.pdf", "file_sha256": "1" * 64, "page": 1, "text": "x y z"}])
    ctx, _pieces = _extract(settings)
    assert _report(ctx)["counts"]["transcript_rows_unmatched"] == 1


def test_a_transcript_replaces_a_textbook_chapter_page(settings):
    book = [[f"Page {n} intro"] for n in range(1, 14)]
    book[7], book[8] = ["Length is measured in metres."], ["A kilometre is 1000 metres."]
    path = pf.text_pdf(settings.content_dir / "textbooks" / "Class6" / "Science" / "Science_6_0036.pdf", book)
    _write_transcripts(settings, [{"file": "textbooks/Class6/Science/Science_6_0036.pdf",
                                   "file_sha256": sha256_of_file(path), "page": 9,
                                   "text": "A kilometre is 1 000 metres (1 km = 1000 m)."}])
    _ctx, pieces = _extract(settings)
    textbook = _by_item(pieces, fx.A_CH_6S0102, "textbook")
    assert [(p.page, p.text) for p in textbook] == [(8, "Length is measured in metres."),
                                                    (9, "A kilometre is 1 000 metres (1 km = 1000 m).")]


def test_without_transcripts_extraction_is_unchanged_and_says_so(settings):
    _tools_pdf(settings)
    ctx, pieces = _extract(settings)
    assert [p.text for p in _by_item(pieces, fx.A_PDF_TOOLS, "document")] == [
        "A ruler and a measuring tape.", "A balance measures mass."]
    report = _report(ctx)
    assert report["counts"].get("pages_transcript", 0) == 0
    assert report["details"]["transcripts"]["files"] == 0


def _rows_with_broken_lines(settings, sha, valid, broken):
    """`valid` good rows (pages 1..valid of tools.pdf) followed by `broken` lines that are not JSON."""
    _write_transcripts(settings, [{"file_sha256": sha, "page": n, "text": f"Page {n} as transcribed."}
                                  for n in range(1, valid + 1)])
    with (settings.transcripts_dir / "run.jsonl").open("a") as handle:
        handle.write("{broken\n" * broken)


def test_a_few_malformed_rows_are_reported_and_extraction_goes_on(settings):
    sha = _tools_pdf(settings)
    _rows_with_broken_lines(settings, sha, valid=100, broken=1)  # 1 of 101 rows: under the 1% limit
    ctx, pieces = _extract(settings)
    assert [p.text for p in _by_item(pieces, fx.A_PDF_TOOLS, "document")] == [
        "Page 1 as transcribed.", "Page 2 as transcribed."]
    report = _report(ctx)
    assert report["counts"]["transcript_rows_malformed"] == 1
    assert report["details"]["transcripts"]["problems"][0]["line"] == 101


def test_too_many_malformed_rows_stop_the_run(settings):
    sha = _tools_pdf(settings)
    _rows_with_broken_lines(settings, sha, valid=100, broken=2)  # 2 of 102 rows: over the 1% limit
    with pytest.raises(TranscriptError, match="malformed"):
        _extract(settings)
    report = json.loads((settings.runs_dir / "r" / "f03_extract.json").read_text())
    assert report["status"] == "failed" and "2 of 102" in report["error"]


def test_an_unreadable_transcript_file_stops_the_run(settings):
    _tools_pdf(settings)
    settings.transcripts_dir.mkdir(parents=True)
    (settings.transcripts_dir / "bad.jsonl").write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(TranscriptError, match="could not be read"):
        _extract(settings)


def test_a_transcribed_page_is_not_sent_to_ocr(settings, monkeypatch):
    read_by_ocr = []

    class FakeOcr:
        """Stands in for Tesseract and records the 1-based pages it was asked to read."""

        def __init__(self, languages):
            pass

        @staticmethod
        def available():
            return True

        def page_text(self, page):
            read_by_ocr.append(page.number + 1)
            return "Text that OCR read."

    monkeypatch.setattr(f03_extract, "TesseractOcr", FakeOcr)
    sha = _tools_pdf(settings)  # its short lines make both pages look scanned
    _write_transcripts(settings, [{"file_sha256": sha, "page": 2, "text": "A balance measures mass."}])
    ctx, _pieces = _extract(settings)
    assert read_by_ocr == [1]
    counts = _report(ctx)["counts"]
    assert counts["pages_ocr"] == 1 and counts["pages_transcript"] == 1


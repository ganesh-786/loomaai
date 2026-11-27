"""F3 extract: text pieces for every in-scope item, from MongoDB records and from files.

Import only (called by looma_pipeline.pipeline). Every item gets its title pieces. Then, by the F2 content kind:
lessons and games from their MongoDB records; PDFs and worksheets page by page (OCR for scanned pages when
`OCR_ENABLED=1` and Tesseract is installed); HTML pages; caption files with start times; and textbook page ranges for
chapters. A file that cannot be read is logged with its item id and counted; it never stops the run.
PDF pages (documents and textbook ranges) that have a usable page transcript (extractors/transcripts.py, issue #2)
take the transcript's text instead of the extracted text and are not sent to OCR; every other page keeps the
extracted text. The stage stops when a transcript file cannot be read or more than 1% of its rows are malformed.
Side effects: reads files under the content folder and the transcripts folder; writes `f03_extract.json` in the run
folder.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from looma_pipeline.config import Settings
from looma_pipeline.extractors.captions import read_captions
from looma_pipeline.extractors.database import game_pieces, lesson_pieces, title_pieces
from looma_pipeline.extractors.html import read_html
from looma_pipeline.extractors.ocr import TesseractOcr
from looma_pipeline.extractors.pdf import PdfPage, extract_pages
from looma_pipeline.extractors.transcripts import TranscriptIndex, TranscriptPage, check_quality, load_transcripts
from looma_pipeline.models import TextPiece
from looma_pipeline.paths import LOOMA_CONTENT_PREFIX
from looma_pipeline.runctx import RunContext, StageReport
from looma_pipeline.stages.f01_snapshot import Snapshot
from looma_pipeline.stages.f02_content_map import ContentEntry, FileRef

log = logging.getLogger(__name__)

PDF_TYPES = frozenset({"pdf", "worksheet"})
MAX_FAILURES_IN_REPORT = 50
MAX_TRANSCRIPT_PROBLEMS_IN_REPORT = 50


@dataclass
class TranscriptUse:
    """The run's transcript index, plus which rows were used and which PDF files the run read."""

    index: TranscriptIndex
    used: set[tuple[str, int]] = field(default_factory=set)
    files_seen: dict[str, str] = field(default_factory=dict)  # path under the content folder -> its sha256

    def saw(self, ref: FileRef) -> None:
        """Record a PDF the run read, so a transcript of an older version of it can be reported as stale.

        Args:
            ref: the F2 file reference; files without a sha256 (missing files) are ignored.
        """
        if ref.sha256:
            self.files_seen[ref.looma_path.removeprefix(LOOMA_CONTENT_PREFIX)] = ref.sha256

    def take(self, file_sha256: str | None, page: int) -> TranscriptPage | None:
        """The usable transcript for this page, marked as used, or None.

        Args:
            file_sha256: sha256 of the PDF file (from F2).
            page: 1-based PDF page.

        Returns:
            The transcript page, or None when the page has no usable transcript.
        """
        transcript = self.index.lookup(file_sha256, page)
        if transcript is not None:
            self.used.add((transcript.file_sha256, transcript.page))
        return transcript

    def unused(self) -> tuple[list[TranscriptPage], list[TranscriptPage]]:
        """Usable rows the run never took: (stale, unmatched).

        Stale: the row names a PDF this run read, but that file now has a different sha256 (it was replaced after
        the transcript was made). Unmatched: anything else, e.g. a file outside the build scope or a page outside
        the chapter's page range.
        """
        stale, unmatched = [], []
        for key, page in sorted(self.index.pages.items()):
            if key in self.used:
                continue
            current = self.files_seen.get(page.file)
            (stale if current is not None and current != page.file_sha256 else unmatched).append(page)
        return stale, unmatched


def _page_pieces(item_id: str, source: str, pages: list[PdfPage], expect_nepali: bool, report: StageReport,
                 transcripts: TranscriptUse, file_sha256: str | None) -> list[TextPiece]:
    pieces = []
    for page in pages:
        transcript = transcripts.take(file_sha256, page.number)
        if transcript is not None:
            report.count("pages_transcript")
            text = transcript.text
        else:
            report.count(f"pages_{page.method}")
            text = page.text
        if text:
            pieces.append(TextPiece(item_id, source, page.number, text, page=page.number,
                                    expect_nepali=expect_nepali))
    return pieces


def _content_pieces(doc: dict, entry: ContentEntry, snapshot: Snapshot, ocr: TesseractOcr | None,
                    report: StageReport, transcripts: TranscriptUse) -> list[TextPiece]:
    item_id, ft = entry.item_id, entry.ft
    if entry.kind == "database":
        record_id = str(doc.get("mongoID", ""))
        if ft == "lesson" and record_id in snapshot.lessons:
            return lesson_pieces(item_id, snapshot.lessons[record_id])
        if ft == "game" and record_id in snapshot.games:
            return game_pieces(item_id, snapshot.games[record_id])
        report.count("database_record_missing")
        return []

    pieces: list[TextPiece] = []
    for ref in entry.files:
        if not ref.exists or ref.local_path is None:
            report.count("files_missing_skipped")
            continue
        path = Path(ref.local_path)
        if entry.kind == "captions":
            pieces += [TextPiece(item_id, "captions", n, cue.text, t_start=cue.start)
                       for n, cue in enumerate(read_captions(path))]
        elif entry.kind == "textbook_pages":
            transcripts.saw(ref)
            pages = extract_pages(path, ref.page_start, ref.page_count, ocr,
                                  skip_ocr=transcripts.index.pages_of(ref.sha256))
            pieces += _page_pieces(item_id, "textbook", pages, ref.role == "textbook_np", report, transcripts,
                                   ref.sha256)
        elif ft in PDF_TYPES:
            transcripts.saw(ref)
            pages = extract_pages(path, ocr=ocr, skip_ocr=transcripts.index.pages_of(ref.sha256))
            pieces += _page_pieces(item_id, "document", pages, False, report, transcripts, ref.sha256)
        elif ft == "html":
            title, text = read_html(path)
            pieces += [TextPiece(item_id, "document", 0, f"{title}\n{text}".strip())] if text or title else []
        report.count("files_read")
    return pieces


def run(ctx: RunContext, snapshot: Snapshot, content_map: dict[str, ContentEntry]) -> list[TextPiece]:
    """Extract text for every in-scope item."""
    settings = ctx.settings
    ocr = TesseractOcr(settings.ocr_langs) if settings.ocr_enabled and TesseractOcr.available() else None
    with ctx.stage("f03_extract") as report:
        report.details["ocr"] = f"on ({settings.ocr_langs})" if ocr else "off"
        transcripts = TranscriptUse(load_transcripts(settings.transcripts_dir, settings.transcripts_allow_unreviewed))
        _report_transcripts(report, transcripts, settings)  # written first, so a stopped run still shows the cause
        check_quality(transcripts.index)
        pieces: list[TextPiece] = []
        failures = []
        for doc in snapshot.activities:
            entry = content_map[str(doc["_id"])]
            pieces += title_pieces(doc)
            try:
                pieces += _content_pieces(doc, entry, snapshot, ocr, report, transcripts)
            except (OSError, RuntimeError, ValueError, UnicodeError) as exc:  # OcrError and PyMuPDF errors too
                report.count("items_failed")
                failures.append({"item_id": entry.item_id, "error": f"{type(exc).__name__}: {exc}"[:300]})
                log.warning("extraction failed", extra={"item_id": entry.item_id, "error": str(exc)[:300]})
        report.counts.update({f"pieces_{source}": n for source, n in sorted(Counter(p.source for p in pieces).items())})
        report.counts["pieces"] = len(pieces)
        report.details["failures"] = failures[:MAX_FAILURES_IN_REPORT]
        _report_transcripts(report, transcripts, settings)
        return pieces


def _report_transcripts(report: StageReport, transcripts: TranscriptUse, settings: Settings) -> None:
    """Add transcript counts (prefixed `transcript_`) and up to 50 problems to the F3 report."""
    stale, unmatched = transcripts.unused()
    index = transcripts.index
    report.counts.update({f"transcript_{key}": n for key, n in sorted(index.counts.items())})
    report.counts.update({"transcript_rows_used": len(transcripts.used), "transcript_rows_stale": len(stale),
                          "transcript_rows_unmatched": len(unmatched)})
    problems = list(index.problems) + [
        {"file": page.file, "line": None, "reason": f"stale: page {page.page} was transcribed from a different "
                                                    f"version of the file (sha256 {page.file_sha256[:12]}...)"}
        for page in stale]
    report.details["transcripts"] = {
        "folder": str(settings.transcripts_dir), "allow_unreviewed": settings.transcripts_allow_unreviewed,
        "files": index.counts["files"], "problems": problems[:MAX_TRANSCRIPT_PROBLEMS_IN_REPORT]}

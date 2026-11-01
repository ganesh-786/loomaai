"""F3 extract: text pieces for every in-scope item, from MongoDB records and from files.

Import only (called by looma_pipeline.pipeline). Every item gets its title pieces. Then, by the F2 content kind:
lessons and games from their MongoDB records; PDFs and worksheets page by page (OCR for scanned pages when
`OCR_ENABLED=1` and Tesseract is installed); HTML pages; caption files with start times; and textbook page ranges for
chapters. A file that cannot be read is logged with its item id and counted; it never stops the run.
Side effects: reads files under the content folder; writes `f03_extract.json` in the run folder.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from looma_pipeline.extractors.captions import read_captions
from looma_pipeline.extractors.database import game_pieces, lesson_pieces, title_pieces
from looma_pipeline.extractors.html import read_html
from looma_pipeline.extractors.ocr import TesseractOcr
from looma_pipeline.extractors.pdf import PdfPage, extract_pages
from looma_pipeline.models import TextPiece
from looma_pipeline.runctx import RunContext, StageReport
from looma_pipeline.stages.f01_snapshot import Snapshot
from looma_pipeline.stages.f02_content_map import ContentEntry

log = logging.getLogger(__name__)

PDF_TYPES = frozenset({"pdf", "worksheet"})
MAX_FAILURES_IN_REPORT = 50


def _page_pieces(item_id: str, source: str, pages: list[PdfPage], expect_nepali: bool,
                 report: StageReport) -> list[TextPiece]:
    for page in pages:
        report.count(f"pages_{page.method}")
    return [TextPiece(item_id, source, page.number, page.text, page=page.number, expect_nepali=expect_nepali)
            for page in pages if page.text]


def _content_pieces(doc: dict, entry: ContentEntry, snapshot: Snapshot, ocr: TesseractOcr | None,
                    report: StageReport) -> list[TextPiece]:
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
            pages = extract_pages(path, ref.page_start, ref.page_count, ocr)
            pieces += _page_pieces(item_id, "textbook", pages, ref.role == "textbook_np", report)
        elif ft in PDF_TYPES:
            pieces += _page_pieces(item_id, "document", extract_pages(path, ocr=ocr), False, report)
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
        pieces: list[TextPiece] = []
        failures = []
        for doc in snapshot.activities:
            entry = content_map[str(doc["_id"])]
            pieces += title_pieces(doc)
            try:
                pieces += _content_pieces(doc, entry, snapshot, ocr, report)
            except (OSError, RuntimeError, ValueError, UnicodeError) as exc:  # OcrError and PyMuPDF errors too
                report.count("items_failed")
                failures.append({"item_id": entry.item_id, "error": f"{type(exc).__name__}: {exc}"[:300]})
                log.warning("extraction failed", extra={"item_id": entry.item_id, "error": str(exc)[:300]})
        report.counts.update({f"pieces_{source}": n for source, n in sorted(Counter(p.source for p in pieces).items())})
        report.counts["pieces"] = len(pieces)
        report.details["failures"] = failures[:MAX_FAILURES_IN_REPORT]
        return pieces

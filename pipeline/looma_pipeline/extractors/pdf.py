"""PDF pages to text, with OCR for scanned pages and cleanup of running headers and page numbers.

Import only; reads one PDF. Each page keeps its 1-based page number, so a passage can link to `?page=` in Looma's
PDF viewer. A page whose text layer has fewer than `min_letters` letters is sent to OCR (when an OCR engine is
given). Cleanup after extraction:
- lines that repeat at the top or bottom of most pages (running headers and footers) are removed;
- lines that are only a page number are removed;
- words broken across lines with a hyphen are joined.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

import fitz

from looma_pipeline.extractors.ocr import TesseractOcr

MIN_LETTERS_FOR_TEXT_LAYER = 40  # below this a page is treated as scanned
REPEATED_LINE_SHARE = 0.6        # a top/bottom line on at least 60% of pages is a running header or footer
EDGE_LINES = 2                   # how many lines at each page edge are checked for headers and footers
_PAGE_NUMBER = re.compile(r"^[\s\-–—]*[0-9०-९]{1,4}[\s\-–—]*$")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_DIGITS = re.compile(r"[0-9०-९]+")


@dataclass(frozen=True)
class PdfPage:
    number: int   # 1-based
    text: str
    method: str   # "text" | "ocr" | "empty"


def _letters(text: str) -> int:
    return sum(ch.isalpha() for ch in text)


def _edge_key(line: str) -> str:
    return _DIGITS.sub("#", line.strip().lower())


def remove_repeated_lines(pages: list[PdfPage]) -> list[PdfPage]:
    """Drop running headers/footers, bare page numbers, and hyphenated line breaks."""
    if len(pages) >= 3:
        edges = Counter()
        for page in pages:
            lines = [ln for ln in page.text.splitlines() if ln.strip()]
            edges.update({_edge_key(ln) for ln in lines[:EDGE_LINES] + lines[-EDGE_LINES:]})
        repeated = {key for key, n in edges.items() if n >= REPEATED_LINE_SHARE * len(pages)}
    else:
        repeated = set()
    cleaned = []
    for page in pages:
        kept = [ln for ln in page.text.splitlines()
                if ln.strip() and _edge_key(ln) not in repeated and not _PAGE_NUMBER.match(ln)]
        cleaned.append(replace(page, text=_HYPHEN_BREAK.sub(r"\1\2", "\n".join(kept)).strip()))
    return cleaned


def extract_pages(path: Path, first_page: int | None = None, page_count: int | None = None,
                  ocr: TesseractOcr | None = None, min_letters: int = MIN_LETTERS_FOR_TEXT_LAYER) -> list[PdfPage]:
    """Text of pages `first_page` .. `first_page + page_count - 1` (1-based; default: every page).

    Raises:
        RuntimeError: from PyMuPDF if the file is not a readable PDF.
        OcrError: if OCR is needed and Tesseract fails.
    """
    pages: list[PdfPage] = []
    with fitz.open(path) as document:
        start = max(first_page or 1, 1)
        end = document.page_count if page_count is None else min(start + page_count - 1, document.page_count)
        for number in range(start, end + 1):
            page = document.load_page(number - 1)
            text, method = page.get_text("text"), "text"
            if _letters(text) < min_letters and ocr is not None:
                text, method = ocr.page_text(page), "ocr"
            pages.append(PdfPage(number, text, method if text.strip() else "empty"))
    return remove_repeated_lines(pages)

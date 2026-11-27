"""PDF pages to text, with OCR for scanned pages and cleanup of running headers and page numbers.

Import only; reads one PDF. Each page keeps its 1-based page number, so a passage can link to `?page=` in Looma's
PDF viewer. A page whose text layer has fewer than `min_letters` letters is sent to OCR (when an OCR engine is
given), unless the caller lists it in `skip_ocr` because a page transcript replaces it. Cleanup after extraction:
- lines that repeat at the top or bottom of most pages that have text (running headers and footers) are removed.
  Lines are compared by their words of 4 or more letters, so page numbers and OCR fragments glued to a footer
  ("cm", "coe", "&" read from
  the page-number badge of a scanned book) do not make its copies look different; a line at the page edge that is at
  least 85% similar to a running header or footer (an OCR misspelling) is removed too;
- lines that are only a page number are removed;
- words broken across lines with a hyphen are joined.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path

import fitz

from looma_pipeline.extractors.ocr import TesseractOcr

MIN_LETTERS_FOR_TEXT_LAYER = 40  # below this a page is treated as scanned
REPEATED_LINE_SHARE = 0.6        # a top/bottom line on at least 60% of pages is a running header or footer
EDGE_LINES = 2                   # how many lines at each page edge are checked for headers and footers
KEY_WORD_MIN_CHARS = 4           # shorter words are ignored when comparing header/footer lines (OCR fragments)
EDGE_SIMILARITY = 0.85           # an edge line this similar to a running header/footer is one too (OCR misspellings)
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


def _words(line: str) -> list[str]:
    """Case-folded runs of letters and combining marks, so a Devanagari word with vowel signs stays one word."""
    words, current = [], []
    for ch in unicodedata.normalize("NFC", line).casefold():
        if unicodedata.category(ch)[0] in "LM":
            current.append(ch)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def _edge_key(line: str) -> str:
    """What two copies of a header or footer line share: their words of 4+ letters, in order.

    A line without such a word (for example "p. 12") keeps the exact comparison, with digits masked.
    """
    long_words = [word for word in _words(line) if len(word) >= KEY_WORD_MIN_CHARS]
    return " ".join(long_words) if long_words else _DIGITS.sub("#", line.strip().lower())


def _is_running_line(key: str, at_edge: bool, repeated: set[str]) -> bool:
    """A repeated key anywhere on the page, or a near copy of one at the page edge."""
    return key in repeated or (at_edge and any(SequenceMatcher(None, key, running).ratio() >= EDGE_SIMILARITY
                                               for running in repeated))


def remove_repeated_lines(pages: list[PdfPage]) -> list[PdfPage]:
    """Drop running headers/footers, bare page numbers, and hyphenated line breaks.

    The share of pages a running line must appear on is taken over pages that have text. Pages without text
    (scanned pages without OCR, or pages whose OCR was skipped because a transcript replaces them) cannot carry a
    footer, so counting them would hide real footers on the other pages.
    """
    with_text = [page for page in pages if page.text.strip()]
    if len(with_text) >= 3:
        edges = Counter()
        for page in with_text:
            lines = [ln for ln in page.text.splitlines() if ln.strip()]
            edges.update({_edge_key(ln) for ln in lines[:EDGE_LINES] + lines[-EDGE_LINES:]})
        repeated = {key for key, n in edges.items() if n >= REPEATED_LINE_SHARE * len(with_text)}
    else:
        repeated = set()
    cleaned = []
    for page in pages:
        lines = [ln for ln in page.text.splitlines() if ln.strip()]
        edge = set(range(min(EDGE_LINES, len(lines)))) | set(range(max(len(lines) - EDGE_LINES, 0), len(lines)))
        kept = [ln for index, ln in enumerate(lines)
                if not _is_running_line(_edge_key(ln), index in edge, repeated) and not _PAGE_NUMBER.match(ln)]
        cleaned.append(replace(page, text=_HYPHEN_BREAK.sub(r"\1\2", "\n".join(kept)).strip()))
    return cleaned


def extract_pages(path: Path, first_page: int | None = None, page_count: int | None = None,
                  ocr: TesseractOcr | None = None, min_letters: int = MIN_LETTERS_FOR_TEXT_LAYER,
                  skip_ocr: frozenset[int] = frozenset()) -> list[PdfPage]:
    """Text of pages `first_page` .. `first_page + page_count - 1` (1-based; default: every page).

    Args:
        path: the PDF file.
        first_page: 1-based first page; default 1.
        page_count: number of pages; default to the end of the file.
        ocr: OCR engine for pages with fewer than `min_letters` letters; None turns OCR off.
        min_letters: below this many letters a page is treated as scanned.
        skip_ocr: 1-based pages never sent to OCR, because a page transcript replaces their text (F3). OCR costs
            seconds per page; on a scanned book with transcripts that time would be thrown away.

    Returns:
        One PdfPage per page, after running header/footer cleanup.

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
            if _letters(text) < min_letters and ocr is not None and number not in skip_ocr:
                text, method = ocr.page_text(page), "ocr"
            pages.append(PdfPage(number, text, method if text.strip() else "empty"))
    return remove_repeated_lines(pages)

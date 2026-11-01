"""Generate small PDFs for tests: text pages, image-only (scanned-looking) pages, and Nepali text.

Nepali is laid out with PyMuPDF's HTML engine (HarfBuzz shaping), so vowel signs and conjuncts render correctly.
"""

from __future__ import annotations

from pathlib import Path

import fitz

DEVANAGARI_FONT_DIR = "/usr/share/fonts/truetype/lohit-devanagari"
DEVANAGARI_CSS = ("@font-face {font-family: deva; src: url(Lohit-Devanagari.ttf);} "
                  "* {font-family: deva; font-size: 30px;}")


def text_pdf(path: Path, pages: list[list[str]]) -> Path:
    """One PDF page per entry; each entry is a list of lines written top to bottom."""
    document = fitz.open()
    for lines in pages:
        page = document.new_page()
        for number, line in enumerate(lines):
            page.insert_text((72, 72 + 18 * number), line, fontsize=12)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)
    return path


def nepali_pdf(path: Path, pages: list[str]) -> Path:
    """One page per string, with a real (extractable) Devanagari text layer."""
    archive = fitz.Archive(DEVANAGARI_FONT_DIR)
    document = fitz.open()
    for text in pages:
        page = document.new_page()
        page.insert_htmlbox(fitz.Rect(50, 50, 550, 750), f"<p>{text}</p>", css=DEVANAGARI_CSS, archive=archive)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)
    return path


def scanned_pdf(path: Path, html: str, css: str = "* {font-size: 34px;}", archive_dir: str | None = None) -> Path:
    """A one-page PDF that is only an image of `html` (no text layer), like a scanned page."""
    source = fitz.open()
    page = source.new_page()
    archive = fitz.Archive(archive_dir) if archive_dir else None
    page.insert_htmlbox(fitz.Rect(50, 50, 550, 750), html, css=css, archive=archive)
    pixmap = page.get_pixmap(dpi=200)
    scanned = fitz.open()
    image_page = scanned.new_page(width=page.rect.width, height=page.rect.height)
    image_page.insert_image(image_page.rect, pixmap=pixmap)
    path.parent.mkdir(parents=True, exist_ok=True)
    scanned.save(path)
    return path

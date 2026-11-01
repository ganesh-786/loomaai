"""Unicode cleanup and HTML-to-text for English and Nepali.

Import only; pure functions. NFC normalization plus removal of zero-width characters and byte-order marks makes the
same Nepali word compare equal however it was typed; this was needed for correct FTS5 matching (measured
2026-10-28 on lesson slides). Lesson HTML can hold whole images as base64 data URIs, which are removed before text
extraction.
"""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
_DATA_URI = re.compile(r"data:[^\"'\s)>]+")
_SPACES = re.compile(r"[ \t\r\f\v\u00a0\u2000-\u200a\u202f\u205f\u3000]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")
_NOISE_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form")


def normalize_text(text: str | None) -> str:
    """NFC, no zero-width characters, single spaces, at most one blank line between paragraphs."""
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFC", str(text)).translate(ZERO_WIDTH)
    lines = [_SPACES.sub(" ", line).strip() for line in cleaned.replace("\r\n", "\n").split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def strip_data_uris(html: str) -> str:
    return _DATA_URI.sub("", html)


def html_to_text(html: str | None) -> str:
    """Visible text of an HTML fragment or page, without scripts, navigation or embedded images."""
    if not html:
        return ""
    soup = BeautifulSoup(strip_data_uris(str(html)), "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    return normalize_text(soup.get_text("\n"))

"""HTML files (Wikipedia for Schools, PhET pages and similar) to visible text.

Import only; one file read. BeautifulSoup detects the file's encoding; scripts, styles and navigation are dropped.
"""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from looma_pipeline.text.normalize import html_to_text, normalize_text


def read_html(path: Path) -> tuple[str, str]:
    """Returns (page title, visible text)."""
    soup = BeautifulSoup(path.read_bytes(), "html.parser")
    title = normalize_text(soup.title.get_text()) if soup.title else ""
    return title, html_to_text(str(soup))

"""OCR of scanned PDF pages with Tesseract (English and Nepali models).

Import only. Calls the `tesseract` program in a subprocess, reading a PNG from stdin and writing text to stdout,
so no temporary files are left behind. Used only for pages that have (almost) no text layer.
"""

from __future__ import annotations

import shutil
import subprocess

import fitz

DEFAULT_DPI = 300           # Tesseract's recommended resolution for printed text
DEFAULT_TIMEOUT_SECONDS = 120


class OcrError(RuntimeError):
    """Tesseract failed or timed out on a page."""


class TesseractOcr:
    def __init__(self, languages: str = "eng+nep", dpi: int = DEFAULT_DPI,
                 timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.languages = languages
        self.dpi = dpi
        self.timeout = timeout

    @staticmethod
    def available() -> bool:
        return shutil.which("tesseract") is not None

    def image_text(self, png: bytes) -> str:
        """Text in a PNG image.

        Raises:
            OcrError: if Tesseract exits with an error or takes longer than the timeout.
        """
        try:
            completed = subprocess.run(
                ["tesseract", "stdin", "stdout", "-l", self.languages, "--psm", "3"],
                input=png, capture_output=True, timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OcrError(f"tesseract took longer than {self.timeout} s") from exc
        if completed.returncode != 0:
            raise OcrError(completed.stderr.decode("utf-8", errors="replace").strip()[:300])
        return completed.stdout.decode("utf-8", errors="replace")

    def page_text(self, page: fitz.Page) -> str:
        return self.image_text(page.get_pixmap(dpi=self.dpi).tobytes("png"))

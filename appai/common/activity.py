from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
import os
import requests
import fitz
from langchain_huggingface import HuggingFaceEmbeddings
from pymongo.database import Database

class Activity(ABC):
    def __init__(self, activity: dict):
        self.activity = activity
        self.cl_lo = activity.get("cl_lo", None)
        self.cl_hi = activity.get("cl_hi", None)
        self.cl_official = activity.get("cl_official", None)

    @abstractmethod
    def embed(self, mongo: Database, embeddings: HuggingFaceEmbeddings) -> list[float]:
        pass

    @abstractmethod
    def payload(self) -> dict:
        pass

    @abstractmethod
    def get_text(self, mongo: Database) -> str:
        pass


def download_pdf(url):
    response = requests.get(url)
    response.raise_for_status()
    return BytesIO(response.content)


def extract_text_from_pdf(pdf_stream):
    pdf_document = fitz.open(stream=pdf_stream, filetype="pdf")
    text = ""

    for page_num in range(len(pdf_document)):
        page = pdf_document.load_page(page_num)
        text += page.get_text()

    pdf_document.close()
    return text


# Page-level access for the PDF ingest (python -m appai.cli.ingest_pdfs; fork issue #2). The functions above
# stay as they are because embed.py uses them; the ones below keep page numbers and read local files only.

# activities.fp is relative to Looma's web root (e.g. "../content/PhET/"); textbooks.fp is relative to the
# content folder itself (e.g. "textbooks/Class10/Science/"). Both resolve against one content folder.
LOOMA_CONTENT_PREFIX = "../content/"


class PageSourceError(Exception):
    """An item's PDF pages can't be read. `reason` is a stable code that run reports count."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class PdfPageSource:
    """Where an item's pages are: a PDF under the content folder and a 1-based, inclusive page range.

    Attributes:
        relative_path: the file as Looma stores it, relative to the content folder ("PhET/x.pdf").
        path: the absolute path on this machine.
        first_page: first PDF page to read, 1-based like chapters.pn.
        last_page: last PDF page to read, inclusive; None means the last page of the file.
    """
    relative_path: str
    path: str
    first_page: int = 1
    last_page: int | None = None


def parse_looma_int(value) -> int | None:
    """Reads a Looma integer field that may be an int, a digit string or an integral double.

    Looma stores the same field with several types (chapters.pn is "" in 862 chapters; cl_lo is an int,
    string or double), so callers normalize here instead of comparing raw values.

    Returns:
        The integer, or None for "", None, booleans, fractions and any other text.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def resolve_content_path(content_dir: str, relative_path: str) -> str:
    """Resolves a Looma file path inside the content folder, refusing anything outside it.

    Args:
        content_dir: the local copy of Looma's content folder.
        relative_path: a path from Mongo, with or without the "../content/" prefix.

    Returns:
        The absolute, symlink-resolved path.

    Raises:
        PageSourceError: "path_outside_content_dir" when the path escapes the folder (".." or absolute).
    """
    root = os.path.realpath(content_dir)
    path = os.path.realpath(os.path.join(root, relative_path.removeprefix(LOOMA_CONTENT_PREFIX)))
    if os.path.commonpath([root, path]) != root:
        raise PageSourceError("path_outside_content_dir", relative_path)
    return path


def extract_page_texts(pdf_stream, first_page: int = 1, last_page: int | None = None) -> list[str]:
    """Returns the text layer of each page in a range, in page order (same PyMuPDF call as above).

    Args:
        pdf_stream: the PDF as bytes or a binary stream.
        first_page: first page to read, 1-based.
        last_page: last page to read, inclusive; None reads to the end of the file.

    Returns:
        One string per page; "".join() of a whole file equals extract_text_from_pdf().

    Raises:
        PageSourceError: "unreadable_pdf" for bytes PyMuPDF can't open, "damaged_pdf" for a file it had to
            repair, "page_range_out_of_bounds" for a range outside the file.
    """
    try:
        pdf_document = fitz.open(stream=pdf_stream, filetype="pdf")
    except (RuntimeError, ValueError) as error:  # PyMuPDF raises FileDataError/EmptyFileError (RuntimeError)
        raise PageSourceError("unreadable_pdf", str(error)) from error
    try:
        page_count = pdf_document.page_count
        if page_count == 0:
            raise PageSourceError("unreadable_pdf", "no pages after opening")
        if pdf_document.is_repaired:
            # MuPDF silently "repairs" damaged files: a truncated test PDF opened with 3 pages, 2 of them
            # empty and no error. Partial text must not be indexed as if it were the whole file.
            raise PageSourceError("damaged_pdf", "MuPDF had to repair the file; text may be incomplete")
        last = page_count if last_page is None else last_page
        if first_page < 1 or last > page_count or first_page > last:
            raise PageSourceError("page_range_out_of_bounds",
                                  f"pages {first_page}-{last} requested, file has {page_count}")
        return [pdf_document.load_page(number - 1).get_text() for number in range(first_page, last + 1)]
    finally:
        pdf_document.close()

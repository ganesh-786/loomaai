import io
import re

from langchain_huggingface import HuggingFaceEmbeddings
from pymongo.synchronous.database import Database

from .activity import (Activity, PageSourceError, PdfPageSource, download_pdf, extract_text_from_pdf,
                       parse_looma_int, resolve_content_path)


# Pass one of textbook or mongo. If textbook is None then mongo must be provided and the function will look up the
# textbook for you.
# Returns: english looma.website URL, english local path, nepali looma.website URL, nepali local path, textbook object
def chapter_url_from_id(chapter_id: str, files_dir: str, textbook: dict | None, mongo: Database | None) -> (str, str, dict):
    groups = re.search(r"([1-9]|10|11|12)(EN|ENa|Sa|S|SF|Ma|M|SSa|SS|N|H|V|CS)[0-9]{2}(\.[0-9]{2})?",
                       chapter_id, re.IGNORECASE)
    grade_level = groups[1]  # grade level
    subject = groups[2]
    textbook = textbook if textbook is not None else mongo.textbooks.find_one({"prefix": grade_level + subject})
    url_en = None
    local_path_en = None
    url_np = None
    local_path_np = None
    if textbook['fn'] != '':
        # TODO: remote url_en and url_np are for the whole textbook. We should never embed the whole textbook in the context of a single chapter. Will need to upload final split to looma.website for this
        # local path is correct (for the single chapter)
        url_en = f"https://looma.website/content/textbooks/{textbook['fp']}{textbook['fn']}"
        local_path_en = f"{files_dir}/{textbook["fp"]}{'en'}/{chapter_id}.pdf"
    if textbook['nfn'] != '':
        url_np = f"https://looma.website/content/textbooks/{textbook['fp']}{textbook['nfn']}"
        local_path_np = f"{files_dir}/{textbook["fp"]}{'np'}/{chapter_id}-nepali.pdf"
    return url_en, local_path_en, url_np, local_path_np, textbook


class ChapterActivity(Activity):

    def __init__(self, activity: dict):
        super().__init__(activity)
        groups = re.search(r"([1-9]|10|11|12)(EN|ENa|Sa|S|SF|Ma|M|SSa|SS|N|H|V|CS)[0-9]{2}(\.[0-9]{2})?",
                           activity.get("ID"), re.IGNORECASE)
        grade_level = groups[1]  # grade level
        self.cl_official = int(grade_level)

    def get_text(self, mongo: Database, ) -> str:
        # activity['ID'] is the chapter ID (not the activity objectid)
        _, filename_en, _, filename_np, _ = chapter_url_from_id(self.activity['ID'], files_dir='', textbook=None, mongo=mongo)
        if filename_en is not None:
            with open("data"+filename_en, "rb") as file:
                pdf_stream = io.BytesIO(file.read())
                return extract_text_from_pdf(pdf_stream)

        return ""

    def embed(self, mongo: Database, embeddings: HuggingFaceEmbeddings) -> list[float]:
        return embeddings.embed_query(self.get_text(mongo))

    def payload(self) -> dict:

        return {
            "collection": "activities",
            "source_id": str(self.activity['_id']),
            "title": self.activity['dn'],
            "ft": "chapter",
            "chapter_id": self.activity['ID'],
            "cl_official": self.cl_official,
        }

    def page_source(self, mongo: Database, content_dir: str) -> PdfPageSource:
        """Locates this chapter's English pages inside its textbook PDF (PDF ingest, issue #2).

        Reads the whole textbook from the local content folder instead of a split copy, so page numbers and
        the file's sha256 match what Looma serves (its viewer opens the chapter at chapters.pn). The page
        range uses the same arithmetic as split.py:79-81, including Skip's Feb 2025 len=0 skip.

        Args:
            mongo: the looma database (read only: textbooks.find_one, chapters.find_one).
            content_dir: the local copy of Looma's content folder.

        Raises:
            PageSourceError: "textbook_not_found", "textbook_record_incomplete", "no_english_textbook",
                "chapter_not_found", "no_page_range" or "path_outside_content_dir".
        """
        chapter_id = self.activity['ID']
        try:
            _, _, _, _, textbook = chapter_url_from_id(chapter_id, files_dir='', textbook=None, mongo=mongo)
        except TypeError as error:  # find_one returned None, so chapter_url_from_id indexes None
            raise PageSourceError("textbook_not_found", chapter_id) from error
        except KeyError as error:
            raise PageSourceError("textbook_record_incomplete", f"{chapter_id}: no {error}") from error
        file_name = textbook.get('fn') or ''
        if not file_name:
            raise PageSourceError("no_english_textbook", textbook.get('prefix', chapter_id))

        chapter = mongo.chapters.find_one({"_id": chapter_id})
        if chapter is None:
            raise PageSourceError("chapter_not_found", chapter_id)
        first_page = parse_looma_int(chapter.get('pn'))
        page_count = parse_looma_int(chapter.get('len'))
        if first_page is None or page_count is None or first_page < 1 or page_count < 1:
            raise PageSourceError("no_page_range", f"{chapter_id}: pn={chapter.get('pn')!r} len={chapter.get('len')!r}")

        relative_path = textbook['fp'] + file_name
        return PdfPageSource(relative_path, resolve_content_path(content_dir, relative_path),
                             first_page, first_page + page_count - 1)

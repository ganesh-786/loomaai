from langchain_huggingface import HuggingFaceEmbeddings
from pymongo.synchronous.database import Database

from .activity import (LOOMA_CONTENT_PREFIX, Activity, PageSourceError, PdfPageSource, download_pdf,
                       extract_text_from_pdf, resolve_content_path)

DEFAULT_PDF_FOLDER = '../content/pdfs/'  # same default as get_text() below uses when fp is missing


class PdfActivity(Activity):
    def get_text(self, mongo: Database) -> str:
        fp = self.activity['fp'] if 'fp' in self.activity else '../content/pdfs/'
        url = f"https://looma.website/{fp}{self.activity['fn']}"
        pdf_stream = download_pdf(url)
        return extract_text_from_pdf(pdf_stream)
    
    def embed(self, mongo: Database, embeddings: HuggingFaceEmbeddings) -> list[float]:


        return embeddings.embed_query(self.get_text(mongo))

    def payload(self) -> dict:
        return {
            "collection": "activities",
            "source_id": str(self.activity['_id']),
            "title": self.activity['dn'],
            "ft": "pdf",
        }

    def page_source(self, mongo: Database | None, content_dir: str) -> PdfPageSource:
        """Locates this PDF in the local content folder; all of its pages are read (PDF ingest, issue #2).

        Unlike get_text(), nothing is downloaded. A null fp gets the same default folder as a missing one.

        Args:
            mongo: unused; kept so every activity type has the same page_source(mongo, content_dir) call.
            content_dir: the local copy of Looma's content folder.

        Raises:
            PageSourceError: "no_file_name" when fn is missing or empty, "path_outside_content_dir".
        """
        file_name = self.activity.get('fn') or ''
        if not file_name:
            raise PageSourceError("no_file_name", str(self.activity.get('_id')))
        folder = self.activity.get('fp') or DEFAULT_PDF_FOLDER
        relative_path = (folder + file_name).removeprefix(LOOMA_CONTENT_PREFIX)
        return PdfPageSource(relative_path, resolve_content_path(content_dir, relative_path))

"""The records that flow between stages. Import only; plain frozen dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    """One searchable resource: an `activities` record, cleaned by F4. Search returns item ids, which Looma-II
    turns back into buttons (`LOOMA.makeButton`)."""

    item_id: str
    ft: str
    title_en: str                 # from dn
    title_np: str                 # from ndn
    subject: str                  # normalized key1, or the subject of a linked chapter's textbook
    taxonomy: tuple[str, ...]     # key1..key4, cleaned, empty levels dropped
    ch_ids: tuple[str, ...]       # valid chapter ids from ch_id and nch_id
    chapter_id: str | None        # for ft == "chapter": the chapter it represents
    grade_lo: int | None
    grade_hi: int | None
    grade_source: str
    src: str
    lang: str                     # "en" | "np" | "both" | "unknown"
    cehrd: bool                   # file under ../content/CEHRD/: shown only on the CEHRD server
    mongo_id: str | None          # lessons and games: id of the record holding the text


@dataclass(frozen=True)
class TextPiece:
    """A piece of extracted text before chunking (F3), cleaned and language-tagged by F4 and F5."""

    item_id: str
    source: str                   # "title" | "lesson" | "game" | "document" | "captions" | "textbook"
    order: int                    # position within the item and source (slide, page, caption block)
    text: str
    lang: str = "none"            # "en" | "np" | "mixed" | "none"
    page: int | None = None       # 1-based page in the source PDF (what Looma's viewer opens with #page=)
    t_start: float | None = None  # seconds into the video
    expect_nepali: bool = False   # the source is meant to be Nepali (ndn, a Nepali textbook, ...)
    # Page metadata (issue #4): how this text was made. Empty strings for text that does not come from a PDF page.
    printed_page: str | None = None  # the number printed on the page; can differ from `page` (10S04: 77 vs 73)
    text_method: str = ""            # PDF pages: "text" | "ocr" | "transcript"
    source_run: str = ""             # transcripts: the run that made the text, e.g. "D-claude-direct-read"
    source_model: str = ""           # transcripts: the model id, when the run records one
    review_status: str = ""          # transcripts: "reviewed" | "unreviewed"; "" = not AI-made text


@dataclass(frozen=True)
class Passage:
    """A chunk ready to embed and index (F6). `passage_id` is `<item_id>:<lang>:<n>`.

    The page metadata fields are copied from the TextPiece the chunk came from (see TextPiece).
    """

    passage_id: str
    item_id: str
    lang: str
    source: str
    text: str
    page: int | None
    t_start: float | None
    n_tokens: int
    printed_page: str | None = None
    text_method: str = ""
    source_run: str = ""
    source_model: str = ""
    review_status: str = ""

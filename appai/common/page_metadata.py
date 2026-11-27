"""Looma metadata and provenance for each ingested PDF page (fork issue #4, PDF ingest).

What: builds the page record (schema looma.pdf_page/1): where the text came from (file, sha256, PDF page,
printed page, text method, transcript run and review status) and what Looma says about the item (chapter
ids, title, subject keys, language, grade with the source of that grade).
Why: every search result must be traceable to its source and to whether a person checked its text; the team
plan says "only checked pieces are indexed". Looma's grade fields are messy (BOM-prefixed keys, strings,
0/0), so the grade used here records how it was found and keeps the raw values.
How: imported by appai/cli/ingest_pdfs.py; no command of its own.
Inputs: the activity document, its payload() and the per-page extraction results.
Outputs: plain dicts, written as JSON lines by the CLI.
Side effects: none. Nothing here writes to Mongo; curated fields (cl_lo, cl_hi, ch_id, ...) are only read.
"""

import re
from collections import Counter

from .activity import parse_looma_int
from .activity_chapter import ChapterActivity

SCHEMA = "looma.pdf_page/1"
GRADE_MIN, GRADE_MAX = 1, 12          # Looma grades; 0 is how many documents say "not set"
GRADE_FIELDS = ("cl_lo", "cl_hi")
BOM = "﻿"                         # 87 pdf/worksheet docs have a key "﻿cl_lo" (local looma-db, 2026-11-27)
SUBJECT_FIELDS = ("key1", "key2", "key3", "key4")
MIN_OFFSET_VOTES = 3                   # printed-page offset needs 3 agreeing footer numbers ...
RUNNER_UP_FACTOR = 2                   # ... and at least twice the votes of the next offset
CONSTANT_NUMBER_SHARE = 0.5            # a number on half the footer lines is footer text, not a page number
# A printed page is at least half its PDF page (front matter is never half a book). OCR often keeps only the
# last digits ("4" for printed 174); without this rule those votes agreed on wrong offsets 54, 174 and 434 in
# 3 of 19 Grade 10 Science chapters, 45 of 108 inferred pages wrong (catalog run 2026-11-27). With it, 4 chapters
# get offset 4 and 15 get none; 0 wrong.
MIN_PRINTED_SHARE = 0.5
FOOTER_NUMBER = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")


def parse_grade(value) -> int | None:
    """Returns a grade 1-12 from an int, digit string or integral double; None for 0, out of range or text."""
    grade = parse_looma_int(value)
    return grade if grade is not None and GRADE_MIN <= grade <= GRADE_MAX else None


def chapter_grade(chapter_id) -> int | None:
    """Grade of a chapter id such as "10S04" or "11SS04.01", parsed by ChapterActivity's own pattern."""
    if not isinstance(chapter_id, str) or not chapter_id:
        return None
    try:
        return parse_grade(ChapterActivity({"ID": chapter_id}).cl_official)
    except TypeError:  # the id doesn't match ChapterActivity's pattern
        return None


def normalize_ch_ids(item: dict) -> list[str]:
    """Chapter ids of an item as a list: a chapter's own ID; ch_id as string or array (deduplicated) otherwise."""
    if item.get("ft") == "chapter":
        return [item["ID"]] if isinstance(item.get("ID"), str) else []
    raw = item.get("ch_id")
    values = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def _grade_field(item: dict, field: str) -> tuple[int | None, bool]:
    """Reads cl_lo or cl_hi and its BOM-prefixed twin; returns (grade, conflict)."""
    plain, prefixed = parse_grade(item.get(field)), parse_grade(item.get(BOM + field))
    if plain is not None and prefixed is not None and plain != prefixed:
        return None, True
    return (plain if plain is not None else prefixed), False


def item_grade(item: dict) -> dict:
    """Grade range of an item and where it came from.

    Order: a chapter's id ("chapter_id"); else valid cl_lo/cl_hi or their BOM twins ("activity_cl"); else the
    range of the linked chapters' grades ("linked_chapters"); else "none".

    Returns:
        {"lo", "hi", "source", "raw" (the grade fields as stored), "conflict" (plain and BOM keys disagree)}.
    """
    raw = {key: item[key] for key in (*GRADE_FIELDS, *(BOM + f for f in GRADE_FIELDS)) if key in item}
    if item.get("ft") == "chapter":
        grade = chapter_grade(item.get("ID"))
        return {"lo": grade, "hi": grade, "source": "chapter_id" if grade else "none", "raw": raw,
                "conflict": False}
    low, low_conflict = _grade_field(item, "cl_lo")
    high, high_conflict = _grade_field(item, "cl_hi")
    conflict = low_conflict or high_conflict
    if not conflict and low is not None and high is not None and low <= high:
        return {"lo": low, "hi": high, "source": "activity_cl", "raw": raw, "conflict": False}
    linked = [grade for grade in map(chapter_grade, normalize_ch_ids(item)) if grade is not None]
    if linked:
        return {"lo": min(linked), "hi": max(linked), "source": "linked_chapters", "raw": raw, "conflict": conflict}
    return {"lo": None, "hi": None, "source": "none", "raw": raw, "conflict": conflict}


def printed_page_offset(removed_lines: list[dict], pdf_pages: list[int]) -> dict:
    """Votes for the offset between PDF page and printed page using numbers in removed footer lines.

    The PDFs define no page labels and OCR keeps the footer number on only some pages (7 of 38 in the
    10S04 pilot), so each number n on a removed line votes for offset = pdf_page - n.

    Args:
        removed_lines: the cleaning report's removed lines ({"page_index", "line", ...}).
        pdf_pages: PDF page number for each page_index.

    A number found on at least half of the removed running lines is part of the footer's own text (the 10
    of "Grade 10") and does not vote; counting it let offset 4 lose 4:3 on the pilot (changed 2026-11-27).
    A number below half its PDF page is a truncated OCR fragment and does not vote either.

    Returns:
        {"offset": int or None, "votes": top votes, "runner_up": next votes, "ignored_numbers": [...]}.
        The offset is None unless the top offset has 3+ votes and at least twice the runner-up's.
    """
    running_lines = [r for r in removed_lines if r.get("rule") == "running_line"]
    lines_with = Counter(n for r in running_lines for n in set(int(x) for x in FOOTER_NUMBER.findall(r["line"])))
    ignored = sorted(n for n, count in lines_with.items() if count >= CONSTANT_NUMBER_SHARE * len(running_lines))
    votes: Counter = Counter()
    for removed in removed_lines:
        pdf_page = pdf_pages[removed["page_index"]]
        for number in map(int, FOOTER_NUMBER.findall(removed["line"])):
            if removed.get("rule") == "running_line" and number in ignored:
                continue
            if number < 1 or number < pdf_page * MIN_PRINTED_SHARE:
                continue  # a truncated number ("4" for printed 174) is not a page number
            votes[pdf_page - number] += 1
    ranked = votes.most_common(2)
    top = ranked[0] if ranked else (None, 0)
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    accepted = top[1] >= MIN_OFFSET_VOTES and top[1] >= RUNNER_UP_FACTOR * runner_up
    return {"offset": top[0] if accepted else None, "votes": top[1], "runner_up": runner_up,
            "ignored_numbers": ignored}


def resolve_printed_page(pdf_page: int, transcript_printed: str | None, offset_vote: dict) -> tuple[int | None, str]:
    """Printed page for display: the transcript's number, else PDF page minus the voted offset, else none.

    Links keep using the PDF page, because Looma's viewer opens a chapter at chapters.pn (a PDF page).

    Returns:
        (printed page or None, "transcript" | "footer_offset" | "none").
    """
    from_transcript = parse_looma_int(transcript_printed)
    if from_transcript is not None and from_transcript >= 1:
        return from_transcript, "transcript"
    offset = offset_vote.get("offset")
    if offset is not None and pdf_page - offset >= 1:
        return pdf_page - offset, "footer_offset"
    return None, "none"


def build_page_record(*, run_id: str, item: dict, base: dict, lang: str | None, relative_path: str,
                      file_sha256: str, pdf_page: int, printed_page: tuple[int | None, str], text: str,
                      fallback_reason: str | None, transcript, cleaning: dict) -> dict:
    """Builds one page record (schema looma.pdf_page/1).

    Args:
        run_id: the ingest run.
        item: the activity document (read only).
        base: the activity's payload() (collection, source_id, title) as embed.py already uses it.
        lang: the language read ("en" for a chapter's English textbook pages; activities.lang otherwise).
        relative_path / file_sha256 / pdf_page: the source file and page.
        printed_page: (number, source) from resolve_printed_page().
        text: the cleaned text.
        fallback_reason: why the text layer was used instead of a transcript, or None.
        transcript: the TranscriptPage used, or None.
        cleaning: what the cleaning step did to this page.

    Returns:
        The record dict; "checked" is True only for an approved transcript.
    """
    review_status = transcript.review_status if transcript else "unchecked"
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "record_id": f"{base['source_id']}:{lang or 'unknown'}:p{pdf_page}",
        "source": {"collection": base["collection"], "item_id": base["source_id"], "ft": item.get("ft"),
                   "file": relative_path, "file_sha256": file_sha256, "pdf_page": pdf_page,
                   "printed_page": printed_page[0], "printed_page_source": printed_page[1]},
        "looma": {"ch_id": normalize_ch_ids(item), "dn": base.get("title"), "ndn": item.get("ndn"), "lang": lang,
                  "subject": {field: item.get(field) for field in SUBJECT_FIELDS}, "grade": item_grade(item)},
        "text": text,
        "text_method": "transcript" if transcript else "text_layer",
        "fallback_reason": fallback_reason,
        "transcript": ({"run": transcript.run, "model": transcript.model, "review_status": transcript.review_status,
                        "line": transcript.line_no} if transcript else None),
        "review_status": review_status,
        "checked": review_status == "approved",
        "cleaning": cleaning,
        "quality": {"chars": len(text), "words": len(text.split())},
    }

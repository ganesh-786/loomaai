"""Reviewed page transcripts used in place of a PDF's text layer (fork issue #2, PDF ingest).

What: loads transcript runs from disk, checks every row, binds each row to the exact PDF it was made from (by
sha256) and decides per page whether a transcript may replace the text layer.
Why: the text layer of Looma's scanned textbooks drops symbols ("2×23" becomes "223") and figure captions; a
reviewed transcript of a page keeps them. Transcripts are read from files at build time only, so nothing extra
runs on the Looma Box.
How: imported by appai/cli/ingest_pdfs.py; no command of its own.
Inputs: transcript run folders (kept outside the repository, like the content folder), each holding:
    report.json  {"run": str, "method": {"model" | "transcriber": str, "review_status": "<status>[: note]"},
                  "inputs": [{"file": <path relative to the content folder>, "sha256": str}, ...]}
    pages.jsonl  one row per page: {"file", "page" (1-based PDF page), "text", "printed_page"?, "review_status"?}
    A row's review_status overrides the run's. Statuses: approved | unreviewed | rejected.
Outputs: a TranscriptIndex; problems found while loading are listed in TranscriptIndex.problems.
Side effects: reads files only.
"""

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)

REVIEW_STATUSES = ("approved", "unreviewed", "rejected")
HEADER_FILE = "report.json"
PAGES_FILE = "pages.jsonl"


@dataclass(frozen=True)
class TranscriptPage:
    """One transcribed PDF page and where it came from."""
    run: str
    model: str | None
    review_status: str
    file: str
    file_sha256: str
    page: int
    text: str
    printed_page: str | None
    line_no: int


@dataclass(frozen=True)
class TranscriptChoice:
    """The transcript to use for a page, or None with the reason the text layer is kept."""
    page: TranscriptPage | None
    fallback_reason: str | None


def _review_status(value) -> str | None:
    """Reads "unreviewed: no human has checked..." as "unreviewed"; None for anything not in REVIEW_STATUSES."""
    if not isinstance(value, str):
        return None
    status = value.split(":", 1)[0].strip().lower()
    return status if status in REVIEW_STATUSES else None


class TranscriptIndex:
    """All usable transcript rows, looked up by (file sha256, PDF page)."""

    def __init__(self):
        self._by_sha = defaultdict(list)
        self._by_file = defaultdict(list)
        self.problems: list[dict] = []
        self.runs: list[dict] = []

    def add(self, page: TranscriptPage) -> None:
        self._by_sha[(page.file_sha256, page.page)].append(page)
        self._by_file[(page.file, page.page)].append(page)

    def problem(self, run_dir: str, line: int | None, reason: str, detail: str) -> None:
        self.problems.append({"run_dir": run_dir, "line": line, "reason": reason, "detail": detail})
        logger.warning("transcript %s line %s: %s (%s)", run_dir, line, reason, detail)

    def choose(self, file: str, file_sha256: str, page: int, allow_unreviewed: bool) -> TranscriptChoice:
        """Picks the transcript for one PDF page, applying the review gate.

        Args:
            file: the PDF path relative to the content folder.
            file_sha256: sha256 of the local PDF; a transcript made from other bytes never matches.
            page: 1-based PDF page.
            allow_unreviewed: use unreviewed rows too (TRANSCRIPTS_ALLOW_UNREVIEWED=1); rejected rows never.

        Returns:
            The chosen page, or a fallback reason: no_transcript, transcript_stale_sha256,
            transcript_unreviewed, transcript_rejected or transcript_conflict.
        """
        candidates = self._by_sha.get((file_sha256, page), [])
        if not candidates:
            stale = self._by_file.get((file, page), [])
            return TranscriptChoice(None, "transcript_stale_sha256" if stale else "no_transcript")
        approved = [c for c in candidates if c.review_status == "approved"]
        unreviewed = [c for c in candidates if c.review_status == "unreviewed"]
        usable = approved or (unreviewed if allow_unreviewed else [])
        if not usable:
            return TranscriptChoice(None, "transcript_unreviewed" if unreviewed else "transcript_rejected")
        if len({c.text for c in usable}) > 1:
            return TranscriptChoice(None, "transcript_conflict")
        return TranscriptChoice(usable[0], None)


def _read_header(run_dir: str, index: TranscriptIndex) -> dict | None:
    """Returns {run, model, review_status, sha_by_file} or None (problem recorded) for an unusable header."""
    path = os.path.join(run_dir, HEADER_FILE)
    try:
        with open(path, encoding="utf-8") as handle:
            header = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        index.problem(run_dir, None, "transcript_header_invalid", f"{HEADER_FILE}: {error}")
        return None
    method = header.get("method") if isinstance(header, dict) else None
    run = header.get("run") if isinstance(header, dict) else None
    status = _review_status(method.get("review_status")) if isinstance(method, dict) else None
    inputs = header.get("inputs") if isinstance(header, dict) else None
    sha_by_file = {}
    if isinstance(inputs, list):
        for entry in inputs:
            if isinstance(entry, dict) and isinstance(entry.get("file"), str) and isinstance(entry.get("sha256"), str):
                sha_by_file[entry["file"]] = entry["sha256"].lower()
    if not (isinstance(run, str) and run and status and sha_by_file):
        index.problem(run_dir, None, "transcript_header_invalid",
                      "needs run, method.review_status (approved|unreviewed|rejected) and inputs[{file, sha256}]")
        return None
    model = method.get("model") or method.get("transcriber")
    return {"run": run, "model": model if isinstance(model, str) else None,
            "review_status": status, "sha_by_file": sha_by_file}


def _row_problem(row, sha_by_file: dict) -> str | None:
    """Describes what is wrong with a pages.jsonl row, or None when it is usable."""
    if not isinstance(row, dict):
        return "row is not a JSON object"
    if row.get("file") not in sha_by_file:
        return f"file {row.get('file')!r} is not in the run's inputs"
    page = row.get("page")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        return f"page {page!r} is not a positive integer"
    if not isinstance(row.get("text"), str) or not row["text"].strip():
        return "text is missing or empty"
    if "review_status" in row and _review_status(row["review_status"]) is None:
        return f"review_status {row['review_status']!r} is not one of {REVIEW_STATUSES}"
    return None


def load_transcript_runs(run_dirs: Iterable[str]) -> TranscriptIndex:
    """Loads transcript runs; bad headers skip their run and bad rows skip their page, each reported.

    Args:
        run_dirs: folders holding report.json and pages.jsonl.

    Returns:
        A TranscriptIndex with every usable row, plus `problems` and a per-run summary in `runs`.
    """
    index = TranscriptIndex()
    for run_dir in run_dirs:
        header = _read_header(run_dir, index)
        if header is None:
            continue
        loaded = rejected = 0
        try:
            with open(os.path.join(run_dir, PAGES_FILE), encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except OSError as error:
            index.problem(run_dir, None, "transcript_header_invalid", f"{PAGES_FILE}: {error}")
            continue
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                row, reason = None, f"not JSON: {error}"
            else:
                reason = _row_problem(row, header["sha_by_file"])
            if reason:
                index.problem(run_dir, line_no, "transcript_malformed", reason)
                rejected += 1
                continue
            printed = row.get("printed_page")
            index.add(TranscriptPage(
                run=header["run"], model=header["model"],
                review_status=_review_status(row["review_status"]) if "review_status" in row else header["review_status"],
                file=row["file"], file_sha256=header["sha_by_file"][row["file"]], page=row["page"],
                text=row["text"], printed_page=str(printed) if printed is not None else None, line_no=line_no))
            loaded += 1
        index.runs.append({"run": header["run"], "dir": run_dir, "model": header["model"],
                           "review_status": header["review_status"], "rows_loaded": loaded,
                           "rows_rejected": rejected})
    return index

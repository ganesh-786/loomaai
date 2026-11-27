"""Page transcripts: reviewed text for single PDF pages, used in place of the PDF's own text layer.

Why: on pages with symbols, figure text or captions, the embedded text layer and OCR lose meaning ("46 (2×23)"
became "46 (223)" on Grade 10 Science chapter 10S04). A transcript made from the page image keeps it. Issue #2 on
ganesh-786/loomaai, parent #1.

How it is used: import only. F3 (stages/f03_extract.py) calls `load_transcripts()` once per run and asks the index
for each PDF page it extracts.

Input: every `*.jsonl` file in the transcripts folder (setting TRANSCRIPTS_DIR), read in name order. One JSON object
per line, one PDF page per object:
    required  file_sha256 (64 hex), page (1-based PDF page, int), text (non-empty), run (non-empty),
              review_status ("reviewed" | "unreviewed" | "rejected")
    optional  file (path under the content folder, used to tell a stale transcript from an unrelated one),
              printed_page, method, model, lang
A page is matched by the sha256 of the PDF file, so a changed PDF never picks up an old transcript.

Output: a `TranscriptIndex` of usable pages, with counts and a list of problems (file, line, reason).
Rules: "rejected" rows are never used; "unreviewed" rows only when allowed (AI output stays a suggestion until a
person approves it); for one page, a reviewed row replaces unreviewed ones; two different texts with the same status
are both dropped, so the page falls back to the PDF's own text; a malformed line, or a file that cannot be read, is
reported and skipped. Loading never stops a build; `check_quality()` (called by F3) does, when a file cannot be read
or more than 1% of rows are malformed.
Side effects: reads files only.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REVIEW_STATUSES = frozenset({"reviewed", "unreviewed", "rejected"})
MAX_MALFORMED_SHARE = 0.01  # above 1% bad rows the export is probably broken: stop the run (check_quality)
_SHA256 = re.compile(r"[0-9a-f]{64}")


class TranscriptError(ValueError):
    """A transcript row is malformed. The message names the field to fix."""


@dataclass(frozen=True)
class TranscriptPage:
    """The transcribed text of one PDF page, with where it came from."""

    file_sha256: str
    page: int                     # 1-based page in the PDF, as PyMuPDF counts it
    text: str
    run: str                      # the transcription run, e.g. "D-claude-direct-read"
    review_status: str            # "reviewed" | "unreviewed" | "rejected"
    file: str = ""                # path under the content folder, e.g. "textbooks/Class10/Science/....pdf"
    printed_page: str | None = None  # the number printed on the page, which can differ from `page`
    method: str = ""
    model: str = ""
    lang: str = ""


@dataclass
class TranscriptIndex:
    """Usable transcript pages keyed by (file sha256, page), plus what was skipped and why."""

    pages: dict[tuple[str, int], TranscriptPage] = field(default_factory=dict)
    counts: Counter = field(default_factory=Counter)
    problems: list[dict[str, Any]] = field(default_factory=list)

    def lookup(self, file_sha256: str | None, page: int) -> TranscriptPage | None:
        """The usable transcript for this page of the file with this sha256, or None."""
        if not file_sha256:
            return None
        return self.pages.get((file_sha256, page))

    def pages_of(self, file_sha256: str | None) -> frozenset[int]:
        """The 1-based pages of this file that have a usable transcript (F3 skips OCR on them)."""
        if not file_sha256:
            return frozenset()
        return frozenset(page for sha, page in self.pages if sha == file_sha256)

    def __len__(self) -> int:
        return len(self.pages)


def check_quality(index: TranscriptIndex, max_malformed_share: float = MAX_MALFORMED_SHARE) -> None:
    """Stop the run when the transcripts look broken, rather than build quietly without them.

    Skipping a few bad lines is safe: those pages fall back to the PDF's own text. A file that cannot be read, or many
    bad lines, usually means a broken export, and a bundle built from it would silently lose the transcripts.

    Args:
        index: the loaded transcripts.
        max_malformed_share: the largest share of malformed rows still accepted (default 1%).

    Raises:
        TranscriptError: if any transcript file could not be read, or too many rows are malformed.
    """
    unreadable = index.counts["files_unreadable"]
    if unreadable:
        raise TranscriptError(f"{unreadable} transcript file(s) could not be read; see the F3 report")
    rows, malformed = index.counts["rows"], index.counts["rows_malformed"]
    if rows and malformed / rows > max_malformed_share:
        raise TranscriptError(f"{malformed} of {rows} transcript rows are malformed "
                              f"(limit {max_malformed_share:.0%}); see the F3 report")


def _optional_text(raw: dict, name: str) -> str:
    value = raw.get(name)
    return value.strip() if isinstance(value, str) else ""


def parse_row(raw: Any) -> TranscriptPage:
    """Validate one decoded JSON line.

    Args:
        raw: the decoded line; must be a JSON object.

    Returns:
        The transcript page. The sha256 is lower-cased to match the pipeline's own hashes.

    Raises:
        TranscriptError: naming the first field that is missing or invalid.
    """
    if not isinstance(raw, dict):
        raise TranscriptError("a row must be a JSON object")
    sha = raw.get("file_sha256")
    if not isinstance(sha, str) or not _SHA256.fullmatch(sha.strip().lower()):
        raise TranscriptError("file_sha256 must be 64 hexadecimal characters")
    page = raw.get("page")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:  # bool is an int subclass in Python
        raise TranscriptError("page must be a whole number of 1 or more")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise TranscriptError("text must be a non-empty string")
    run = raw.get("run")
    if not isinstance(run, str) or not run.strip():
        raise TranscriptError("run must be a non-empty string")
    status = raw.get("review_status")
    if status not in REVIEW_STATUSES:
        raise TranscriptError(f"review_status must be one of {', '.join(sorted(REVIEW_STATUSES))}")
    printed = raw.get("printed_page")
    return TranscriptPage(
        file_sha256=sha.strip().lower(), page=page, text=text, run=run.strip(), review_status=status,
        file=_optional_text(raw, "file"),
        printed_page=str(printed).strip() if printed not in (None, "") else None,
        method=_optional_text(raw, "method"), model=_optional_text(raw, "model"), lang=_optional_text(raw, "lang"),
    )


def _read_rows(path: Path, index: TranscriptIndex) -> list[TranscriptPage]:
    """Valid rows of one file; malformed lines go to `index.problems`. Blank lines are ignored."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        index.counts["files_unreadable"] += 1
        index.problems.append({"file": path.name, "line": None, "reason": f"{type(exc).__name__}: {exc}"[:300]})
        return []
    rows = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        index.counts["rows"] += 1
        try:
            rows.append(parse_row(json.loads(line)))
        except (json.JSONDecodeError, TranscriptError) as exc:
            index.counts["rows_malformed"] += 1
            index.problems.append({"file": path.name, "line": number, "reason": str(exc)[:300]})
    return rows


def load_transcripts(folder: Path, allow_unreviewed: bool) -> TranscriptIndex:
    """Read every `*.jsonl` file in `folder` and keep the rows that may be used.

    Args:
        folder: the transcripts folder. A folder that does not exist gives an empty index.
        allow_unreviewed: also use rows whose review_status is "unreviewed".

    Returns:
        The index. Its counts: files, files_unreadable, rows, rows_malformed, rows_rejected,
        rows_unreviewed_skipped, rows_superseded, rows_duplicate, pages_conflicting, pages_usable.
    """
    index = TranscriptIndex()
    index.counts["files"] = 0
    try:
        files = sorted(folder.glob("*.jsonl")) if folder.is_dir() else []
    except OSError as exc:  # e.g. a folder the container user may not list: report it, build without transcripts
        index.problems.append({"file": None, "line": None, "reason": f"{type(exc).__name__}: {exc}"[:300]})
        files = []
    candidates: dict[tuple[str, int], list[TranscriptPage]] = {}
    for path in files:
        index.counts["files"] += 1
        for page in _read_rows(path, index):
            if page.review_status == "rejected":
                index.counts["rows_rejected"] += 1
            elif page.review_status == "unreviewed" and not allow_unreviewed:
                index.counts["rows_unreviewed_skipped"] += 1
            else:
                candidates.setdefault((page.file_sha256, page.page), []).append(page)
    for key, pages in candidates.items():
        reviewed = [page for page in pages if page.review_status == "reviewed"]
        if reviewed and len(reviewed) < len(pages):
            # A person checked one reading; it replaces the readings nobody checked.
            index.counts["rows_superseded"] += len(pages) - len(reviewed)
            pages = reviewed
        texts = {page.text for page in pages}
        if len(texts) > 1:
            # Two readings disagree and nothing says which is right: use neither, so the page falls back to the
            # PDF's own text and a person can decide.
            index.counts["pages_conflicting"] += 1
            index.problems.append({"file": None, "line": None,
                                   "reason": f"conflict: {len(texts)} different texts for page {key[1]} of {key[0]}"})
            continue
        index.counts["rows_duplicate"] += len(pages) - 1
        index.pages[key] = pages[0]
    index.counts["pages_usable"] = len(index.pages)
    return index

"""Caption files (SRT and WebVTT) to timed text.

Import only; pure functions plus one file read. Handles `HH:MM:SS,mmm` and `MM:SS.mmm` timestamps (the prototype's
parser missed hour-long videos, audit B13), cue settings after the arrow, inline tags such as `<c>` and `<i>`,
`NOTE` blocks, and the repeated lines that automatic captions produce. Cues are grouped into blocks of about
`max_chars` characters, each keeping the start time of its first cue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_TIMING = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s*-->")
_TAG = re.compile(r"<[^>]+>")
DEFAULT_BLOCK_CHARS = 700  # about one passage of text per block


@dataclass(frozen=True)
class Cue:
    start: float  # seconds
    text: str


def _seconds(match: re.Match) -> float:
    hours, minutes, seconds, millis = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_cues(text: str) -> list[Cue]:
    """Cues from SRT or WebVTT text, in file order, without tags or repeated lines."""
    cues: list[Cue] = []
    start: float | None = None
    lines: list[str] = []
    previous_line = ""

    def flush() -> None:
        if start is not None and lines:
            cues.append(Cue(start, " ".join(lines)))

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        timing = _TIMING.match(line)
        if timing:
            flush()
            start, lines = _seconds(timing), []
        elif not line:
            flush()
            start, lines = None, []
        elif start is not None:
            cleaned = _TAG.sub("", line).strip()
            if cleaned and cleaned != previous_line:
                lines.append(cleaned)
                previous_line = cleaned
    flush()
    return cues


def group_cues(cues: list[Cue], max_chars: int = DEFAULT_BLOCK_CHARS) -> list[Cue]:
    """Join consecutive cues into blocks of at most about `max_chars` characters."""
    blocks: list[Cue] = []
    block_start, parts, size = None, [], 0
    for cue in cues:
        if parts and size + len(cue.text) > max_chars:
            blocks.append(Cue(block_start, " ".join(parts)))
            parts, size = [], 0
        if not parts:
            block_start = cue.start
        parts.append(cue.text)
        size += len(cue.text) + 1
    if parts:
        blocks.append(Cue(block_start, " ".join(parts)))
    return blocks


def read_captions(path: Path, max_chars: int = DEFAULT_BLOCK_CHARS) -> list[Cue]:
    return group_cues(parse_cues(path.read_text(encoding="utf-8", errors="replace")), max_chars)

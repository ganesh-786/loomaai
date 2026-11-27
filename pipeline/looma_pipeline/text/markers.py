"""Page-transcript markers to plain text, so figure, table and diagram text is searchable without tag noise.

Why: a page transcript (extractors/transcripts.py) marks text that is not running prose: captions, words inside
figures, tables, concept maps, blanks for students to fill, and labels the figure cuts off. Embedded as they are, the
tags become noise in vectors and show up in result snippets. Issue #3 on ganesh-786/loomaai, parent #1.

How it is used: import only; pure functions. F3 calls `clean_markers()` on each transcript page it uses.

Marker spec v1 (the conventions of run D, in its report.json) and what each becomes:
    [Figure 4.6: Structure of DNA]          -> Figure 4.6: Structure of DNA   (the label stays: "figure 4.6" is a query)
    [Figure text: a; b]  [Callouts: a; b]
    [Screenshot text: a; b]                 -> a; b
    [Table] / [End table] lines             -> removed; rows "a | b |  |" inside become "a; b" (empty cells dropped)
    [Concept map] / [End concept map] lines -> removed; arrows (→) stay, they carry the meaning
    [blank]  [illegible]                    -> removed
    nucleosi[cut off]                       -> nucleosi                       (the visible letters stay)
Any other [...] is left as it is, counted as "unknown" and returned, because it may be real text such as "[H+]".
Input: one page of transcript text. Output: the cleaned text, counts per marker type and the unknown brackets.
Side effects: none.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

_INLINE_REMOVED = {"cut_off": re.compile(r"\[cut off\]"), "blank": re.compile(r"\[blank\]"),
                   "illegible": re.compile(r"\[illegible\]")}
# The figure number must start with a digit; otherwise "[Figure text: ...]" would be read as a caption.
_FIGURE_CAPTION = re.compile(r"\[(Figure\s+\d[\w.\-]*):\s*([^\[\]]*)\]")
_CONTENT_TAGS = {"figure_text": re.compile(r"\[Figure text:\s*([^\[\]]*)\]"),
                 "callouts": re.compile(r"\[Callouts:\s*([^\[\]]*)\]"),
                 "screenshot_text": re.compile(r"\[Screenshot text:\s*([^\[\]]*)\]")}
_BLOCKS = {"[Table]": ("[End table]", "table"), "[Concept map]": ("[End concept map]", "concept_map")}
_UNKNOWN = re.compile(r"\[[^\[\]\n]{1,80}\]")
_SPACES = re.compile(r"[ \t]{2,}")


@dataclass(frozen=True)
class MarkerResult:
    """Cleaned page text and what was found in it."""

    text: str
    counts: Counter = field(default_factory=Counter)   # per marker type, e.g. {"figure_caption": 3, "blank": 1}
    unknown: list[str] = field(default_factory=list)   # brackets that matched no marker, left in the text


def _table_row(line: str) -> str:
    """'Wall | yes | ' -> 'Wall; yes': cells joined with '; ', empty cells dropped."""
    return "; ".join(cell.strip() for cell in line.split("|") if cell.strip())


def _clean_blocks(lines: list[str], counts: Counter) -> list[str]:
    """Remove table and concept-map tag lines; turn table rows into plain cell lists."""
    kept: list[str] = []
    open_block: tuple[str, str] | None = None  # (end tag, block name) while inside a block
    for line in lines:
        stripped = line.strip()
        if open_block is None and stripped in _BLOCKS:
            open_block = _BLOCKS[stripped]
            counts[open_block[1]] += 1
            continue
        if open_block is not None and stripped == open_block[0]:
            open_block = None
            continue
        if open_block is not None and open_block[1] == "table":
            line = _table_row(line)
        kept.append(line)
    if open_block is not None:
        counts[f"{open_block[1]}_unclosed"] += 1  # cleaned to the end of the page; reported so a person can check
    return kept


def clean_markers(text: str) -> MarkerResult:
    """Turn transcript markers into plain text (marker spec v1, see the module docstring).

    Args:
        text: one page of transcript text.

    Returns:
        The cleaned text, counts per marker type, and the brackets that matched no marker.
    """
    counts: Counter = Counter()
    # Inline markers first: "[cut off]" can sit inside "[Figure text: ...]", and the outer pattern has no brackets.
    for name, pattern in _INLINE_REMOVED.items():
        text, n = pattern.subn("", text)
        counts[name] += n
    text, n = _FIGURE_CAPTION.subn(lambda m: f"{m.group(1)}: {m.group(2).strip()}", text)
    counts["figure_caption"] += n
    for name, pattern in _CONTENT_TAGS.items():
        text, n = pattern.subn(lambda m: m.group(1).strip(), text)
        counts[name] += n
    lines = _clean_blocks(text.split("\n"), counts)
    lines = [_SPACES.sub(" ", line).strip() for line in lines]
    cleaned = "\n".join(lines).strip()
    unknown = _UNKNOWN.findall(cleaned)
    counts["unknown"] += len(unknown)
    return MarkerResult(cleaned, +counts, unknown)

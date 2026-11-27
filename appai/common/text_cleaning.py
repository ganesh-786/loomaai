"""Cleaning of PDF page text before chunking: text layer (rules C1-C4) and transcripts (rules M1-M9).

What: removes running footers and page numbers, rejoins words split by a line-break hyphen, normalizes Unicode
and whitespace, and turns transcript markers such as "[Figure 4.1: ...]" into plain words.
Why: fork issue #3 and the PDF ingest plan. On main's own extraction of the 10S04 pilot the running footer
"Science and Technology, Grade 10" is on 44 of 44 pages; transcript tags would otherwise be embedded and
shown in result snippets. The rules were fixed in the plan before any result was seen.
How: imported by appai/cli/ingest_pdfs.py; no command of its own.
Inputs/outputs: page strings in, cleaned strings out, plus counts and every removed line for the run report.
Side effects: none.

Rules:
    C1 NFC; ligatures U+FB00-FB06 to letters; remove U+00AD, U+200B, U+FEFF; keep ZWJ/ZWNJ (Devanagari).
    C2 Running lines, in an item with 3+ pages: every line is keyed by its words of 4+ letters. The key on
       the most pages (3+; ties: more words) is the running line if it sits at a page edge (first or last
       2 non-empty lines) on at least one page and matching lines are on at least half the pages. A line
       matches by the same key or by holding all its words with at most 2 more; at page edges an OCR
       variant with difflib ratio >= 0.85 also matches. Matching lines anywhere go, because PyMuPDF's text
       order puts the footer mid-page on some pages (PhET guide p1: line 7 of 29). Number-only edge lines go.
       (Changed 2026-11-27 after the pilot: the first version looked at edge lines only and left the
       footer on all 6 PhET pages and on textbook p87.)
    C3 "word-\\nword" is joined only if the joined word appears elsewhere in the item, else "word-word".
    C4 NBSP and other spaces to one space, lines stripped, at most one blank line in a row.
    M1 [Figure N: caption] -> "Figure N caption"   M2 [Figure text: a; b] -> "a; b"
    M3 [Callouts: ...], [Screenshot text: ...] -> their words
    M4 [Table] rows [End table] -> rows with cells joined by "; ", empty cells dropped
    M5 [Concept map] ... [End concept map] -> the lines, arrows kept
    M6 [blank] dropped   M7 x[cut off] -> x   M8 [illegible] dropped
    M9 an unknown "[Name: ...]" keeps its words and is counted; other brackets ("[1]") stay as printed.
    Markers are resolved innermost first, because cut-off labels sit inside figure text.
"""

import difflib
import re
import unicodedata
from collections import Counter, defaultdict

LIGATURES_AND_INVISIBLES = str.maketrans({
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st",
    "ﬆ": "st", "­": "", "​": "", "﻿": "",
})
SPACES = re.compile(r"[ \t  -   　]+")

EDGE_LINES = 2           # lines checked at the top and at the bottom of each page
MIN_PAGES = 3            # an item needs this many pages before a line can count as "running"
MIN_PAGE_SHARE = 0.5     # the running line must be on at least half the pages (a heading such as "Activity" is not)
MIN_WORD_LETTERS = 4     # key words have 4+ letters, so OCR debris ("cm", "2") and "and" don't split variants
FUZZY_MATCH = 0.85       # difflib ratio that still counts an OCR variant ("Sciénco") as the running line
MAX_EXTRA_WORDS = 2      # a line may hold the running line's words plus at most 2 more and still match
PAGE_NUMBER = re.compile(r"\W*\d{1,3}\W*")
HYPHEN_BREAK = re.compile(r"([^\W\d_]+)-\n([^\W\d_]+)")
WORD = re.compile(r"[^\W\d_]+")

TABLE_BLOCK = re.compile(r"\[Table\][ \t]*\n(.*?)\n?[ \t]*\[End table\]", re.S)
CONCEPT_MAP_BLOCK = re.compile(r"\[Concept map\][ \t]*\n?(.*?)\n?[ \t]*\[End concept map\]", re.S)
FIGURE_CAPTION = re.compile(r"Figure\s+(\d+(?:\.\d+)*[a-z]?)\s*:\s*(.*)", re.S)
LABELLED_TEXT = re.compile(r"(Figure text|Callouts|Screenshot text)\s*:\s*(.*)", re.S | re.I)
UNKNOWN_LABEL = re.compile(r"([A-Z][A-Za-z]*(?: [A-Za-z]+){0,3})\s*:\s*(.*)", re.S)
DROPPED_TAGS = {"cut off": "cut_off", "blank": "blank", "illegible": "illegible"}
BLOCK_TAGS = {"table", "end table", "concept map", "end concept map"}


def normalize_unicode(text: str) -> str:
    """C1: NFC, ligatures to letters, soft hyphen / zero-width space / BOM removed; ZWJ and ZWNJ kept."""
    return unicodedata.normalize("NFC", text.translate(LIGATURES_AND_INVISIBLES))


def tidy_whitespace(text: str) -> str:
    """C4: one space between words, stripped lines, no leading/trailing blank lines, no blank-line runs."""
    lines = [SPACES.sub(" ", line).strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    kept: list[str] = []
    for line in lines:
        if line or (kept and kept[-1]):
            kept.append(line)
    while kept and not kept[-1]:
        kept.pop()
    return "\n".join(kept)


def _letter_words(line: str) -> list[str]:
    """Splits a line into runs of letters and combining marks (keeps Devanagari vowel signs inside words)."""
    words, current = [], []
    for char in line:
        if unicodedata.category(char)[0] in ("L", "M"):
            current.append(char)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def _line_key(line: str) -> str:
    return " ".join(word.lower() for word in _letter_words(line) if len(word) >= MIN_WORD_LETTERS)


def _edge_indexes(lines: list[str]) -> list[int]:
    filled = [i for i, line in enumerate(lines) if line.strip()]
    return sorted(set(filled[:EDGE_LINES] + filled[-EDGE_LINES:]))


def _matches_running(key: str, running: str, at_edge: bool) -> bool:
    """True if a line's key is the running line; fuzzy OCR variants count only at a page edge."""
    if not key:
        return False
    if key == running:
        return True
    key_words, running_words = key.split(), running.split()
    if set(running_words) <= set(key_words) and len(key_words) <= len(running_words) + MAX_EXTRA_WORDS:
        return True
    return at_edge and difflib.SequenceMatcher(None, key, running).ratio() >= FUZZY_MATCH


def remove_running_lines(pages: list[str]) -> tuple[list[str], list[dict]]:
    """C2: removes the running footer/header and number-only lines at the page edges of one item.

    Args:
        pages: the item's page texts, in page order.

    Returns:
        (cleaned pages, removed lines as {"page_index", "line", "rule": "running_line" | "page_number"}).
        An item with fewer than 3 pages is returned unchanged.
    """
    if len(pages) < MIN_PAGES:
        return pages, []
    split_pages = [text.split("\n") for text in pages]
    edges = [set(_edge_indexes(lines)) for lines in split_pages]
    keys = [[_line_key(line) for line in lines] for lines in split_pages]
    pages_by_key: dict[str, set[int]] = defaultdict(set)
    edge_keys: set[str] = set()
    for page_index, page_keys in enumerate(keys):
        for line_index, key in enumerate(page_keys):
            if key:
                pages_by_key[key].add(page_index)
                if line_index in edges[page_index]:
                    edge_keys.add(key)

    def matches(page_index: int, line_index: int, running: str) -> bool:
        return _matches_running(keys[page_index][line_index], running, line_index in edges[page_index])

    running = None
    candidates = [key for key, found in pages_by_key.items() if len(found) >= MIN_PAGES]
    if candidates:
        best = max(candidates, key=lambda k: (len(pages_by_key[k]), len(k.split()), k))
        covered = {page_index for page_index, lines in enumerate(split_pages)
                   if any(matches(page_index, i, best) for i in range(len(lines)))}
        if best in edge_keys and len(covered) >= MIN_PAGE_SHARE * len(pages):
            running = best

    cleaned, removed = [], []
    for page_index, lines in enumerate(split_pages):
        drop = set()
        for line_index, line in enumerate(lines):
            if line_index in edges[page_index] and PAGE_NUMBER.fullmatch(line.strip()):
                drop.add(line_index)
                removed.append({"page_index": page_index, "line": line.strip(), "rule": "page_number"})
            elif running and matches(page_index, line_index, running):
                drop.add(line_index)
                removed.append({"page_index": page_index, "line": line.strip(), "rule": "running_line"})
        cleaned.append("\n".join(line for i, line in enumerate(lines) if i not in drop))
    return cleaned, removed


def join_line_break_hyphens(pages: list[str]) -> tuple[list[str], list[dict]]:
    """C3: rejoins "inheri-\\ntance" when "inheritance" occurs elsewhere in the item; else keeps "self-pollinating".

    Returns:
        (pages, decisions as {"page_index", "parts", "result": "joined" | "kept_hyphen"}).
    """
    vocabulary = {word.lower() for text in pages for word in WORD.findall(text)}
    decisions: list[dict] = []
    cleaned = []
    for page_index, text in enumerate(pages):
        def resolve(match: re.Match) -> str:
            head, tail = match.group(1), match.group(2)
            if not tail[0].islower():
                return match.group(0)
            joined = (head + tail).lower() in vocabulary
            decisions.append({"page_index": page_index, "parts": f"{head}-{tail}",
                              "result": "joined" if joined else "kept_hyphen"})
            return head + tail if joined else f"{head}-{tail}"
        cleaned.append(HYPHEN_BREAK.sub(resolve, text))
    return cleaned, decisions


def clean_text_layer_pages(pages: list[str]) -> tuple[list[str], dict]:
    """Runs C1, C2, C3 and C4 over all text-layer pages of one item.

    Returns:
        (cleaned pages, {"removed_lines": [...], "hyphens": [...]}) for the run report.
    """
    normalized = [normalize_unicode(text) for text in pages]
    without_running, removed = remove_running_lines(normalized)
    joined, hyphens = join_line_break_hyphens(without_running)
    return [tidy_whitespace(text) for text in joined], {"removed_lines": removed, "hyphens": hyphens}


def _table_rows(match: re.Match, counts: Counter) -> str:
    counts["table"] += 1
    rows = []
    for line in match.group(1).split("\n"):
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        if cells:
            rows.append("; ".join(cells))
    return "\n".join(rows)


def _concept_map(match: re.Match, counts: Counter) -> str:
    counts["concept_map"] += 1
    return match.group(1)


def _marker_text(inner: str, counts: Counter) -> str:
    """Replacement for one innermost "[...]"; non-markers are returned with their brackets."""
    name = inner.strip()
    lowered = name.lower()
    if lowered in DROPPED_TAGS:
        counts[DROPPED_TAGS[lowered]] += 1
        return ""
    if lowered in BLOCK_TAGS:
        counts["unpaired_block_tag"] += 1
        return ""
    caption = FIGURE_CAPTION.fullmatch(name)
    if caption:
        counts["figure_caption"] += 1
        return f"Figure {caption.group(1)} {caption.group(2).strip()}"
    labelled = LABELLED_TEXT.fullmatch(name)
    if labelled:
        counts[labelled.group(1).lower().replace(" ", "_")] += 1
        return labelled.group(2).strip()
    unknown = UNKNOWN_LABEL.fullmatch(name)
    if unknown:
        counts["unknown_marker"] += 1
        return unknown.group(2).strip()
    return f"[{inner}]"


def _resolve_brackets(text: str, counts: Counter) -> str:
    """Replaces markers innermost first with a stack; unclosed "[" text is kept as printed and counted."""
    stack: list[list[str]] = [[]]
    for char in text:
        if char == "[":
            stack.append([])
        elif char == "]" and len(stack) > 1:
            inner = "".join(stack.pop())
            stack[-1].append(_marker_text(inner, counts))
        else:
            stack[-1].append(char)
    while len(stack) > 1:
        inner = "".join(stack.pop())
        stack[-1].append("[" + inner)
        counts["unbalanced_bracket"] += 1
    return "".join(stack[0])


def clean_transcript_text(text: str) -> tuple[str, dict]:
    """C1, then M1-M9, then C4 on one transcript page.

    Returns:
        (clean text, counts per marker type: figure_caption, figure_text, callouts, screenshot_text, table,
        concept_map, blank, cut_off, illegible, unknown_marker, unpaired_block_tag, unbalanced_bracket).
    """
    counts: Counter = Counter()
    text = normalize_unicode(text)
    text = TABLE_BLOCK.sub(lambda m: _table_rows(m, counts), text)
    text = CONCEPT_MAP_BLOCK.sub(lambda m: _concept_map(m, counts), text)
    text = _resolve_brackets(text, counts)
    return tidy_whitespace(text), dict(counts)

"""Spelling correction for search queries, built from the bundle's own vocabulary.

Import only. F8 calls `build_spelling_tables()`; `looma_pipeline.search` uses `Speller`. Every word of the FTS5 index
with a letter, no digit and at least MIN_WORD_CHARS characters is stored with its document frequency, plus a
symmetric-delete index (Garbe, SymSpell, 2012): the keys are the word's first PREFIX_CHARS characters with up to
MAX_DISTANCE of them deleted. The same deletes of a query word find every index word within that many edits; the
optimal-string-alignment distance (Damerau-Levenshtein with neighbour swaps) is then checked on the whole words.

Only unknown words are corrected: a query word in neither the index nor the English-Nepali dictionary becomes the
nearest index word (fewest edits, then the word seen with more of the query's other words, then the more frequent
one), keeping the user's capitalization. A correction is always a word that exists in Looma's content.
Real words typed by mistake ("plan" for "plant") are left alone. Suggesting them from co-occurrence in Looma's text
was measured and rejected: it changed 9 of 447 correct queries ("five year plan" became "give hear play"), while
"plant" is only 1.7 times as likely as "plan" next to "make" and "food" (docs/experiments/2026-11-01-typo-tolerance.md).
Side effects: `build_spelling_tables()` writes two tables; everything else only reads.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from looma_pipeline.query_terms import query_terms
from looma_pipeline.text.normalize import normalize_text

MIN_WORD_CHARS = 4         # shorter words are never corrected
PREFIX_CHARS = 7           # SymSpell prefix length: keys come from the first 7 characters
MAX_DISTANCE = 2           # deletes stored per index word
SHORT_WORD_CHARS = 6       # query words up to this length are corrected within 1 edit, longer ones within 2
MAX_CANDIDATES = 10        # nearest candidates compared by context

SCHEMA = """
CREATE TABLE spell_words (word_id INTEGER PRIMARY KEY, word TEXT NOT NULL UNIQUE, df INTEGER NOT NULL);
CREATE TABLE spell_deletes (key TEXT NOT NULL, word_id INTEGER NOT NULL, PRIMARY KEY (key, word_id)) WITHOUT ROWID;
"""

_DEVANAGARI = f"{chr(0x0900)}-{chr(0x097F)}"
_WORD_CHAR = f"\\w{_DEVANAGARI}"


def is_word(term: str) -> bool:
    """A term spelling correction works on: at least MIN_WORD_CHARS characters, a letter and no digit."""
    return (len(term) >= MIN_WORD_CHARS and any(ch.isalpha() for ch in term)
            and not any(ch.isdigit() for ch in term))


def deletes(word: str, distance: int = MAX_DISTANCE) -> set[str]:
    """The word's first PREFIX_CHARS characters, and every string made by deleting up to `distance` of them."""
    found = {word[:PREFIX_CHARS]}
    frontier = set(found)
    for _ in range(distance):
        frontier = {w[:i] + w[i + 1:] for w in frontier for i in range(len(w))} - found
        found |= frontier
    return found


def edit_distance(a: str, b: str) -> int:
    """Optimal string alignment distance: insertions, deletions, substitutions and swaps of two neighbours."""
    if a == b:
        return 0
    before_previous: list[int] = []
    previous = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        current = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                current[j] = min(current[j], before_previous[j - 2] + 1)
        before_previous, previous = previous, current
    return previous[-1]


def build_spelling_tables(db: sqlite3.Connection) -> dict[str, int]:
    """Fill `spell_words` and `spell_deletes` from the FTS5 table `passages_fts`. Returns row counts.

    Rows are inserted in key order, so two builds from the same index write the same tables.
    """
    db.executescript(SCHEMA)
    db.execute("CREATE VIRTUAL TABLE temp.index_vocabulary USING fts5vocab(main, passages_fts, 'row')")
    try:
        words = sorted((term, df) for term, df in db.execute("SELECT term, doc FROM temp.index_vocabulary")
                       if is_word(term))
    finally:
        db.execute("DROP TABLE temp.index_vocabulary")
    db.executemany("INSERT INTO spell_words VALUES (?, ?, ?)", [(n, w, df) for n, (w, df) in enumerate(words)])
    keys = sorted((key, n) for n, (word, _df) in enumerate(words) for key in deletes(word))
    db.executemany("INSERT INTO spell_deletes VALUES (?, ?)", keys)
    return {"spell_words": len(words), "spell_deletes": len(keys)}


@dataclass(frozen=True)
class Change:
    original: str
    replacement: str
    distance: int


@dataclass(frozen=True)
class SpellCheck:
    query: str
    corrected: str | None = None     # the query with corrections applied; None if nothing was corrected
    changes: tuple[Change, ...] = field(default=())


class Speller:
    """Spelling correction over one bundle's SQLite file. A bundle without the tables (schema 1.0) gets none."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        self.available = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'spell_words'").fetchone() is not None
        self._df: dict[str, int] = {}
        self._indexed: dict[str, int] = {}
        self._together: dict[tuple[str, str], int] = {}

    def df(self, word: str) -> int:
        """Passages containing `word`, from the spelling vocabulary (0 if absent)."""
        if word not in self._df:
            row = self.db.execute("SELECT df FROM spell_words WHERE word = ?", (word,)).fetchone()
            self._df[word] = row[0] if row else 0
        return self._df[word]

    def indexed(self, term: str) -> int:
        """Passages containing `term` exactly, any length (used for context words)."""
        if term not in self._indexed:
            self._indexed[term] = self._count(_quoted(term))
        return self._indexed[term]

    def together(self, a: str, b: str) -> int:
        """Passages containing both terms exactly."""
        key = (a, b) if a <= b else (b, a)
        if key not in self._together:
            self._together[key] = self._count(f"{_quoted(a)} AND {_quoted(b)}")
        return self._together[key]

    def known(self, word: str) -> bool:
        if self.df(word):
            return True
        return self.db.execute("SELECT 1 FROM dictionary WHERE en = ? OR np = ? LIMIT 1", (word, word)).fetchone() \
            is not None

    def candidates(self, word: str, max_distance: int) -> list[tuple[str, int, int]]:
        """Index words within `max_distance` edits of `word`, as (word, distance, df): fewest edits, most frequent."""
        keys = sorted(deletes(word, max_distance))
        rows = self.db.execute(
            f"SELECT DISTINCT w.word, w.df FROM spell_deletes d JOIN spell_words w USING (word_id) "
            f"WHERE d.key IN ({','.join('?' * len(keys))})", keys).fetchall()
        found = []
        for candidate, df in rows:
            if candidate != word and abs(len(candidate) - len(word)) <= max_distance:
                distance = edit_distance(word, candidate)
                if distance <= max_distance:
                    found.append((candidate, distance, df))
        return sorted(found, key=lambda row: (row[1], -row[2], row[0]))

    def check(self, query: str) -> SpellCheck:
        if not self.available:
            return SpellCheck(query)
        terms = query_terms(query)
        changes = []
        for word in (t for t in terms if is_word(t) and not self.known(t)):
            change = self._correct(word, [t for t in terms if t != word and self.indexed(t)])
            if change:
                changes.append(change)
        return SpellCheck(query, corrected=_apply(query, changes) if changes else None, changes=tuple(changes))

    def _correct(self, word: str, context: list[str]) -> Change | None:
        found = self.candidates(word, 1 if len(word) <= SHORT_WORD_CHARS else 2)
        if not found:
            return None
        nearest = [row for row in found if row[1] == found[0][1]][:MAX_CANDIDATES]
        best = min(nearest, key=lambda row: (-sum(self.together(row[0], k) for k in context), -row[2], row[0]))
        return Change(word, best[0], best[1])

    def _count(self, expression: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM passages_fts WHERE passages_fts MATCH ?",
                               (expression,)).fetchone()[0]


def _quoted(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def same_case(typed: str, replacement: str) -> str:
    """`replacement` in the capitalization of `typed`: the meaning model distinguishes "Dablam" from "dablam"."""
    if typed.isupper() and len(typed) > 1:
        return replacement.upper()
    if typed[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _apply(query: str, changes: list[Change]) -> str:
    """The query with each changed word replaced as a whole word, keeping the case it was typed in."""
    text = normalize_text(query)
    for change in changes:
        pattern = f"(?<![{_WORD_CHAR}]){re.escape(change.original)}(?![{_WORD_CHAR}])"
        text = re.sub(pattern, lambda match, r=change.replacement: same_case(match.group(0), r), text,
                      flags=re.IGNORECASE)
    return text

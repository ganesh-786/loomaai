"""The bundle's SQLite file: items, passages, an FTS5 word index, English-Nepali dictionary pairs and spelling tables.

Import only. Written by F8, read by looma_pipeline.search. The FTS5 tokenizer keeps vowel signs and viramas inside
words (`categories 'L* N* Co M*'`); SQLite's default splits Devanagari words at every vowel sign, which made `पानी`
match 398 lesson slides instead of the 181 that contain it (measured 2026-10-28). The full-text table is contentless
(`content=''`): passage text is stored once, in `passages`. FTS rowid = `vrow` = the passage's row in the vector file.
The spelling tables come from the finished FTS5 index (looma_pipeline.spelling). Each passage row also stores its
page metadata (models.Passage; schema 1.2), so any search hit can be traced to how its text was made.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from looma_pipeline.models import Item, Passage
from looma_pipeline.spelling import build_spelling_tables

FTS_TOKENIZER = "unicode61 categories 'L* N* Co M*'"
MAX_DICTIONARY_WORDS = 3  # keep word and short-phrase pairs; drop sentence-length entries

SCHEMA = f"""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE items (
    item_id TEXT PRIMARY KEY, ft TEXT NOT NULL, title_en TEXT NOT NULL, title_np TEXT NOT NULL,
    subject TEXT NOT NULL, grade_lo INTEGER, grade_hi INTEGER, grade_source TEXT NOT NULL, src TEXT NOT NULL,
    lang TEXT NOT NULL, cehrd INTEGER NOT NULL, chapter_id TEXT);
CREATE TABLE item_chapters (ch_id TEXT NOT NULL, item_id TEXT NOT NULL, PRIMARY KEY (ch_id, item_id)) WITHOUT ROWID;
CREATE TABLE passages (
    vrow INTEGER PRIMARY KEY, passage_id TEXT NOT NULL UNIQUE, item_id TEXT NOT NULL REFERENCES items (item_id),
    lang TEXT NOT NULL, source TEXT NOT NULL, page INTEGER, t_start REAL, n_tokens INTEGER NOT NULL, text TEXT NOT NULL,
    printed_page TEXT, text_method TEXT NOT NULL, source_run TEXT NOT NULL, source_model TEXT NOT NULL,
    review_status TEXT NOT NULL);
CREATE INDEX passages_by_item ON passages (item_id);
CREATE VIRTUAL TABLE passages_fts USING fts5 (title, body, content='', tokenize="{FTS_TOKENIZER}");
CREATE TABLE dictionary (en TEXT NOT NULL, np TEXT NOT NULL);
CREATE INDEX dictionary_by_en ON dictionary (en);
CREATE INDEX dictionary_by_np ON dictionary (np);
"""

_WORDS = re.compile(r"\S+")


def usable_pair(english: str, nepali: str) -> bool:
    return (0 < len(_WORDS.findall(english)) <= MAX_DICTIONARY_WORDS
            and 0 < len(_WORDS.findall(nepali)) <= MAX_DICTIONARY_WORDS + 1)


def build_word_index(path: Path, items: dict[str, Item], passages: list[Passage],
                     dictionary: list[tuple[str, str]], meta: dict[str, str]) -> dict[str, int]:
    """Write the SQLite file. `passages` must be in vector-row order. Returns row counts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    db = sqlite3.connect(str(path))
    try:
        db.executescript(SCHEMA)
        db.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))
        used_items = sorted({p.item_id for p in passages})
        db.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
            (i.item_id, i.ft, i.title_en, i.title_np, i.subject, i.grade_lo, i.grade_hi, i.grade_source, i.src,
             i.lang, int(i.cehrd), i.chapter_id) for i in (items[item_id] for item_id in used_items)])
        db.executemany("INSERT INTO item_chapters VALUES (?, ?)",
                       [(ch, item_id) for item_id in used_items for ch in items[item_id].ch_ids])
        db.executemany("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (row, p.passage_id, p.item_id, p.lang, p.source, p.page, p.t_start, p.n_tokens, p.text, p.printed_page,
             p.text_method, p.source_run, p.source_model, p.review_status)
            for row, p in enumerate(passages)])
        db.executemany("INSERT INTO passages_fts (rowid, title, body) VALUES (?, ?, ?)", [
            (row, f"{items[p.item_id].title_en} {items[p.item_id].title_np}".strip(), p.text)
            for row, p in enumerate(passages)])
        pairs = sorted({(en.lower().strip(), np.strip()) for en, np in dictionary if usable_pair(en, np)})
        db.executemany("INSERT INTO dictionary VALUES (?, ?)", pairs)
        spelling = build_spelling_tables(db)
        db.commit()
        db.execute("VACUUM")
        return {"items": len(used_items), "passages": len(passages), "dictionary_pairs": len(pairs),
                "item_chapter_links": db.execute("SELECT COUNT(*) FROM item_chapters").fetchone()[0], **spelling}
    finally:
        db.close()

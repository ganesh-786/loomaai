"""Reference search over a staged or signed bundle: meaning (vectors) plus words (FTS5), merged with RRF.

Import only. Used by F9 (suggestions), F12 (checks), `verify` and `python -m looma_pipeline search`. The serve-plane
service will follow the same steps:
1. Filters become one boolean mask over passages (type, source, subject, grade, chapter, CEHRD rule).
2. Meaning: the query's vector is scored against every passage in one pass; disallowed passages are dropped.
3. Words: query terms plus dictionary translations go to FTS5, which returns matches in rank order; disallowed
   passages are skipped. FTS5 ranks with whole-index statistics, so this gives the same list as restricting
   inside SQL, whose cost grew with the number of allowed passages (about 6 s per query at 40,000 passages).
   Both lists are cut to `depth` only after filtering, so a narrow filter still returns its best matches.
4. Reciprocal rank fusion, k = 60 (Cormack et al. 2009): each list adds 1 / (60 + rank).
5. Passages are grouped by item; an item's score is its best passage's score.
Spelling correction (looma_pipeline.spelling) runs first unless turned off: when an unknown word is corrected, the
meaning search embeds the corrected query and the word search looks for the original and the corrected words.
Side effects: none (the SQLite file is opened read-only).
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from looma_pipeline.query_terms import expand, match_expression, query_terms
from looma_pipeline.spelling import SpellCheck, Speller
from looma_pipeline.stages.f07_embed import Embedder, from_int8

RRF_K = 60
DEFAULT_DEPTH = 100  # passages kept from each list before fusion
VECTORS_FILE = "vectors/passages.i8.npy"
DB_FILE = "meta/chunks.db"


@dataclass(frozen=True)
class Filters:
    """Empty sets / None mean "no restriction". Items without a grade band pass a grade filter only when
    `include_unknown_grade` is set (the policy is open question S7). With `grade_window` w, an item passes when its
    band overlaps grade - w .. grade + w. Subjects compare without case."""

    types: frozenset[str] = frozenset()
    sources: frozenset[str] = frozenset()
    subjects: frozenset[str] = frozenset()
    grade: int | None = None
    grade_window: int = 0
    include_unknown_grade: bool = True
    chapter_id: str | None = None
    cehrd_server: bool = False


@dataclass(frozen=True)
class Hit:
    item_id: str
    title: str
    ft: str
    score: float           # RRF score of the item's best passage
    similarity: float      # cosine similarity of that passage to the query
    passage_id: str
    passage: str
    page: int | None
    t_start: float | None


@dataclass(frozen=True)
class SearchResult:
    hits: list[Hit]
    spelling: SpellCheck   # the corrections used for the hits, if any


class SearchEngine:
    """Loads one bundle (vectors + SQLite) and answers queries. Not thread-safe; one instance per worker."""

    def __init__(self, bundle_dir: Path, embedder: Embedder) -> None:
        self.bundle_dir = bundle_dir
        self.embedder = embedder
        self.vectors = from_int8(np.load(bundle_dir / VECTORS_FILE, allow_pickle=False))
        self.db = sqlite3.connect(f"file:{bundle_dir / DB_FILE}?mode=ro", uri=True)
        self.speller = Speller(self.db)
        if self.vectors.shape[1] != embedder.dims:
            raise ValueError(f"bundle vectors have {self.vectors.shape[1]} dims, the embedder {embedder.dims}")

        items = self.db.execute("SELECT item_id, ft, title_en, title_np, subject, grade_lo, grade_hi, src, cehrd "
                                "FROM items ORDER BY item_id").fetchall()
        self.item_ids = [row[0] for row in items]
        index = {item_id: n for n, item_id in enumerate(self.item_ids)}
        self.item_ft = np.array([row[1] for row in items], dtype=object)
        self.item_title = [row[2] or row[3] for row in items]
        self.item_subject = np.array([(row[4] or "").lower() for row in items], dtype=object)
        self.item_grade_lo = np.array([-1 if row[5] is None else row[5] for row in items])
        self.item_grade_hi = np.array([-1 if row[6] is None else row[6] for row in items])
        self.item_src = np.array([(row[7] or "").lower() for row in items], dtype=object)
        self.item_cehrd = np.array([bool(row[8]) for row in items])
        self.chapter_items: dict[str, np.ndarray] = {}
        for ch_id, item_id in self.db.execute("SELECT ch_id, item_id FROM item_chapters"):
            self.chapter_items.setdefault(ch_id, []).append(index[item_id])
        self.chapter_items = {k: np.array(v) for k, v in self.chapter_items.items()}

        passages = self.db.execute("SELECT vrow, passage_id, item_id, text, page, t_start FROM passages "
                                   "ORDER BY vrow").fetchall()
        if len(passages) != self.vectors.shape[0]:
            raise ValueError(f"{len(passages)} passages but {self.vectors.shape[0]} vectors")
        self.row_item = np.array([index[row[2]] for row in passages], dtype=np.int64)
        self.row_meta = [(row[1], row[3], row[4], row[5]) for row in passages]

    def close(self) -> None:
        self.db.close()

    def item_mask(self, filters: Filters) -> np.ndarray:
        mask = ~self.item_cehrd if not filters.cehrd_server else np.ones(len(self.item_ids), dtype=bool)
        if filters.types:
            mask &= np.isin(self.item_ft, list(filters.types))
        if filters.sources:
            mask &= np.isin(self.item_src, [s.lower() for s in filters.sources])
        if filters.subjects:
            mask &= np.isin(self.item_subject, [s.lower() for s in filters.subjects])
        if filters.grade is not None:
            known = self.item_grade_lo >= 0
            low, high = filters.grade - filters.grade_window, filters.grade + filters.grade_window
            inside = known & (self.item_grade_lo <= high) & (low <= self.item_grade_hi)
            mask &= inside | (~known if filters.include_unknown_grade else False)
        if filters.chapter_id is not None:
            in_chapter = np.zeros(len(self.item_ids), dtype=bool)
            in_chapter[self.chapter_items.get(filters.chapter_id, np.array([], dtype=np.int64))] = True
            mask &= in_chapter
        return mask

    def _dense(self, query: str, rows: np.ndarray, depth: int) -> tuple[list[int], np.ndarray]:
        vector = self.embedder.embed_queries([query])[0]
        scores = (self.vectors @ vector)[rows]  # indexing the vectors first would copy every allowed row
        keep = min(depth, len(rows))
        top = np.argpartition(-scores, keep - 1)[:keep] if keep else np.array([], dtype=np.int64)
        top = top[np.lexsort((rows[top], -scores[top]))]  # by score, ties by row for determinism
        similarity = np.full(self.vectors.shape[0], np.nan, dtype=np.float32)
        similarity[rows] = scores
        return [int(rows[i]) for i in top], similarity

    def _lexical(self, query: str, allowed: np.ndarray, depth: int, also: str | None = None) -> list[int]:
        """The first `depth` allowed passages in FTS5 rank order. `allowed` is a boolean mask over vector rows;
        `also` is a second wording whose terms are searched too (the original of a corrected query)."""
        terms = query_terms(query)
        terms += [t for t in query_terms(also or "") if t not in terms]
        expression = match_expression(expand(terms, self.db))
        if expression is None:
            return []
        kept: list[int] = []
        cursor = self.db.execute("SELECT rowid FROM passages_fts WHERE passages_fts MATCH ? ORDER BY rank, rowid",
                                 (expression,))
        try:
            for (row,) in cursor:
                if allowed[row]:
                    kept.append(row)
                    if len(kept) == depth:
                        break
        finally:
            cursor.close()
        return kept

    def respond(self, query: str, filters: Filters = Filters(), k: int = 10, depth: int = DEFAULT_DEPTH,
                spelling: bool = True) -> SearchResult:
        """The `k` best items for `query` under `filters`, with the spelling corrections that were applied."""
        check = self.speller.check(query) if spelling and query.strip() else SpellCheck(query)
        if check.corrected:
            return SearchResult(self._search(check.corrected, filters, k, depth, also=query), check)
        return SearchResult(self._search(query, filters, k, depth), check)

    def search(self, query: str, filters: Filters = Filters(), k: int = 10, depth: int = DEFAULT_DEPTH,
               spelling: bool = True) -> list[Hit]:
        """The `k` best items for `query` under `filters`."""
        return self.respond(query, filters, k, depth, spelling).hits

    def _search(self, query: str, filters: Filters, k: int, depth: int, also: str | None = None) -> list[Hit]:
        allowed = self.item_mask(filters)[self.row_item]
        rows = np.flatnonzero(allowed)
        if len(rows) == 0 or not query.strip():
            return []
        dense, similarity = self._dense(query, rows, depth)
        lexical = self._lexical(query, allowed, depth, also)
        fused: dict[int, float] = {}
        for ranked in (dense, lexical):
            for rank, row in enumerate(ranked):
                fused[row] = fused.get(row, 0.0) + 1.0 / (RRF_K + rank + 1)
        best: dict[int, tuple[float, float, int]] = {}
        for row, score in fused.items():
            item = int(self.row_item[row])
            candidate = (score, float(similarity[row]), -row)
            if item not in best or candidate > best[item]:
                best[item] = candidate
        ranked_items = sorted(best.items(), key=lambda kv: (-kv[1][0], -kv[1][1], self.item_ids[kv[0]]))[:k]
        hits = []
        for item, (score, sim, negative_row) in ranked_items:
            passage_id, text, page, t_start = self.row_meta[-negative_row]
            hits.append(Hit(self.item_ids[item], self.item_title[item], str(self.item_ft[item]), round(score, 6),
                            round(sim, 4), passage_id, text, page, t_start))
        return hits

    def timed_search(self, query: str, filters: Filters = Filters(), k: int = 10,
                     spelling: bool = True) -> tuple[list[Hit], float]:
        hits, _spelling, ms = self.timed_respond(query, filters, k, spelling)
        return hits, ms

    def timed_respond(self, query: str, filters: Filters = Filters(), k: int = 10,
                      spelling: bool = True) -> tuple[list[Hit], SpellCheck, float]:
        started = time.perf_counter()
        result = self.respond(query, filters, k, spelling=spelling)
        return result.hits, result.spelling, (time.perf_counter() - started) * 1000

"""F1 snapshot: read Looma's records for one scope, read only, and fingerprint them.

Import only (called by looma_pipeline.pipeline). Reads activities, lessons, games, chapters, textbooks and the
dictionary through a DataSource. Produces:
- the in-scope records for later stages;
- `snapshot_hash`: SHA-256 of the in-scope records (repeatable; goes into the bundle manifest);
- `curated_checksum`: SHA-256 of every curated field in the whole database, so a later comparison proves the
  pipeline changed nothing (gate G1).
Side effects: writes `f01_snapshot.json` in the run folder. Never writes to MongoDB.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from looma_pipeline.chapters import normalize_ch_ids
from looma_pipeline.hashing import canonical_json, sha256_of_values
from looma_pipeline.runctx import RunContext
from looma_pipeline.source import DataSource

# Curated fields (data-safety rule) plus the AI-written ai_ch_id, which Looma-II shows to exec logins.
CURATED_ACTIVITY_FIELDS = frozenset({
    "ch_id", "nch_id", "cl_lo", "cl_hi", "key1", "key2", "key3", "key4",
    "dn", "ndn", "lang", "src", "fp", "fn", "ai_ch_id",
})
CURATED_CHAPTER_FIELDS = ("dn", "ndn", "pn", "len", "npn", "nlen")

# Pilot: grades 5-6 Science and Social Studies (open question S1's provisional pilot).
PILOT_CHAPTER_RE = re.compile(r"(5|6)(S|SS)\d.*")

# Search hides quizzes today (looma-database-utilities.php skips ft 'quiz'); the bundle does the same.
EXCLUDED_FILE_TYPES = frozenset({"quiz"})


@dataclass
class Snapshot:
    """The in-scope records and their fingerprints."""

    snapshot_id: str
    snapshot_hash: str
    curated_checksum: str
    scope: str
    scope_chapter_ids: frozenset[str]
    activities: list[dict]
    lessons: dict[str, dict]
    games: dict[str, dict]
    chapters: dict[str, dict]
    textbooks: dict[str, dict]
    dictionary: list[tuple[str, str]]
    counts: dict[str, int] = field(default_factory=dict)


def _curated_fields(document: dict, wanted: frozenset[str]) -> dict:
    # Keep the raw key, so a BOM-prefixed duplicate like "\ufeffcl_lo" is covered too.
    return {key: value for key, value in document.items() if key.lstrip("\ufeff") in wanted}


def curated_checksum(activities: list[dict], lessons: list[dict], chapters: list[dict]) -> str:
    """SHA-256 over every curated field of every activity, lesson Nepali text and chapter page range."""
    digest = hashlib.sha256()
    for doc in sorted(activities, key=lambda d: str(d.get("_id"))):
        digest.update(canonical_json(["a", str(doc.get("_id")), _curated_fields(doc, CURATED_ACTIVITY_FIELDS)]))
    for doc in sorted(lessons, key=lambda d: str(d.get("_id"))):
        nepali = [slide.get("nepali") for slide in doc.get("data") or [] if isinstance(slide, dict)]
        digest.update(canonical_json(["l", str(doc.get("_id")), nepali, doc.get("translator"),
                                      doc.get("translated")]))
    for doc in sorted(chapters, key=lambda d: str(d.get("_id"))):
        digest.update(canonical_json(["c", str(doc.get("_id")), [doc.get(f) for f in CURATED_CHAPTER_FIELDS]]))
    return digest.hexdigest()


def read_curated_checksum(source: DataSource) -> str:
    """Recompute the curated checksum straight from the source (used after a run, for gate G1)."""
    return curated_checksum(list(source.activities()), list(source.lessons()), list(source.chapters()))


def scope_chapter_ids(scope: str, chapter_ids: list[str]) -> frozenset[str]:
    if scope == "all":
        return frozenset(chapter_ids)
    if scope == "pilot":
        return frozenset(cid for cid in chapter_ids if PILOT_CHAPTER_RE.fullmatch(cid))
    raise ValueError(f"unknown scope {scope!r}; use 'pilot' or 'all'")


def activity_chapters(doc: dict) -> tuple[str, ...]:
    """All valid chapter ids an activity is linked to, from ch_id / nch_id and their BOM-prefixed twins."""
    values = [value for key, value in doc.items() if key.lstrip("\ufeff") in ("ch_id", "nch_id")]
    ids, _invalid = normalize_ch_ids(*values)
    return ids


def in_scope(doc: dict, scope: str, chapters_in_scope: frozenset[str]) -> bool:
    if doc.get("ft") in EXCLUDED_FILE_TYPES:
        return False
    if scope == "all":
        return True
    if doc.get("ft") == "chapter":
        return str(doc.get("ID", "")).strip() in chapters_in_scope
    return any(cid in chapters_in_scope for cid in activity_chapters(doc))


def run(ctx: RunContext, source: DataSource) -> Snapshot:
    """Read the scope's records and fingerprint them. See the module docstring."""
    with ctx.stage("f01_snapshot") as report:
        activities_all = list(source.activities())
        lessons_all = list(source.lessons())
        chapters_all = list(source.chapters())
        checksum = curated_checksum(activities_all, lessons_all, chapters_all)

        chapters = {str(c["_id"]): c for c in chapters_all}
        chapters_in_scope = scope_chapter_ids(ctx.scope, list(chapters))
        selected = [doc for doc in activities_all if in_scope(doc, ctx.scope, chapters_in_scope)]

        lesson_ids = {str(doc["mongoID"]) for doc in selected if doc.get("ft") == "lesson" and doc.get("mongoID")}
        game_ids = {str(doc["mongoID"]) for doc in selected if doc.get("ft") == "game" and doc.get("mongoID")}
        lessons = {str(d["_id"]): d for d in lessons_all if str(d["_id"]) in lesson_ids}
        games = {str(d["_id"]): d for d in source.games() if str(d["_id"]) in game_ids}
        textbooks = {str(t["prefix"]): t for t in source.textbooks() if t.get("prefix")}
        dictionary = sorted({
            (str(d.get("en", "")).strip(), str(d.get("np", "")).strip())
            for d in source.dictionary()
            if isinstance(d.get("en"), str) and isinstance(d.get("np"), str) and d["en"].strip() and d["np"].strip()
        })

        snapshot_hash = sha256_of_values([
            ctx.scope, sorted(chapters_in_scope),
            *selected, *[lessons[k] for k in sorted(lessons)], *[games[k] for k in sorted(games)],
            *[chapters[k] for k in sorted(chapters_in_scope)], *[textbooks[k] for k in sorted(textbooks)],
            dictionary,
        ])
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot = Snapshot(
            snapshot_id=f"snap-{stamp}-{snapshot_hash[:12]}", snapshot_hash=snapshot_hash,
            curated_checksum=checksum, scope=ctx.scope, scope_chapter_ids=chapters_in_scope,
            activities=selected, lessons=lessons, games=games, chapters=chapters, textbooks=textbooks,
            dictionary=dictionary,
        )
        snapshot.counts = {
            "activities_total": len(activities_all), "activities_in_scope": len(selected),
            "chapters_total": len(chapters_all), "chapters_in_scope": len(chapters_in_scope),
            "lessons_in_scope": len(lessons), "games_in_scope": len(games),
            "textbooks": len(textbooks), "dictionary_pairs": len(dictionary),
            "lessons_missing": len(lesson_ids - set(lessons)), "games_missing": len(game_ids - set(games)),
        }
        report.counts.update(snapshot.counts)
        report.details.update({"snapshot_id": snapshot.snapshot_id, "snapshot_hash": snapshot_hash,
                               "curated_checksum": checksum})
        return snapshot

"""F4 clean: turn raw activity records into clean Items, and clean extracted text.

Import only (called by looma_pipeline.pipeline). Everything happens in memory; MongoDB is never "fixed"
(.claude/rules/data-safety.md). Handles the quirks measured in the local database: grades stored as int, text or
decimal; BOM-prefixed duplicate keys from CSV imports (`\\ufeffcl_lo`); three `ch_id` shapes; `lang` variants;
subject typos in `key1`. Text pieces get NFC cleanup and a language tag by script.
Side effects: writes `f04_clean.json` and `items.jsonl` in the run folder.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, replace
from typing import Any

from looma_pipeline.chapters import chapter_grade, chapter_prefix, normalize_ch_ids
from looma_pipeline.grades import GradeBand, band_from_chapters, band_from_pair, choose_band
from looma_pipeline.models import Item, TextPiece
from looma_pipeline.records import merged_fields
from looma_pipeline.runctx import RunContext
from looma_pipeline.stages.f01_snapshot import Snapshot
from looma_pipeline.text.normalize import normalize_text
from looma_pipeline.text.script import language_of

CEHRD_PREFIX = "../content/CEHRD"  # same test as Looma-II's CEHRDfilter() in includes/mongo-connect.php

# key1 values seen in the database that mean the same subject (data-model notes: 'Lamguage', 'Math', 'science').
SUBJECT_ALIASES = {
    "science": "Science", "social studies": "Social Studies", "mathematics": "Mathematics", "math": "Mathematics",
    "maths": "Mathematics", "language": "Language", "lamguage": "Language", "english": "English",
    "nepali": "Nepali", "health": "Health",
}
LANG_ALIASES = {"en": "en", "english": "en", "np": "np", "ne": "np", "nepali": "np", "both": "both"}
TYPO_KEYS = ("cl_l0", "ch_lo", "ch_hi", "cj_id", "dnn")  # recorded, never guessed at
_GRADE_PREFIX = re.compile(r"^grade\s+\d+\s+", re.IGNORECASE)


def normalize_subject(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    collapsed = " ".join(value.split())
    return SUBJECT_ALIASES.get(collapsed.lower(), collapsed)


def subject_from_chapters(chapter_ids: tuple[str, ...], snapshot: Snapshot) -> str:
    """The subject named by a linked chapter's textbook, e.g. 'Grade 6 Science' gives 'Science'."""
    for chapter_id in chapter_ids:
        textbook = snapshot.textbooks.get(chapter_prefix(chapter_id) or "")
        if textbook and isinstance(textbook.get("dn"), str):
            return normalize_subject(_GRADE_PREFIX.sub("", textbook["dn"]).strip())
    return ""


def clean_item(doc: dict, snapshot: Snapshot, report_counts: Counter) -> Item:
    """Build one Item from a raw activity record. `report_counts` collects data-quality counts."""
    fields, bom_count = merged_fields(doc)
    report_counts["bom_keys_merged"] += bom_count
    report_counts["typo_keys_seen"] += sum(1 for key in TYPO_KEYS if key in fields)

    ft = str(fields.get("ft") or "")
    linked, invalid = normalize_ch_ids(fields.get("ch_id"), fields.get("nch_id"))
    report_counts["invalid_chapter_ids"] += invalid
    chapter_id = str(fields.get("ID", "")).strip() if ft == "chapter" else None
    if chapter_id and chapter_grade(chapter_id) is None:
        report_counts["invalid_chapter_ids"] += 1
        chapter_id = None
    ch_ids = tuple(sorted(set(linked) | ({chapter_id} if chapter_id else set())))

    curated = band_from_pair(fields.get("cl_lo"), fields.get("cl_hi"), "curated")
    chapter_band = band_from_chapters(ch_ids)
    game = snapshot.games.get(str(fields.get("mongoID"))) if ft == "game" else None
    game_band = band_from_pair(game.get("cl_lo"), game.get("cl_hi"), "game") if game else None
    band: GradeBand = choose_band(curated, chapter_band, game_band)
    if curated and chapter_band and not (curated.lo <= chapter_band.lo and chapter_band.hi <= curated.hi):
        report_counts["curated_band_conflicts_with_chapter"] += 1

    taxonomy = tuple(t for t in (normalize_subject(fields.get("key1")), *[
        " ".join(str(fields.get(k) or "").split()) for k in ("key2", "key3", "key4")]) if t)
    subject = normalize_subject(fields.get("key1")) or subject_from_chapters(ch_ids, snapshot)

    return Item(
        item_id=str(fields["_id"]), ft=ft,
        title_en=normalize_text(fields.get("dn") if isinstance(fields.get("dn"), str) else ""),
        title_np=normalize_text(fields.get("ndn") if isinstance(fields.get("ndn"), str) else ""),
        subject=subject, taxonomy=taxonomy, ch_ids=ch_ids, chapter_id=chapter_id,
        grade_lo=band.lo, grade_hi=band.hi, grade_source=band.source,
        src=str(fields.get("src") or "").strip(),
        lang=LANG_ALIASES.get(str(fields.get("lang") or "").strip().lower(), "unknown"),
        cehrd=str(fields.get("fp") or "").startswith(CEHRD_PREFIX),
        mongo_id=str(fields["mongoID"]) if fields.get("mongoID") else None,
    )


def clean_pieces(pieces: list[TextPiece]) -> tuple[list[TextPiece], int]:
    """Normalize text, drop empty pieces and tag each with its language by script.

    Returns:
        (cleaned pieces, number dropped because they were empty after cleanup)
    """
    cleaned: list[TextPiece] = []
    dropped = 0
    for piece in pieces:
        text = normalize_text(piece.text)
        if not text:
            dropped += 1
            continue
        cleaned.append(replace(piece, text=text, lang=language_of(text)))
    return cleaned, dropped


def run(ctx: RunContext, snapshot: Snapshot, pieces: list[TextPiece]) -> tuple[dict[str, Item], list[TextPiece]]:
    """Clean every in-scope item and every extracted text piece."""
    with ctx.stage("f04_clean") as report:
        quality: Counter = Counter()
        items = {item.item_id: item for item in (clean_item(doc, snapshot, quality) for doc in snapshot.activities)}
        cleaned, dropped = clean_pieces(pieces)

        grade_sources = Counter(item.grade_source for item in items.values())
        report.counts.update({
            "items": len(items), "pieces_in": len(pieces), "pieces_out": len(cleaned), "pieces_empty": dropped,
            "cehrd_items": sum(item.cehrd for item in items.values()),
            "items_without_title": sum(1 for i in items.values() if not i.title_en and not i.title_np),
            **{f"grade_{source}": n for source, n in sorted(grade_sources.items())},
            **dict(sorted(quality.items())),
        })
        report.details["grade_unknown_share"] = round(grade_sources.get("unknown", 0) / max(len(items), 1), 3)
        report.details["languages"] = dict(Counter(item.lang for item in items.values()))
        report.details["subjects"] = dict(Counter(item.subject or "(none)" for item in items.values()).most_common(10))
        ctx.write_jsonl("items.jsonl", (asdict(item) for item in items.values()))
        return items, cleaned

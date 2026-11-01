"""F9 suggestions: for each chapter, library items that look related but are not linked to it yet.

Import only (called by looma_pipeline.pipeline). These are PROPOSALS for people to review (Other Resources, P5a);
they are written to a file in the run folder and never to MongoDB (.claude/rules/data-safety.md). Each row carries
provenance: run id, model, snapshot hash, method, score and status "proposed".
The chapter's own title (English, then Nepali) is the query; the search keeps items whose grade band includes the
chapter's grade (or have no band: the age policy is open question S7), and drops chapters and items already
linked to the chapter. MIN_SIMILARITY is provisional and not calibrated yet. Spelling help is off: chapter titles
are curated text, not user input.
Side effects: writes `proposals.jsonl` and `f09_suggestions.json` in the run folder.
"""

from __future__ import annotations

from looma_pipeline.chapters import chapter_grade
from looma_pipeline.models import Item
from looma_pipeline.runctx import RunContext, utc_now
from looma_pipeline.search import Filters, SearchEngine
from looma_pipeline.stages.f01_snapshot import Snapshot
from looma_pipeline.stages.f07_embed import Embedder

PROPOSALS_PER_CHAPTER = 10
CANDIDATES_PER_CHAPTER = 40   # searched before dropping already-linked items
MIN_SIMILARITY = 0.80         # provisional: calibrate on a reviewed sample before showing anything to teachers
METHOD = "hybrid-rrf-v1"


def run(ctx: RunContext, snapshot: Snapshot, items: dict[str, Item], embedder: Embedder) -> list[dict]:
    with ctx.stage("f09_suggestions") as report:
        engine = SearchEngine(ctx.staging_dir, embedder)
        proposals: list[dict] = []
        similarities: list[float] = []
        try:
            for chapter_id in sorted(snapshot.scope_chapter_ids):
                chapter = snapshot.chapters.get(chapter_id, {})
                query = str(chapter.get("dn") or chapter.get("ndn") or "").strip()
                if not query:
                    report.count("chapters_without_title")
                    continue
                filters = Filters(grade=chapter_grade(chapter_id), include_unknown_grade=True,
                                  cehrd_server=ctx.settings.is_cehrd_server)
                kept = [h for h in engine.search(query, filters, CANDIDATES_PER_CHAPTER, spelling=False)
                        if items[h.item_id].ft != "chapter" and chapter_id not in items[h.item_id].ch_ids]
                kept = [h for h in kept if h.similarity >= MIN_SIMILARITY][:PROPOSALS_PER_CHAPTER]
                similarities += [h.similarity for h in kept]
                proposals += [{
                    "ch_id": chapter_id, "activity_id": h.item_id, "title": h.title, "ft": h.ft,
                    "rank": rank, "score": h.score, "similarity": h.similarity, "evidence": h.passage[:200],
                    "method": METHOD, "model": embedder.model_key, "snapshot_hash": snapshot.snapshot_hash,
                    "run_id": ctx.run_id, "created_at": utc_now(), "status": "proposed",
                } for rank, h in enumerate(kept, start=1)]
                report.count("chapters_queried")
        finally:
            engine.close()
        ctx.write_jsonl("proposals.jsonl", proposals)
        report.counts.update({"proposals": len(proposals),
                              "chapters_with_proposals": len({p["ch_id"] for p in proposals})})
        ordered = sorted(similarities)
        report.details["similarity"] = {
            "min": round(ordered[0], 3) if ordered else None,
            "median": round(ordered[len(ordered) // 2], 3) if ordered else None,
            "max": round(ordered[-1], 3) if ordered else None,
            "threshold": MIN_SIMILARITY, "calibrated": False}
        report.details["written_to_mongodb"] = False
        return proposals

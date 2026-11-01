"""F12 checks: open the staged bundle with the reference search and decide whether it may be signed.

Import only (called by looma_pipeline.pipeline). Gates were fixed before the first run
(docs/experiments/2026-11-01-e2e-build-pipeline.md):
- G5 self-test: items with a unique title are found in the top 10 by that title; the queries are saved in the
  bundle so `verify` can repeat them after loading;
- G6 known items: up to 200 English and 200 Nepali titles, at least 95% / 90% found in the top 10 (an item with an
  identical title counts as found), and no CEHRD-only item in any result list;
- G7 chapter filter: searching within a chapter returns only that chapter's items, and something for at least 95%
  of chapters that have items;
- G8 (report only): today's Looma search and this bundle side by side on five questions.
If G5, G6 or G7 fails, ChecksFailed is raised and no bundle is produced.
Side effects: writes `staging/tests/self_test.jsonl` and `f12_checks.json`; HTTP to Looma for G8.
"""

from __future__ import annotations

import json
import random
import statistics
from dataclasses import dataclass

from looma_pipeline.baseline import BaselineUnavailable, today_search
from looma_pipeline.models import Item
from looma_pipeline.runctx import RunContext
from looma_pipeline.search import Filters, SearchEngine
from looma_pipeline.stages.f01_snapshot import Snapshot
from looma_pipeline.stages.f07_embed import Embedder
from looma_pipeline.text.normalize import normalize_text
from looma_pipeline.text.script import language_of

SAMPLE_SEED = 20261101             # fixed, so every run checks the same items
KNOWN_ITEM_SAMPLE = 200
TOP_K = 10
ENGLISH_MIN_RECALL = 0.95          # G6
NEPALI_MIN_RECALL = 0.90           # G6
CHAPTER_MIN_NONEMPTY = 0.95        # G7
SELF_TEST_QUERIES = 20             # G5
COMPARISON_QUESTIONS = ("photosynthesis", "how do plants make food", "units of measurement", "नाप र एकाइ",
                        "prakash sanshleshan")
SELF_TEST_FILE = "tests/self_test.jsonl"


class ChecksFailed(RuntimeError):
    """A gate failed; the bundle must not be signed."""


@dataclass(frozen=True)
class KnownItem:
    item_id: str
    query: str


def _key(title: str) -> str:
    return normalize_text(title).casefold()


def known_item_samples(items: list[Item], language: str, size: int, seed: int = SAMPLE_SEED) -> list[KnownItem]:
    """Items whose title in `language` is written in that language's script, sampled reproducibly."""
    field = "title_en" if language == "en" else "title_np"
    candidates = sorted((i for i in items if getattr(i, field) and language_of(getattr(i, field)) == language),
                        key=lambda i: i.item_id)
    chosen = random.Random(f"{seed}-{language}").sample(candidates, min(size, len(candidates)))
    return [KnownItem(i.item_id, getattr(i, field)) for i in chosen]


def known_item_recall(engine: SearchEngine, samples: list[KnownItem], items: dict[str, Item],
                      latencies: list[float], cehrd_hits: list[str], filters: Filters) -> dict:
    found, misses = 0, []
    for sample in samples:
        hits, ms = engine.timed_search(sample.query, filters, TOP_K)
        latencies.append(ms)
        cehrd_hits += [h.item_id for h in hits if items[h.item_id].cehrd]
        target = _key(sample.query)
        if any(h.item_id == sample.item_id or _key(items[h.item_id].title_en) == target
               or _key(items[h.item_id].title_np) == target for h in hits):
            found += 1
        elif len(misses) < 10:
            misses.append({"query": sample.query, "item_id": sample.item_id,
                           "got": [h.title for h in hits[:3]]})
    return {"queries": len(samples), "found": found,
            "recall_at_10": round(found / len(samples), 4) if samples else None, "misses": misses}


def chapter_filter_check(engine: SearchEngine, snapshot: Snapshot, items: dict[str, Item]) -> dict:
    chapter_ids = sorted(ch for ch in snapshot.scope_chapter_ids if ch in engine.chapter_items)
    nonempty, impure = 0, []
    for chapter_id in chapter_ids:
        chapter = snapshot.chapters.get(chapter_id, {})
        query = str(chapter.get("dn") or chapter.get("ndn") or chapter_id)
        hits = engine.search(query, Filters(chapter_id=chapter_id), TOP_K)
        nonempty += bool(hits)
        impure += [{"chapter": chapter_id, "item_id": h.item_id} for h in hits
                   if chapter_id not in items[h.item_id].ch_ids]
    return {"chapters": len(chapter_ids), "nonempty": nonempty,
            "nonempty_share": round(nonempty / len(chapter_ids), 4) if chapter_ids else None,
            "results_outside_chapter": len(impure), "examples": impure[:5]}


def self_test_queries(engine: SearchEngine, items: dict[str, Item], visible: set[str],
                      cehrd_server: bool = False) -> list[dict]:
    """Up to 20 visible items whose title is unique in the bundle, each with the query that must find it."""
    titles: dict[str, list[str]] = {}
    for item_id in engine.item_ids:
        title = items[item_id].title_en or items[item_id].title_np
        if title:
            titles.setdefault(_key(title), []).append(item_id)
    unique = sorted(ids[0] for ids in titles.values() if len(ids) == 1 and ids[0] in visible)
    chosen = random.Random(f"{SAMPLE_SEED}-self-test").sample(unique, min(SELF_TEST_QUERIES, len(unique)))
    return [{"query": items[i].title_en or items[i].title_np, "expected_item_id": i, "k": TOP_K,
             "cehrd_server": cehrd_server} for i in sorted(chosen)]


def self_test_passes(engine: SearchEngine, test: dict) -> bool:
    """True when the test's item is in the top k for its query (also used by `verify` after loading a bundle)."""
    hits = engine.search(test["query"], Filters(cehrd_server=bool(test.get("cehrd_server"))), int(test["k"]))
    return any(h.item_id == test["expected_item_id"] for h in hits)


def comparison(engine: SearchEngine, looma_web_url: str) -> list[dict]:
    rows = []
    for question in COMPARISON_QUESTIONS:
        try:
            count, titles = today_search(question, looma_web_url)
            today = {"count": count, "top5": titles[:5]}
        except BaselineUnavailable as exc:
            today = {"not_run": str(exc)}
        rows.append({"question": question, "today": today,
                     "bundle_top5": [f"{h.title} [{h.ft}]" for h in engine.search(question, Filters(), 5)]})
    return rows


def run(ctx: RunContext, snapshot: Snapshot, items: dict[str, Item], embedder: Embedder) -> None:
    with ctx.stage("f12_checks") as report:
        engine = SearchEngine(ctx.staging_dir, embedder)
        try:
            # Only items this server may show are sampled: CEHRD-only items are hidden unless building for CEHRD.
            cehrd_server = ctx.settings.is_cehrd_server
            filters = Filters(cehrd_server=cehrd_server)
            visible = [items[i] for i in engine.item_ids if cehrd_server or not items[i].cehrd]
            latencies: list[float] = []
            cehrd_hits: list[str] = []
            english = known_item_recall(engine, known_item_samples(visible, "en", KNOWN_ITEM_SAMPLE), items,
                                        latencies, cehrd_hits, filters)
            nepali = known_item_recall(engine, known_item_samples(visible, "np", KNOWN_ITEM_SAMPLE), items,
                                       latencies, cehrd_hits, filters)
            if cehrd_server:
                cehrd_hits.clear()  # CEHRD results are expected on the CEHRD server
            chapters = chapter_filter_check(engine, snapshot, items)

            tests = self_test_queries(engine, items, {i.item_id for i in visible}, cehrd_server)
            self_test_passed = sum(self_test_passes(engine, test) for test in tests)
            (ctx.staging_dir / "tests").mkdir(parents=True, exist_ok=True)
            (ctx.staging_dir / SELF_TEST_FILE).write_text(
                "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tests), encoding="utf-8")

            report.details.update({
                "G5_self_test": {"queries": len(tests), "passed": self_test_passed},
                "G6_english": english, "G6_nepali": nepali,
                "G6_cehrd_results": {"count": len(cehrd_hits), "examples": cehrd_hits[:5]},
                "G7_chapter_filter": chapters,
                "G8_comparison": comparison(engine, ctx.settings.looma_web_url),
                "G10_search_ms": {"queries": len(latencies),
                                  "p50": round(statistics.median(latencies), 1) if latencies else None,
                                  "p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 1)
                                  if latencies else None,
                                  "label": "dev machine, not Box numbers"},
            })
            failures = gate_failures(report.details)
            report.details["gates_failed"] = failures
            report.counts.update({"self_test_queries": len(tests), "known_item_queries": len(latencies),
                                  "chapters_checked": chapters["chapters"]})
            if failures:
                raise ChecksFailed("; ".join(failures))
        finally:
            engine.close()


def gate_failures(details: dict) -> list[str]:
    """Which of G5, G6 and G7 failed, in words. Empty when all passed."""
    failures = []
    g5 = details["G5_self_test"]
    if g5["queries"] == 0 or g5["passed"] < g5["queries"]:
        failures.append(f"G5 self-test {g5['passed']}/{g5['queries']}")
    for name, minimum in (("G6_english", ENGLISH_MIN_RECALL), ("G6_nepali", NEPALI_MIN_RECALL)):
        recall = details[name]["recall_at_10"]
        if recall is not None and recall < minimum:
            failures.append(f"{name} recall@10 {recall} < {minimum}")
    if details["G6_english"]["queries"] == 0:
        failures.append("G6_english has no queries")
    if details["G6_cehrd_results"]["count"]:
        failures.append(f"G6 {details['G6_cehrd_results']['count']} CEHRD-only results")
    g7 = details["G7_chapter_filter"]
    if g7["results_outside_chapter"]:
        failures.append(f"G7 {g7['results_outside_chapter']} results outside their chapter")
    if g7["nonempty_share"] is not None and g7["nonempty_share"] < CHAPTER_MIN_NONEMPTY:
        failures.append(f"G7 non-empty share {g7['nonempty_share']} < {CHAPTER_MIN_NONEMPTY}")
    return failures

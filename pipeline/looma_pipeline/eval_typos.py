"""Typo-tolerance evaluation of one bundle (docs/experiments/2026-11-01-typo-tolerance.md).

Import only; `python -m looma_pipeline eval-typos <bundle>` calls `run_typo_eval()`. Every query is searched with
spelling help off (option A) and on (option B), on the same bundle:
1. synthetic typos: G6's English and Nepali title samples; the longest word of at least 5 letters gets one seeded
   edit, redrawn until it is an unknown word; found = the item, or one with the same title, in the top 10;
2. hand-made pairs (pipeline/eval/typo_pairs.jsonl): overlap@10 between a typo query and its correct spelling, and
   whether the correction equals the correct spelling;
3. clean queries: the G6 titles, the correct half of each pair and the clean-only queries; corrections made to them;
4. latency: every typo query and every clean query is timed with spelling off and on, alternately.
Gates T1, T2, T3 and T5 are decided here; T4 comes from the e2e run and T6 from the bundle sizes.
Side effects: writes `data/runs/eval-typos-<time>/report.json` and `report.md`.
"""

from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from looma_pipeline.config import Settings
from looma_pipeline.query_terms import query_terms
from looma_pipeline.search import Filters, Hit, SearchEngine
from looma_pipeline.spelling import is_word, same_case
from looma_pipeline.stages.f12_checks import SAMPLE_SEED, TOP_K, _key, known_item_samples

PAIRS_FILE = Path(__file__).resolve().parents[1] / "eval" / "typo_pairs.jsonl"
SYNTHETIC_SAMPLE = 200
MIN_TARGET_CHARS = 5
MAX_REDRAWS = 20
ALPHABETS = {"en": "abcdefghijklmnopqrstuvwxyz",
             "np": "".join(chr(c) for c in [*range(0x0905, 0x093A), *range(0x093E, 0x094D)])}
GATES = {"T1": 0.90, "T2_overlap": 0.70, "T2_fixed": 0.85, "T5_added_p95_ms": 15.0}
_DEVANAGARI = f"{chr(0x0900)}-{chr(0x097F)}"


def make_typo(word: str, rng: random.Random, alphabet: str) -> str:
    """One random edit: delete, insert, substitute, or swap two neighbouring characters."""
    operation = rng.choice(("delete", "insert", "substitute", "swap"))
    i = rng.randrange(len(word))
    if operation == "delete":
        return word[:i] + word[i + 1:]
    if operation == "insert":
        return word[:i] + rng.choice(alphabet) + word[i:]
    if operation == "substitute":
        return word[:i] + rng.choice([c for c in alphabet if c != word[i]]) + word[i + 1:]
    i = min(i, len(word) - 2)
    return word[:i] + word[i + 1] + word[i] + word[i + 2:]


def replace_word(text: str, word: str, replacement: str) -> str:
    """Replace the first whole-word `word`, keeping the case it has in `text`."""
    pattern = f"(?<![\\w{_DEVANAGARI}]){re.escape(word)}(?![\\w{_DEVANAGARI}])"
    return re.sub(pattern, lambda match: same_case(match.group(0), replacement), text, count=1, flags=re.IGNORECASE)


def synthetic_typos(engine: SearchEngine, items: list[Any], language: str, size: int = SYNTHETIC_SAMPLE,
                    seed: int = SAMPLE_SEED) -> tuple[list[dict], int]:
    """(typo queries, titles skipped because no word could be turned into an unknown word)."""
    alphabet, cases, skipped = ALPHABETS[language], [], 0
    for sample in known_item_samples(items, language, size, seed):
        rng = random.Random(f"{seed}-typo-{sample.item_id}")
        words = [t for t in query_terms(sample.query) if is_word(t) and len(t) >= MIN_TARGET_CHARS
                 and all(c in alphabet or not c.isalpha() for c in t)]
        typo = None
        if words:
            word = max(words, key=len)
            for _ in range(MAX_REDRAWS):
                attempt = make_typo(word, rng, alphabet)
                if attempt != word and is_word(attempt) and not engine.speller.known(attempt):
                    typo = attempt
                    break
        if typo is None:
            skipped += 1
            continue
        cases.append({"item_id": sample.item_id, "title": sample.query, "word": word, "typo": typo,
                      "query": replace_word(sample.query, word, typo)})
    return cases, skipped


def run_typo_eval(settings: Settings, engine: SearchEngine, bundle_name: str) -> dict:
    filters = Filters(cehrd_server=settings.is_cehrd_server)
    rows = engine.db.execute("SELECT item_id, title_en, title_np, cehrd FROM items ORDER BY item_id").fetchall()
    titles = {item_id: (en, np) for item_id, en, np, _ in rows}
    visible = [SimpleNamespace(item_id=i, title_en=en, title_np=np) for i, en, np, cehrd in rows
               if settings.is_cehrd_server or not cehrd]
    def search(query: str, spelling: bool) -> tuple[list[Hit], Any]:
        result = engine.respond(query, filters, TOP_K, spelling=spelling)
        return result.hits, result.spelling

    def found(hits: list[Hit], item_id: str, title: str) -> bool:
        target = _key(title)
        return any(h.item_id == item_id or target in {_key(titles[h.item_id][0]), _key(titles[h.item_id][1])}
                   for h in hits)

    for warm_up in ("photosynthesis", "water cycle"):
        engine.respond(warm_up, filters)

    synthetic: dict[str, Any] = {}
    timed_queries: list[str] = []
    for language in ("en", "np"):
        cases, skipped = synthetic_typos(engine, visible, language)
        timed_queries += [case["query"] for case in cases]
        result: dict[str, Any] = {"queries": len(cases), "skipped": skipped}
        for spelling in (False, True):
            hits_found, misses, corrected_back = 0, [], 0
            for case in cases:
                hits, check = search(case["query"], spelling)
                ok = found(hits, case["item_id"], case["title"])
                hits_found += ok
                corrected_back += bool(check.corrected and case["word"] in query_terms(check.corrected))
                if not ok and len(misses) < 10:
                    misses.append({"query": case["query"], "title": case["title"],
                                   "corrected": check.corrected, "got": [h.title for h in hits[:3]]})
            result["on" if spelling else "off"] = {
                "found": hits_found, "recall_at_10": round(hits_found / len(cases), 4) if cases else None,
                "corrected_to_the_original_word": corrected_back, "misses": misses}
        synthetic[language] = result

    pairs, clean_queries = [], []
    for line in PAIRS_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        clean_queries.append(row["clean"])
        if "typo" not in row:
            continue
        typo_terms, clean_terms = query_terms(row["typo"]), query_terms(row["clean"])
        misspelled = [t for t in typo_terms if t not in clean_terms]
        kind = "unknown word" if any(not engine.speller.known(t) for t in misspelled) else "real word"
        timed_queries.append(row["typo"])
        off, _ = search(row["typo"], False)
        on, check = search(row["typo"], True)
        reference, _ = search(row["clean"], True)
        reference_ids = {h.item_id for h in reference}
        pairs.append({
            "typo": row["typo"], "clean": row["clean"], "lang": row["lang"], "kind": kind, "corrected": check.corrected,
            "fixed": bool(check.corrected) and query_terms(check.corrected) == clean_terms,
            "overlap_off": _overlap(off, reference_ids), "overlap_on": _overlap(on, reference_ids),
            "top1_same_on": bool(on and reference and on[0].item_id == reference[0].item_id)})

    for sample in [*known_item_samples(visible, "en", 200), *known_item_samples(visible, "np", 200)]:
        clean_queries.append(sample.query)
    changed = []
    for query in clean_queries:
        _hits, check = search(query, True)
        if check.changes:
            changed.append({"query": query, "corrected": check.corrected})
    clean = {"queries": len(clean_queries), "corrected": len(changed), "examples": changed[:20]}

    timings: dict[bool, list[float]] = {False: [], True: []}
    for query in timed_queries + clean_queries:
        for spelling in (False, True):
            timings[spelling].append(engine.timed_respond(query, filters, TOP_K, spelling=spelling)[2])

    latency = {("on" if mode else "off"): {"queries": len(ms), "p50": _percentile(ms, 50),
                                           "p95": _percentile(ms, 95)} for mode, ms in timings.items()}
    unknown = [p for p in pairs if p["kind"] == "unknown word" and p["lang"] == "en"]
    real = [p for p in pairs if p["kind"] == "real word"]
    summary = {
        "unknown_word_pairs_en": _pair_summary(unknown), "real_word_pairs": _pair_summary(real),
        "nepali_pairs": _pair_summary([p for p in pairs if p["lang"] == "np"])}
    english = synthetic["en"]["on"]["recall_at_10"] or 0.0
    added_p95 = round(latency["on"]["p95"] - latency["off"]["p95"], 1)
    gates = {
        "T1": {"pass": english >= GATES["T1"], "evidence": f"English synthetic typos recall@10 {english} "
               f"(spelling off {synthetic['en']['off']['recall_at_10']})"},
        "T2": {"pass": bool(unknown) and summary["unknown_word_pairs_en"]["mean_overlap_on"] >= GATES["T2_overlap"]
               and summary["unknown_word_pairs_en"]["fixed_share"] >= GATES["T2_fixed"],
               "evidence": f"{len(unknown)} unknown-word pairs: mean overlap@10 "
                           f"{summary['unknown_word_pairs_en']['mean_overlap_on']} (off "
                           f"{summary['unknown_word_pairs_en']['mean_overlap_off']}), fixed "
                           f"{summary['unknown_word_pairs_en']['fixed_share']}"},
        "T3": {"pass": clean["corrected"] == 0,
               "evidence": f"{clean['queries']} clean queries: {clean['corrected']} corrected "
                           "(no suggestions are made)"},
        "T5": {"pass": added_p95 <= GATES["T5_added_p95_ms"],
               "evidence": f"p95 {latency['on']['p95']} ms on, {latency['off']['p95']} ms off (+{added_p95} ms)"},
    }
    return {"bundle": bundle_name, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "all_gates_pass": all(g["pass"] for g in gates.values()), "gates": gates, "synthetic": synthetic,
            "pairs": pairs, "pair_summary": summary, "clean": clean, "latency_ms": latency}


def write_report(settings: Settings, report: dict) -> Path:
    folder = settings.runs_dir / f"eval-typos-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    folder.mkdir(parents=True)
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / "report.md").write_text(markdown(report), encoding="utf-8")
    return folder


def markdown(report: dict) -> str:
    lines = [f"# Typo tolerance: {report['bundle']}", "", "| Gate | Result | Evidence |", "|---|---|---|"]
    lines += [f"| {name} | {'PASS' if gate['pass'] else 'FAIL'} | {gate['evidence']} |"
              for name, gate in report["gates"].items()]
    lines += ["", "| Pair | Kind | Overlap off | Overlap on | Correction |", "|---|---|---|---|---|"]
    lines += [f"| {p['typo']} | {p['kind']} | {p['overlap_off']} | {p['overlap_on']} | {p['corrected'] or '-'} |"
              for p in report["pairs"]]
    return "\n".join(lines) + "\n"


def _overlap(hits: list[Hit], reference_ids: set[str]) -> float:
    return round(len({h.item_id for h in hits} & reference_ids) / max(len(reference_ids), 1), 2)


def _pair_summary(pairs: list[dict]) -> dict:
    if not pairs:
        return {"pairs": 0}
    return {"pairs": len(pairs),
            "mean_overlap_off": round(sum(p["overlap_off"] for p in pairs) / len(pairs), 3),
            "mean_overlap_on": round(sum(p["overlap_on"] for p in pairs) / len(pairs), 3),
            "fixed_share": round(sum(p["fixed"] for p in pairs) / len(pairs), 3),
            "top1_same_on": round(sum(p["top1_same_on"] for p in pairs) / len(pairs), 3)}


def _percentile(values: list[float], percent: int) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(percent / 100 * (len(ordered) - 1)))], 1) if ordered else 0.0

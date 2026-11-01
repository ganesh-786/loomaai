"""End-to-end check: does the pipeline work, safely and repeatably? Decides gates G1-G10.

Import only; `python -m looma_pipeline e2e --scope pilot` calls `run_e2e()`. The gates were fixed before the first
run in docs/experiments/2026-11-01-e2e-build-pipeline.md. Steps:
1. curated-field checksum of the whole database (before);
2. the test suite (G9);
3. build 1 and build 2 from the same data (G2, G4). One int8 embedder is shared by both builds; only build 1's
   F7 loads the full-size model, for its int8 agreement report, and releases it. Loading both models per build
   (430 MB + 746 MB warmed) made two full-scope builds peak at 1,896 MB in one process, near the 2 GiB limit;
4. verify build 1, then try two tampered copies: one changed byte, and a validly re-signed bundle that claims
   another model (G3, G5);
5. curated-field checksum again (G1); G6-G8 and G10 come from build 1's reports.
Side effects: everything a build does (two bundles in data/bundles/), plus `data/runs/e2e-<time>/` with the
tampered copies and `e2e-report.json` / `e2e-report.md`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from looma_pipeline.bundle import MANIFEST_FILE, load_private_key, write_checksums_and_sign
from looma_pipeline.chunking import TokenCounter
from looma_pipeline.config import Settings
from looma_pipeline.pipeline import STAGE_REPORTS, int8_embedder, open_mongo_source, run_build
from looma_pipeline.runctx import peak_rss_mb
from looma_pipeline.source import DataSource
from looma_pipeline.stages.f01_snapshot import read_curated_checksum
from looma_pipeline.stages.f07_embed import Embedder
from looma_pipeline.verify import verify

PIPELINE_DIR = Path(__file__).resolve().parents[1]


def _report(run_dir: Path, stage: str) -> dict:
    return json.loads((run_dir / f"{stage}.json").read_text(encoding="utf-8"))


def run_tests() -> tuple[bool, str]:
    """Run the test suite in a subprocess. Returns (passed, pytest's summary line)."""
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=PIPELINE_DIR,
                               capture_output=True, text=True, check=False)
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return completed.returncode == 0, (lines[-1] if lines else completed.stderr.strip()[-200:])


def _tampered_byte(bundle: Path, work: Path) -> Path:
    copy = shutil.copytree(bundle, work / "tamper-one-byte")
    target = copy / "vectors" / "passages.i8.npy"
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0x01
    target.write_bytes(bytes(data))
    return copy


def _tampered_model(bundle: Path, work: Path, settings: Settings) -> Path:
    """A bundle that claims another model and is validly re-signed, as a mistaken build would be."""
    copy = shutil.copytree(bundle, work / "tamper-other-model")
    manifest = json.loads((copy / MANIFEST_FILE).read_text(encoding="utf-8"))
    manifest["embedding"]["repo"] = "someone/other-embedding-model"
    (copy / MANIFEST_FILE).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_checksums_and_sign(copy, load_private_key(settings.signing_key_path))
    return copy


def _failed_check(result) -> str:
    return next((name for name, ok, _ in result.checks if not ok), "")


def run_e2e(settings: Settings, scope: str, source: DataSource | None = None, counter: TokenCounter | None = None,
            embedder: Embedder | None = None, model_dir: Path | None = None, with_tests: bool = True) -> dict:
    """Run every step and return the report (also written to the e2e folder)."""
    work = settings.runs_dir / f"e2e-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    work.mkdir(parents=True)
    source = source or open_mongo_source(settings)
    before = read_curated_checksum(source)
    tests_ok, tests_summary = run_tests() if with_tests else (None, "not run")

    shared = embedder if embedder is not None else int8_embedder(settings)
    first = run_build(settings, scope, source=source, counter=counter, embedder=shared, model_dir=model_dir,
                      int8_agreement=True)
    bundle1, run_dir1, seconds1 = first.outputs["bundle"], first.run_dir, first.seconds
    first = None  # the gates need only its files; its records, passages and vectors can go before build 2
    second = run_build(settings, scope, source=source, counter=counter, embedder=shared, model_dir=model_dir,
                       int8_agreement=False)
    bundle2, run_dir2 = second.outputs["bundle"], second.run_dir
    second = shared = None
    manifest1 = json.loads((bundle1 / MANIFEST_FILE).read_text(encoding="utf-8"))
    manifest2 = json.loads((bundle2 / MANIFEST_FILE).read_text(encoding="utf-8"))

    # Without an injected embedder, verify loads the bundle's own model, so G3 and G5 test the shipped files.
    verified = verify(bundle1, settings, embedder=embedder)
    byte_result = verify(_tampered_byte(bundle1, work), settings, embedder=embedder)
    model_result = verify(_tampered_model(bundle1, work, settings), settings, embedder=embedder)
    after = read_curated_checksum(source)

    reports = {stage: _report(run_dir1, stage) for stage in STAGE_REPORTS}
    checks = reports["f12_checks"]["details"]
    embed1, embed2 = reports["f07_embed"], _report(run_dir2, "f07_embed")
    self_test = next(d for n, _, d in verified.checks if n == "self-test queries") if verified.checks else ""
    gates: dict[str, dict[str, Any]] = {
        "G1": {"pass": before == after == manifest1["snapshot"]["curated_checksum"],
               "evidence": f"curated checksum before {before[:16]}, after {after[:16]}; write rejection is "
                           "covered by test_mongo_readonly (G9)"},
        "G2": {"pass": all(r["status"] == "ok" for r in reports.values()),
               "evidence": f"{len(reports)} stage reports ok, build {seconds1} s, bundle {bundle1.name}"},
        "G3": {"pass": verified.ok and not byte_result.ok and _failed_check(byte_result) == "checksums"
               and not model_result.ok and _failed_check(model_result) == "model expected by the reader",
               "evidence": f"verify ok={verified.ok}; one byte changed -> refused at "
                           f"'{_failed_check(byte_result)}'; other model -> refused at '{_failed_check(model_result)}'"},
        "G4": {"pass": manifest1["content_hash"] == manifest2["content_hash"] and embed2["counts"]["embedded_new"] == 0,
               "evidence": f"content hash {manifest1['content_hash'][:16]} == {manifest2['content_hash'][:16]}; "
                           f"second build embedded {embed2['counts']['embedded_new']} passages"},
        "G5": {"pass": verified.ok and bool(self_test), "evidence": f"self-test after loading: {self_test}"},
        "G6": {"pass": not [f for f in checks["gates_failed"] if f.startswith("G6")],
               "evidence": f"English {checks['G6_english']['found']}/{checks['G6_english']['queries']}, Nepali "
                           f"{checks['G6_nepali']['found']}/{checks['G6_nepali']['queries']}, CEHRD results "
                           f"{checks['G6_cehrd_results']['count']}"},
        "G7": {"pass": not [f for f in checks["gates_failed"] if f.startswith("G7")],
               "evidence": f"{checks['G7_chapter_filter']['nonempty']}/{checks['G7_chapter_filter']['chapters']} "
                           f"chapters non-empty, {checks['G7_chapter_filter']['results_outside_chapter']} outside"},
        "G8": {"pass": None, "evidence": "report only, see comparison", "comparison": checks["G8_comparison"]},
        "G9": {"pass": tests_ok, "evidence": tests_summary},
        "G10": {"pass": None, "evidence": "dev machine, not Box numbers",
                "stage_seconds": {s: r["seconds"] for s, r in reports.items()},
                "peak_rss_mb": {"build_1": reports["f13_bundle"].get("peak_rss_mb"),
                                "build_2": _report(run_dir2, "f13_bundle").get("peak_rss_mb"),
                                "whole_e2e_run": peak_rss_mb()},
                "bundle_bytes": reports["f13_bundle"]["counts"]["bytes"],
                "search_ms": checks["G10_search_ms"],
                "embedding": {"passages": embed1["counts"]["passages"],
                              "embedded_new_first_build": embed1["counts"]["embedded_new"],
                              "passages_per_second": embed1["details"].get("passages_per_second_new"),
                              "int8_vs_full": embed1["details"].get("int8_vs_full")}},
    }
    decided = [g["pass"] for g in gates.values() if g["pass"] is not None]
    report = {"scope": scope, "work_dir": str(work), "bundles": [bundle1.name, bundle2.name],
              "verify": verified.as_dict(), "all_gates_pass": all(decided), "gates": gates}
    (work / "e2e-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (work / "e2e-report.md").write_text(markdown(report), encoding="utf-8")
    return report


def markdown(report: dict) -> str:
    rows = ["| Gate | Result | Evidence |", "|---|---|---|"]
    for gate, data in report["gates"].items():
        result = {True: "PASS", False: "FAIL", None: "REPORT"}[data["pass"]]
        rows.append(f"| {gate} | {result} | {data['evidence']} |")
    comparison = ["", "| Question | Today (count: top results) | Bundle top 3 |", "|---|---|---|"]
    for row in report["gates"]["G8"]["comparison"]:
        today = row["today"]
        today_text = (f"{today['count']}: {', '.join(today['top5'][:3])}" if "count" in today
                      else f"not run ({today['not_run'][:40]})")
        comparison.append(f"| {row['question']} | {today_text} | {'; '.join(row['bundle_top5'][:3])} |")
    verdict = "ALL GATES PASS" if report["all_gates_pass"] else "SOME GATES FAIL"
    return "\n".join([f"# End-to-end report ({report['scope']}): {verdict}", "", *rows, *comparison, ""])

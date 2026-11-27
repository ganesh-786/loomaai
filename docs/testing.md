# Testing

For: developers changing the build pipeline, and reviewers deciding whether a change can ship. Covers how to run each
kind of check and the latest results.

Last verified: 2026-11-01 at 98f8a807

## Kinds of checks

| Check | What it covers | Command | Runs on | Needs |
|---|---|---|---|---|
| Unit tests | extraction, OCR, captions, cleaning, grades, chunking, ids, FTS5 tokenizer, search filters, signing, tampering | `make pipeline-test` | laptop | nothing external; tests marked `mongo` and `model` skip themselves when unavailable |
| Integration (MongoDB, read only) | F1 on the real database with an unchanged curated checksum; the FTS5 tokenizer on every real lesson slide | `make pipeline-test` | laptop with Looma-II up | `looma-db` |
| Integration (model) | real embedder: 384 dims, normalized, English matches its Nepali translation, batch-independence | `make pipeline-test` | laptop | `make pipeline-model` |
| End to end, gates G1-G10 | two builds, verification, two tampered copies, the tests, today's search side by side | `make pipeline-e2e SCOPE=pilot` (about 1 min) or `SCOPE=all` (about 5 min) | laptop with Looma-II up | the model |
| Typo tolerance, gates T1-T3 and T5 | synthetic English and Nepali typos of G6 titles, hand-made typo pairs (`pipeline/eval/typo_pairs.jsonl`), clean queries, latency with spelling on and off | `make pipeline-eval-typos BUNDLE=<name>` (about 1 min on the full scope) | laptop | a bundle with schema 1.1 |
| Retrieval quality judged by people | Recall@10 / nDCG@10 against today's search on the golden question set | not built yet | laptop | golden-set version |
| Box measurements | latency, memory, disk on arm64 | not built yet | ODROID-C4 | a Box |

## Latest results

| Check | Date | Commit | Result | Report |
|---|---|---|---|---|
| `make pipeline-test` | 2026-11-01 | 98f8a807 | 228 passed, 0 skipped (model and MongoDB available) | console |
| `make pipeline-e2e SCOPE=pilot` | 2026-11-01 | 98f8a807 | all decided gates pass (G1-G7, G9); G8 and G10 recorded | `data/runs/e2e-20261101T141550Z/` (not in Git) |
| `make pipeline-e2e SCOPE=all` | 2026-11-01 | 98f8a807 | all decided gates pass (G1-G7, G9); G8 and G10 recorded | `data/runs/e2e-20261101T141011Z/` (not in Git) |
| `make pipeline-eval-typos` | 2026-11-01 | 22e028d1 | T1, T2, T3 and T5 pass on the full scope | [typo tolerance experiment](experiments/2026-11-01-typo-tolerance.md) |
| `pytest` in the pipeline image | 2026-11-27 | ca66da95 | 333 passed, 0 failed, 0 skipped (model and MongoDB available) | console |
| `e2e --scope all`, empty content folder | 2026-11-27 | ca66da95 | all decided gates pass (G1-G7, G9); G8 not run (see below); 0 files found, so no PDF text | `data/runs/e2e-20261127T053206Z/` (not in Git) |
| `e2e --scope all`, content sample mounted | 2026-11-27 | ca66da95 | all decided gates pass (G1-G7, G9); 21 files found; 466 text-layer pages and 1 OCR page; peak 1,684 MB; search p50 13.4 ms, p95 33.5 ms (not Box numbers) | `data/runs/e2e-20261127T053742Z/` (not in Git) |
| Red check, page transcripts (issue #2) | 2026-11-27 | 33e44208 | new tests fail on the code before the change: 5 failed, 2 test modules cannot import `extractors.transcripts`; 330 others pass | console |
| `pytest` in the pipeline image | 2026-11-27 | 1730c33d | 374 passed, 0 failed, 0 skipped | console |
| `build --scope all --until f03`, content sample, run D's 44 unreviewed transcript rows, `TRANSCRIPTS_ALLOW_UNREVIEWED=1` | 2026-11-27 | 1730c33d | 44 rows used, 44 transcript pages, 0 stale, 0 unmatched, 0 malformed, 0 problems; OCR skipped (0 OCR pages) | `data/runs/20261127T054511Z-all-ad90/` (not in Git) |
| the same with the default `TRANSCRIPTS_ALLOW_UNREVIEWED=0` | 2026-11-27 | 1730c33d | 44 rows skipped as unreviewed, 0 transcript pages; the page that needs OCR went to OCR (1 OCR page) | `data/runs/20261127T054525Z-all-defa/` (not in Git) |
| Red check, transcript markers (issue #3) | 2026-11-27 | f0f02ce2 | new tests fail on the code before the change: 1 failed, `test_markers` cannot import `text.markers`; 374 others pass | console |
| `pytest` in the pipeline image | 2026-11-27 | 9db243b2 | 386 passed, 0 failed, 0 skipped | console |
| `build --scope all --until f06`, content sample, run D's 44 rows, `TRANSCRIPTS_ALLOW_UNREVIEWED=1` | 2026-11-27 | 9db243b2 | 104 passages from 44 pages; 0 brackets and 0 table pipes left; 26/26 critical facts; captions 26/26 by the A-D harness tokenizer, 25/26 by words split at spaces (gold caption F07 reads "Figure 4.7Structure of RNA", missing a space; the bundle text has "Figure 4.7: Structure of RNA"); 0 unknown markers | `data/runs/20261127T054846Z-all-7f8c/` (not in Git) |
| Red check, page metadata (issue #4) | 2026-11-27 | 32d6a9d5 | the 5 new tests fail on the code before the change; 386 others pass | console |
| `pytest` in the pipeline image | 2026-11-27 | be0c5999 | 391 passed, 0 failed, 0 skipped | console |
| `build --scope all`, content sample, run D's 44 rows, `TRANSCRIPTS_ALLOW_UNREVIEWED=1`, then `verify` | 2026-11-27 | be0c5999 | schema 1.2; G5 20/20, G6 English 0.99 and Nepali 1.00, G7 1,645/1,645; `verify ok`; content hash `6b13f338...`, the same as the 2026-11-26 build of the unsplit change | `data/bundles/looma-ai-bundle-2026.11.27-all-r5/` (not in Git) |
| Quality checks Q1-Q14 on that bundle | 2026-11-27 | be0c5999 | Q1-Q11 and Q13 pass; Q12 page-exact hit@3 0.875 fails the 0.90 gate (search shows a neighbouring page) | [quality evaluation](experiments/2026-11-27-transcript-quality.md) |

The content sample is `data/content/` in the main checkout: Grade 10 Science `Science_10_0016.pdf` and two PhET
guides, with sources and sha256 in its `manifest.json`. The Makefile's default content folder
(`/usr/local/var/www/content`) is empty on the development machine. All runs on 2026-11-27 used the image built
2026-11-02 with `pipeline/` mounted read only (its `requirements.lock` is unchanged since that build). Build runs with
the content sample mount it read only at `/content`.

G8 was not run on 2026-11-27: `looma-web` answered HTTP 404 for `looma-database-utilities.php` and 403 for its home
page, because the running container serves no Looma-II PHP files. That is the local Looma-II setup, not the
pipeline; G8 is report-only.

Gate results of those runs (dev machine, not Box numbers):

| Gate | Pilot (1,034 items, 1,930 passages) | All (23,681 items, 40,212 passages) |
|---|---|---|
| G1 | curated-field checksum identical before and after (`8e58fba1...`) | same |
| G2 | 11 stage reports ok; one build 25.3 s | 11 stage reports ok; one build 141.0 s |
| G3 | verify ok; one changed byte refused at `checksums`; a re-signed bundle for another model refused at `model expected by the reader` | same |
| G4 | same content hash on the second build (`b2dda6e7...`); 0 passages re-embedded | same (`2bddd48c...`); 0 re-embedded |
| G5 | self-test after loading 20/20 | 20/20 |
| G6 | English titles 200/200, Nepali titles 200/200, 0 CEHRD-only results | English 199/200, Nepali 200/200, 0 CEHRD-only |
| G7 | 140/140 chapters return results, 0 outside their chapter | 1,645/1,645, 0 outside |
| G9 | 228 passed | 228 passed |
| G10 | search p50 12.6 ms, p95 24.3 ms; bundle 143 MB; peak RSS 1,593 MB | search p50 21.8 ms, p95 53.5 ms; bundle 191 MB; peak RSS 1,667 MB |

Search times vary between runs on this laptop by more than the cost of spelling correction: the typo evaluation,
which times the same 848 queries with correction on and off, measured +2.5 ms at p95. Content hashes changed at
`22e028d1` because they now cover the spelling vocabulary.

Every stage report (`data/runs/<run_id>/<stage>.json`) records `status` (`ok`, `failed` or `interrupted`) and
`peak_rss_mb`, the process's peak memory so far.

## Known gaps
- File extractors (PDF, OCR, captions, HTML) and Preeti conversion are tested on generated files only. Looma's
  content folder is empty on the development machine (open question S1).
- G6 measures whether an item can be found by its own title. It does not measure whether results answer a
  student's question; that needs the golden question set and people judging results.
- int8 against full-size embeddings: mean cosine 0.989 but only 80% average top-10 overlap on a 200-passage sample.
  The embedder experiment (EXP-002) has to compare quantization options before a production choice.
- No Box numbers yet: every time and size here is from the development machine.
- F9 proposals use an uncalibrated similarity threshold (0.80): every chapter got the maximum of 10, on the pilot
  and on the full scope (18,439 proposals). They must be reviewed and the threshold calibrated before anyone sees
  them.
- Near-identical numbered titles ("Old Nepal 00094" among hundreds of "Old Nepal" photos) can miss the top 10: the
  model scores them almost alike and RRF favours items found by both lists. A ranking change needs the golden set.
- Memory headroom: the full-scope e2e run peaks at 1,667 MB of the container's 2 GiB. Real textbook text will add
  passages; watch `peak_rss_mb`.
- Spelling: real words typed by mistake ("plan" for "plant") are not corrected, and words one edit from two index
  words can be corrected to the wrong one ("hart" became "part"). The hand-made typo pairs were written by the
  developer and the synthetic typos are random edits; real student queries and a Nepali speaker's review are needed.

# Testing

For: developers changing the build pipeline, and reviewers deciding whether a change can ship. Covers how to run each
kind of check and the latest results.

Last verified: 2026-11-01 at b1b63e54

## Kinds of checks

| Check | What it covers | Command | Runs on | Needs |
|---|---|---|---|---|
| Unit tests | extraction, OCR, captions, cleaning, grades, chunking, ids, FTS5 tokenizer, search filters, signing, tampering | `make pipeline-test` | laptop | nothing external; tests marked `mongo` and `model` skip themselves when unavailable |
| Integration (MongoDB, read only) | F1 on the real database with an unchanged curated checksum; the FTS5 tokenizer on every real lesson slide | `make pipeline-test` | laptop with Looma-II up | `looma-db` |
| Integration (model) | real embedder: 384 dims, normalized, English matches its Nepali translation, batch-independence | `make pipeline-test` | laptop | `make pipeline-model` |
| End to end, gates G1-G10 | two builds, verification, two tampered copies, the tests, today's search side by side | `make pipeline-e2e SCOPE=pilot` (57 s) or `SCOPE=all` (4 min 12 s) | laptop with Looma-II up | the model |
| Retrieval quality judged by people | Recall@10 / nDCG@10 against today's search on the golden question set | not built yet | laptop | golden-set version |
| Box measurements | latency, memory, disk on arm64 | not built yet | ODROID-C4 | a Box |

## Latest results

| Check | Date | Commit | Result | Report |
|---|---|---|---|---|
| `make pipeline-test` | 2026-11-01 | b1b63e54 | 198 passed, 0 skipped (model and MongoDB available) | console |
| `make pipeline-e2e SCOPE=pilot` | 2026-11-01 | b1b63e54 | all decided gates pass (G1-G7, G9); G8 and G10 recorded | [experiment record](experiments/2026-11-01-e2e-build-pipeline.md), section 9 |
| `make pipeline-e2e SCOPE=all` | 2026-11-01 | b1b63e54 | all decided gates pass (G1-G7, G9); G8 and G10 recorded | [experiment record](experiments/2026-11-01-e2e-build-pipeline.md), section 9 |

Gate results of those runs (dev machine, not Box numbers):

| Gate | Pilot (1,034 items, 1,930 passages) | All (23,681 items, 40,212 passages) |
|---|---|---|
| G1 | curated-field checksum identical before and after (`8e58fba1...`) | same |
| G2 | 11 stage reports ok; one build 18.9 s | 11 stage reports ok; one build 117.7 s |
| G3 | verify ok; one changed byte refused at `checksums`; a re-signed bundle for another model refused at `model expected by the reader` | same |
| G4 | same content hash on the second build (`28cc7d6e...`); 0 passages re-embedded | same (`459c5174...`); 0 re-embedded |
| G5 | self-test after loading 20/20 | 20/20 |
| G6 | English titles 200/200, Nepali titles 200/200, 0 CEHRD-only results | English 199/200, Nepali 200/200, 0 CEHRD-only |
| G7 | 140/140 chapters return results, 0 outside their chapter | 1,645/1,645, 0 outside |
| G9 | 198 passed | 198 passed |
| G10 | search p50 9.0 ms, p95 24.1 ms; bundle 140 MB; peak RSS 1,594 MB | search p50 15.4 ms, p95 39.1 ms; bundle 176 MB; peak RSS 1,666 MB |

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
- Memory headroom: the full-scope e2e run peaks at 1,666 MB of the container's 2 GiB. Real textbook text will add
  passages; watch `peak_rss_mb`.

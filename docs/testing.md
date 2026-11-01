# Testing

For: developers changing the build pipeline, and reviewers deciding whether a change can ship. Covers how to run each
kind of check and the latest results.

Last verified: 2026-11-01 at 865883ff

## Kinds of checks

| Check | What it covers | Command | Runs on | Needs |
|---|---|---|---|---|
| Unit tests | extraction, OCR, captions, cleaning, grades, chunking, ids, FTS5 tokenizer, search filters, signing, tampering | `make pipeline-test` | laptop | nothing external; tests marked `mongo` and `model` skip themselves when unavailable |
| Integration (MongoDB, read only) | F1 on the real database with an unchanged curated checksum; the FTS5 tokenizer on every real lesson slide | `make pipeline-test` | laptop with Looma-II up | `looma-db` |
| Integration (model) | real embedder: 384 dims, normalized, English matches its Nepali translation, batch-independence | `make pipeline-test` | laptop | `make pipeline-model` |
| End to end, gates G1-G10 | two builds, verification, two tampered copies, the tests, today's search side by side | `make pipeline-e2e SCOPE=pilot` | laptop with Looma-II up | the model |
| Retrieval quality judged by people | Recall@10 / nDCG@10 against today's search on the golden question set | not built yet | laptop | golden-set version |
| Box measurements | latency, memory, disk on arm64 | not built yet | ODROID-C4 | a Box |

## Latest results

| Check | Date | Commit | Result | Report |
|---|---|---|---|---|
| `make pipeline-test` | 2026-11-01 | 865883ff | 176 passed, 0 skipped (model and MongoDB available) | console |
| `make pipeline-e2e SCOPE=pilot` | 2026-11-01 | 865883ff | all decided gates pass (G1-G7, G9); G8 and G10 recorded | [experiment record](experiments/2026-11-01-e2e-build-pipeline.md) |

Gate results of that run (dev machine, not Box numbers):

| Gate | Result |
|---|---|
| G1 | curated-field checksum identical before and after (`8e58fba1...`) |
| G2 | 11 stage reports ok; one build took 67.5 s |
| G3 | verify ok; one changed byte refused at `checksums`; a re-signed bundle for another model refused at `model expected by the reader` |
| G4 | same content hash on the second build; 0 passages re-embedded |
| G5 | self-test after loading 20/20 |
| G6 | English titles 200/200, Nepali titles 200/200, 0 CEHRD-only results |
| G7 | 140/140 chapters return results, 0 results outside their chapter |
| G9 | 176 passed |
| G10 | search p50 92.9 ms, p95 174 ms; bundle 134 MB |

## Known gaps
- File extractors (PDF, OCR, captions, HTML) and Preeti conversion are tested on generated files only. Looma's
  content folder is empty on the development machine (open question S1).
- G6 measures whether an item can be found by its own title. It does not measure whether results answer a
  student's question; that needs the golden question set and people judging results.
- int8 against full-size embeddings: mean cosine 0.989 but only 80% average top-10 overlap on a 200-passage sample.
  The embedder experiment (EXP-002) has to compare quantization options before a production choice.
- No Box numbers yet: every time and size here is from the development machine.
- F9 proposals use an uncalibrated similarity threshold (0.80): every pilot chapter got the maximum of 10. They
  must be reviewed and the threshold calibrated before anyone sees them.

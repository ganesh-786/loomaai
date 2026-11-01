# Experiment: Does the F1-F13 build pipeline work end to end, safely and repeatably, on Looma's data?

| | |
|---|---|
| Date | 2026-11-01 |
| Status | done |
| Owner | Ganesh (TEJ) |
| Informs | no decision yet: feeds the build-plane design in `../architecture.md` |
| Code | branch `feat/p5-02-e2e-build-pipeline`, commits listed in section 8 |

## 1. Question and hypothesis

Can one command turn Looma's database into a signed index bundle that is correct, safe and repeatable, using only the
text that is in MongoDB today? We expect yes for the database text. File extractors (PDF, OCR, captions, HTML) can only
be tested on generated files, because the content folder on the development machine is empty.

This is not a search-quality experiment. Quality judged by people needs the golden question set, and Box fit needs an
ODROID-C4. Both are later experiments.

## 2. Options under test

One configuration; every choice below is provisional.

| Option | Exact id and version | License | Size on disk | Notes |
|---|---|---|---|---|
| Embedder | `intfloat/multilingual-e5-small`, revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, published `onnx/model.onnx`, int8 by `onnxruntime.quantization.quantize_dynamic` | MIT | measured in section 5 | needs `query: ` / `passage: ` prefixes |
| Runtime | ONNX Runtime 1.31.1, CPU | MIT | in the image | no PyTorch anywhere |
| Word index | SQLite 3.46.1 FTS5, `unicode61 categories 'L* N* Co M*'` | public domain | measured | Devanagari setting tested 2026-10-28 |
| Vector store | int8 vectors in a NumPy file, exact dot product | n/a | measured | EXP-003 compares Qdrant, Zvec, sqlite-vec later |
| Passages | target 200, max 256 tokens, overlap 32 | n/a | n/a | the embedder's tokenizer |

## 3. Setup

- Hardware: developer laptop, WSL2 on Windows, 12 CPUs, 6.6 GiB RAM visible to Linux, Docker Desktop. **All times and
  sizes are dev-machine numbers, not Box numbers.**
- Software: image `looma-pipeline:dev` built from `pipeline/Dockerfile` (base
  `python@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159`, Debian 13, Python 3.12, packages in
  `pipeline/requirements.lock`).
- Data: local `looma-db` restored from Looma-II's `mongo-dump` (MongoDB 5.0.27). Scope `pilot`: grades 5-6 Science
  and Social Studies (chapter ids matching `(5|6)(S|SS)\d`). Content folder: empty.
- To reproduce:
```bash
make pipeline-image
make pipeline-model          # downloads the embedder once (network)
make pipeline-test
make pipeline-e2e SCOPE=pilot
```

## 4. Metrics and gate (fixed before running)

| Gate | Pass rule |
|---|---|
| G1 | curated-field checksum identical before and after; the read-only wrapper rejects writes (unit test) |
| G2 | `make pipeline-build SCOPE=pilot` runs F1 to F13, exit code 0, every stage report present |
| G3 | verify passes; one changed byte is refused; a bundle signed for another model is refused |
| G4 | a second build gives the same content hash and re-embeds 0 passages |
| G5 | the bundle's self-test queries pass after loading |
| G6 | 200 random English titles queried by their own title: at least 95% found in the top 10; up to 200 Nepali titles: at least 90% (items with an identical title count as found); 0 CEHRD-only items returned |
| G7 | a one-chapter filter returns only that chapter's items and is non-empty for at least 95% of pilot chapters with linked items |
| G8 | report only: today's `cmd=search` and the bundle side by side on five questions |
| G9 | `make pipeline-test` passes |
| G10 | time per stage, bundle size and search latency recorded |

Also recorded (not gates): int8 against full-size embeddings on a sample (mean cosine, top-10 agreement).

## 5. Results

Run: `make pipeline-e2e SCOPE=pilot` at commit `865883ff`, 2026-11-01, 2 min 34 s in total. Dev-machine numbers,
not Box numbers.

| Gate | Result | Measured |
|---|---|---|
| G1 | PASS | curated checksum `8e58fba128fcb671…` before and after; write rejection covered by `test_mongo_readonly` |
| G2 | PASS | 11 stage reports with status `ok`; one build 67.5 s |
| G3 | PASS | verify ok; one changed byte refused at `checksums`; a validly re-signed bundle claiming another model refused at `model expected by the reader` |
| G4 | PASS | content hash `28cc7d6ec27da78d…` equal for both builds; second build embedded 0 passages |
| G5 | PASS | self-test after loading the bundle's own model: 20/20 |
| G6 | PASS | English titles 200/200 in the top 10, Nepali titles 200/200, CEHRD-only results 0 |
| G7 | PASS | 140/140 pilot chapters with items return results; 0 results outside their chapter |
| G8 | report | see the comparison below |
| G9 | PASS | 176 tests passed |
| G10 | report | see the measurements below |

Pilot data: 1,034 activities, 164 chapters, 31 lessons, 106 games, 26,981 dictionary pairs (26,742 kept). F3
produced 1,921 text pieces; F6 1,930 passages (1,303 English, 615 Nepali, 12 mixed; mean 33 tokens, at most 199).

G8, today's `cmd=search` against the bundle (top results):

| Question | Today | Bundle top 3 |
|---|---|---|
| photosynthesis | 7: C-4 Photosynthesis, Nutrition in Plants Photosynthesis, Photosynthesis | Photosynthesis [chapter]; What is Photosynthesis [video]; Photosynthesis [video] |
| how do plants make food | 0 | 6S05.02 Photosyntesis and digestion [game]; 5S Life Processes [lesson]; 5S Plant Parts [lesson] |
| units of measurement | 1: Converting units of measurements | Local and standard units of measurement [chapter]; Multiple and submultiple units [chapter]; Measurement and unit [chapter] |
| नाप र एकाइ | 0 | Measurement and unit [chapter]; Multiple and submultiple units [chapter]; Local and standard units of measurement [chapter] |
| prakash sanshleshan | 0 | Pasang Lhamu Sherpa [image]; Light [chapter]; Anuradha Koirala [image] |

G10 measurements:

| Measure | Value |
|---|---|
| Stage seconds (first build) | F1 0.85 · F2 0.02 · F3 0.36 · F4 0.13 · F5 0.04 · F6 0.47 · F7 4.3 (from cache) · F8 0.31 · F9 14.0 · F12 41.1 · F13 2.1 |
| Embedding, new passages | about 156 passages/s, one text per call, 4 threads |
| Search latency (400 queries) | p50 92.9 ms, p95 174 ms |
| Bundle size | 134 MB (int8 model 118 MB, tokenizer 17 MB, vectors 0.74 MB, SQLite 3.8 MB) |
| int8 vs full-size (200 passages, 50 queries) | mean cosine 0.989; mean top-10 overlap 0.80; identical top 10 for 12% of queries |

## 6. Analysis
- The pipeline works end to end on the database text and meets every gate set before the run.
- Search by meaning answers questions today's title search cannot: three of five comparison questions return 0 today
  and relevant items from the bundle. "prakash sanshleshan" (romanized Nepali) still returns unrelated items: no
  component handles romanized Nepali yet (EXP-008).
- Two problems were found by tests during the run and fixed before the final run:
  1. Dynamic int8 quantization made a passage's vector depend on the other texts in its batch (up to 0.016 per
     component; the full-size model is exactly batch-independent). Passages are now embedded one per call, the way
     a query is, at about half the throughput.
  2. Number-only query terms were dropped, so numbered titles ("Old Nepal 00152") could not be told apart. Numbers
     are now matched exactly. English known-item recall went from 198/200 to 200/200; the gate was not changed.
- Multiple-choice games store `{question, correctAns, wrongAns}` objects; the first extractor missed them (37 of 106
  pilot games had text). Now 106 of 106 do; wrong answers are left out on purpose.
- int8 keeps vectors close (cosine 0.989) but reorders near-ties: only 80% top-10 overlap with the full-size model.
- F9's provisional threshold (0.80) gave every chapter the maximum of 10 proposals: it is too low to be useful as is.

Threats to validity: G6 asks whether an item is found by its own title, an easy test; it is not search quality
judged by people. File extractors were tested on generated files only. All timings are from a 12-CPU laptop.

## 7. Conclusion
The F1-F13 pipeline is correct, safe (no MongoDB writes, signed bundles, tampering refused) and repeatable on the
pilot scope. Still open: search quality on golden questions, real-content extraction (S1), the embedder and
quantization choice (EXP-002), the vector store (EXP-003), romanized Nepali (EXP-008), F9 threshold calibration,
and Box measurements.

## 8. Artifacts

| Artifact | Location | sha256 | Size |
|---|---|---|---|
| e2e report | `data/runs/e2e-20261101T072213Z/e2e-report.json` (not in Git) | `5118333fd24e4ff58045b7e0ac6b504eb7c15f00924cec199137ef7556ebcb26` | 5,753 bytes |
| Bundle checksum list | `data/bundles/looma-ai-bundle-2026.11.01-pilot-r1/SHA256SUMS` (not in Git) | `92bd6053cdbea7b4b7f0936ef4d21af5605f7c69794f3a568730e55fd651f60f` | 776 bytes |
| Bundle | `data/bundles/looma-ai-bundle-2026.11.01-pilot-r1/` (not in Git) | content hash `28cc7d6ec27da78d7f0378cebbec4a76e45ea52da3a886ee36c637dc92ee43bd` | 140,187,407 bytes |
| int8 model | `data/models/intfloat--multilingual-e5-small/614241f622f53c4eeff9890bdc4f31cfecc418b3/model.int8.onnx` | `8da4c9ba0ad59f58e8566839425d7fd6339d31414d0ce5cba2d7d0afb75dd8b6` | 118,101,091 bytes |

Commits on `feat/p5-02-e2e-build-pipeline`: `b77eb0d0` design, `2ea99136` image and settings, `98de28d5` F1,
`6b063a76` F2, `89cc7efd` F4, `cf73ca00` F3, `ebeca399` F5, `bd2ca9f9` F6, `2f532dfc` this record (plan),
`62d1b5e0` F7, `35f6f9a6` F8, `9c29b1cc` F12 and search, `865883ff` F9, F13, verify and e2e.

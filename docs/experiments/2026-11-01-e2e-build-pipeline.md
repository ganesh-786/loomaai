# Experiment: Does the F1-F13 build pipeline work end to end, safely and repeatably, on Looma's data?

| | |
|---|---|
| Date | 2026-11-01 |
| Status | running |
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
Not run yet.

## 6. Analysis
Not run yet.

## 7. Conclusion
Not run yet.

## 8. Artifacts
Not run yet.

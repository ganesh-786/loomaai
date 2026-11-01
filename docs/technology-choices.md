# Technology choices

For: reviewers and the next developer asking "why this component?". One row per component: what was tried, what is in
use now, how settled it is, and the evidence.

Last verified: 2026-11-01 at b1b63e54

No choice below is a production decision yet: none has an accepted ADR. "Provisional" means it is in use so the
pipeline can run end to end, and the named experiment will decide.

| Component | Options tried | In use now | Status | ADR | Evidence |
|---|---|---|---|---|---|
| Embedding model | `intfloat/multilingual-e5-small` | same, revision `614241f6`, published ONNX | provisional | none | [e2e experiment](experiments/2026-11-01-e2e-build-pipeline.md); EXP-002 will compare models |
| Model runtime | ONNX Runtime 1.31.1 (CPU) | same | provisional | none | e2e experiment; no PyTorch needed |
| Quantization | dynamic int8 (`quantize_dynamic`, QInt8) | same, one text per call | provisional | none | int8 vs full size: cosine 0.989, top-10 overlap 0.80 (pilot sample); 0.991, 0.87 (full-scope sample); batch dependence measured (up to 0.016) |
| Vector storage | int8 NumPy file, exact dot product | same | provisional | none | 1,930 × 384 vectors = 0.74 MB (pilot), 40,212 × 384 = 15 MB (full scope); EXP-003 will compare Qdrant, Zvec, sqlite-vec |
| Word index | SQLite FTS5 with `unicode61 categories 'L* N* Co M*'` | same; filters applied by skipping disallowed rows, not inside SQL | provisional | none | tokenizer finding of 2026-10-28, now a regression test on real lesson slides; `rowid IN (...)` filtering rejected at about 3 s per query on 40,000 passages |
| Fusion | reciprocal rank fusion, k = 60 | same | provisional | none | standard method (Cormack et al. 2009); quality not yet measured on golden questions |
| OCR | Tesseract (`eng`, `nep`) | same | provisional | none | generated scanned pages in English and Nepali read back correctly (tests); not tried on real scans |
| Preeti conversion | `npttf2utf/` (in repo) | same, guarded | provisional; license question | none | converts `gfk / PsfO` to `नाप र एकाइ`; GPL-3.0 needs Skip's decision |
| Signing | ed25519 via `cryptography` | same | provisional | none | tamper tests: changed byte, other key, edited rows all refused |
| Pipeline packaging | Docker image `looma-pipeline` | same | provisional | none | image 768 MB vs 11.4 GB for the prototype image |

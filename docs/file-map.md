# File map

For: developers looking for where something lives or what a file does. Covers every tracked file.

Last verified: 2026-11-01 at 98f8a807

## Overview
```
appai/        prototype: Streamlit admin pages and CLI jobs (unchanged from upstream de3b4b9)
docs/         project documentation (this folder)
npttf2utf/    Preeti-to-Unicode converter (third party, GPL-3.0); used by the pipeline's F5
pipeline/     build pipeline F1-F13: code, tests, Dockerfile, pinned dependencies
Makefile      prototype targets plus pipeline-* targets
```

## Files

| Path | What it does | How it runs | Reads | Writes or side effects |
|---|---|---|---|---|
| `Makefile` | prototype and pipeline targets | `make <target>` | see [install-and-run.md](install-and-run.md) | see [install-and-run.md](install-and-run.md) |
| `Dockerfile` | prototype image (Streamlit app) | `make build` | `requirements.txt`, `appai/` | image; **copies `.env` into it** |
| `.dockerignore` | build context exclusions for the prototype image | Docker | n/a | n/a |
| `.gitignore` | ignores `data/`, `.env`, `env`, caches | Git | n/a | n/a |
| `docker-compose.yml` | prototype services: `looma-streamlit`, `looma-ollama`, `looma-qdrant` | `make run` | `.env` values from the host | containers, `data/` volumes |
| `docker-compose.search.yml` | the `looma-search` service alone, for a Looma Box or a server: read-only container, port bound to `127.0.0.1` | `make search-up`, `make search-down` | `data/bundles/<SEARCH_BUNDLE>/` and the public key, both read only | a container on `loomanet` |
| `bootup.sh` | starts Streamlit inside the prototype image | image entry point | `appai/` | `st-llms.log` |
| `requirements.txt` | prototype Python dependencies | `make setup-host`, `make build` | n/a | n/a |
| `README.md` | prototype overview and quickstart; links to these docs | read | n/a | n/a |
| `README_LLM.md` | prototype notes on LLM selection | read | n/a | n/a |
| `dotstreamlit/config.toml` | Streamlit settings for the prototype | copied into the image | n/a | n/a |
| `appai/` | prototype package: `appai/main.py`, `appai/pages/`, `appai/cli/`, `appai/common/` (see the prototype audit for what each job writes) | Streamlit, `make` targets | MongoDB, Qdrant, looma.website, LLM APIs | MongoDB (`cl_lo`/`cl_hi`, `ai_ch_id`, lesson Nepali), Qdrant, `data/` |
| `npttf2utf/` | Preeti and other legacy Nepali fonts to Unicode; `npttf2utf/files/map.json` holds the mapping rules; `npttf2utf/files/` also holds samples | imported by `pipeline/looma_pipeline/text/preeti.py` | text | none |
| `docs/architecture.md` | goals, constraints, building blocks, runtime views, risks, glossary | read | n/a | n/a |
| `docs/install-and-run.md` | setup and every make target | read | n/a | n/a |
| `docs/configuration.md` | every setting and its default | read | n/a | n/a |
| `docs/testing.md` | how to test; latest results | read | n/a | n/a |
| `docs/file-map.md` | this file | read | n/a | n/a |
| `docs/changes-from-prototype.md` | what changed since upstream `de3b4b9` | read | n/a | n/a |
| `docs/technology-choices.md` | per component: options, provisional choice, evidence | read | n/a | n/a |
| `docs/experiments/` | experiment records with gates fixed before running | read | n/a | n/a |
| `pipeline/Dockerfile` | the `looma-pipeline` image (pinned base, Tesseract, no PyTorch, no secrets) | `make pipeline-image` | `pipeline/`, `npttf2utf/` | image |
| `pipeline/Dockerfile.dockerignore` | allow-list build context for that image | Docker BuildKit | n/a | n/a |
| `pipeline/requirements.in` | top-level pipeline dependencies | edit, then refreeze | n/a | n/a |
| `pipeline/requirements.lock` | exact versions installed in the image | `pip install -r` in the Dockerfile | n/a | n/a |
| `pipeline/Dockerfile.serve` | the `looma-search` image: search code and its libraries only (no PDF, OCR or MongoDB libraries) | `make search-image`, `make search-image-arm64` | `pipeline/requirements-serve.lock`, `pipeline/looma_pipeline/` | image |
| `pipeline/requirements-serve.in` | top-level dependencies of the search image | edit, then refreeze within `requirements.lock` | n/a | n/a |
| `pipeline/requirements-serve.lock` | exact versions installed in the search image | `pip install -r` in `pipeline/Dockerfile.serve` | n/a | n/a |
| `pipeline/pytest.ini` | test settings and markers (`mongo`, `model`) | `make pipeline-test` | n/a | n/a |
| `pipeline/looma_pipeline/__init__.py` | package version, bundle schema version | import | n/a | n/a |
| `pipeline/looma_pipeline/__main__.py` | `python -m looma_pipeline` entry point | CLI | n/a | n/a |
| `pipeline/looma_pipeline/cli.py` | commands: info, prepare-model, keygen, build, verify, search, serve, e2e, eval-typos, clean | CLI | env vars | depends on the command |
| `pipeline/looma_pipeline/service.py` | `looma-search` HTTP service: `/health` and `/search` (modes library, chapter, related); imports search code only | `python -m looma_pipeline.service <bundle>` or the `serve` command | a bundle, `SEARCH_*` env vars | one JSON log line per request (never the query text) |
| `pipeline/looma_pipeline/config.py` | all settings, read once from env vars and validated | import | env vars | none |
| `pipeline/looma_pipeline/logs.py` | JSON-lines logging; `run.log` per run | import | n/a | stderr, `data/runs/<run_id>/run.log` |
| `pipeline/looma_pipeline/runctx.py` | run ids, run folders, stage reports | import | n/a | `data/runs/<run_id>/*.json` |
| `pipeline/looma_pipeline/pipeline.py` | runs F1 to F13 in order | `build`, `e2e` | everything below | everything below |
| `pipeline/looma_pipeline/mongo_readonly.py` | MongoDB wrapper with read methods only | import | MongoDB | none (writes raise `ReadOnlyViolation`) |
| `pipeline/looma_pipeline/source.py` | data sources: MongoDB (read only) or in-memory for tests | import | MongoDB | none |
| `pipeline/looma_pipeline/records.py` | BOM-prefixed key handling | import | n/a | none |
| `pipeline/looma_pipeline/chapters.py` | chapter id parsing and normalization | import | n/a | none |
| `pipeline/looma_pipeline/grades.py` | grade parsing and grade-band precedence | import | n/a | none |
| `pipeline/looma_pipeline/paths.py` | Looma's file path rules; content-folder confinement | import | n/a | none |
| `pipeline/looma_pipeline/models.py` | Item, TextPiece, Passage records | import | n/a | none |
| `pipeline/looma_pipeline/hashing.py` | canonical JSON and SHA-256 helpers | import | files | none |
| `pipeline/looma_pipeline/text/` | Unicode cleanup and HTML to text (`pipeline/looma_pipeline/text/normalize.py`), script detection (`pipeline/looma_pipeline/text/script.py`), Preeti conversion (`pipeline/looma_pipeline/text/preeti.py`) | import | n/a | none |
| `pipeline/looma_pipeline/extractors/` | text from records (`pipeline/looma_pipeline/extractors/database.py`), PDF pages (`pipeline/looma_pipeline/extractors/pdf.py`), OCR (`pipeline/looma_pipeline/extractors/ocr.py`), captions (`pipeline/looma_pipeline/extractors/captions.py`), HTML (`pipeline/looma_pipeline/extractors/html.py`), page transcripts with the review gate (`pipeline/looma_pipeline/extractors/transcripts.py`, issue #2) | import | records, content files, `data/transcripts/*.jsonl` | none |
| `pipeline/looma_pipeline/chunking.py` | passage packing measured in model tokens | import | the model's tokenizer file | none |
| `pipeline/looma_pipeline/embedder.py` | model download, int8 quantization, ONNX inference | `prepare-model`, import | Hugging Face (prepare only), model files | `data/models/` |
| `pipeline/looma_pipeline/embedding_cache.py` | vectors cached by model and passage text | import | cache file | `data/cache/embeddings.sqlite` |
| `pipeline/looma_pipeline/word_index.py` | SQLite schema, FTS5 Devanagari tokenizer, dictionary | import | n/a | the bundle's `meta/chunks.db` |
| `pipeline/looma_pipeline/query_terms.py` | query terms, safe FTS5 expressions, dictionary expansion | import | `chunks.db` | none |
| `pipeline/looma_pipeline/search.py` | reference hybrid search with filters before the cut and spelling correction first | import, `search` | a bundle | none |
| `pipeline/looma_pipeline/spelling.py` | spelling vocabulary and symmetric-delete index (built in F8); corrects unknown query words | import | the bundle's SQLite file | F8 writes two tables |
| `pipeline/looma_pipeline/eval_typos.py` | typo tolerance evaluation, gates T1, T2, T3 and T5 | `eval-typos` | a bundle, `pipeline/eval/typo_pairs.jsonl` | `data/runs/eval-typos-<time>/` |
| `pipeline/looma_pipeline/fsutil.py` | hard link or copy, and atomic writes, for files that are never changed in place | import | files | creates files |
| `pipeline/looma_pipeline/retention.py` | which old bundles and run folders can go | `clean` | `data/bundles/`, `data/runs/` | with `--apply`, deletes the planned folders |
| `pipeline/looma_pipeline/baseline.py` | today's Looma search, for comparison | import | `looma-web` over HTTP | none |
| `pipeline/looma_pipeline/bundle.py` | keys, content hash, checksums, signature, verification | import | a bundle, keys | `data/keys/`, bundle files |
| `pipeline/looma_pipeline/verify.py` | full verification including the self-test with the bundle's own model | `verify` | a bundle | none |
| `pipeline/looma_pipeline/e2e.py` | end-to-end gate run G1-G10 | `e2e` | MongoDB, model, `looma-web` | two bundles, `data/runs/e2e-<time>/` |
| `pipeline/looma_pipeline/stages/` | one module per stage, `pipeline/looma_pipeline/stages/f01_snapshot.py` to `pipeline/looma_pipeline/stages/f13_bundle.py` (F1-F9, F12, F13) | called by `pipeline/looma_pipeline/pipeline.py` | see [architecture.md](architecture.md), section 5 | run-folder reports; F13 writes the bundle |
| `pipeline/eval/typo_pairs.jsonl` | hand-made typo and correct query pairs, and correctly spelled queries, for the typo evaluation | read by `eval-typos` | n/a | none |
| `pipeline/tests/` | pytest tests, test data (`pipeline/tests/looma_fixture.py`), PDF generators (`pipeline/tests/pdf_fixtures.py`), a stand-in embedder (`pipeline/tests/fake_embedder.py`) | `make pipeline-test` | temp folders; MongoDB and model when available | temp folders only |

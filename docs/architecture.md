# loomaai architecture

For: developers joining the project and reviewers of design changes. Covers what loomaai is for, the constraints it
works under, how its parts fit, and why. This version describes the existing prototype and the new build pipeline
(stages F1 to F13) added on branch `feat/p5-02-e2e-build-pipeline`.

Last verified: 2026-11-01 at 98f8a807 (design written first, then checked against the code and the end-to-end runs)

## 1. Goals and scope

Project 5 asks for search by meaning over Looma's library, search within a chapter, and short grounded answers
("Ask Looma"), all working offline on a Looma Box. The work is split into a **build plane** (an office or cloud
computer with internet, where all heavy work happens) and a **serve plane** (the Box, offline).

This document covers the build plane: the pipeline that turns Looma's data into one signed **index bundle**.

```
 F1 snapshot → F2 content map → F3 extract → F4 clean → F5 Nepali check → F6 chunk
   → F7 embed + F8 word index → F9 suggestions → F12 checks → F13 pack and sign
```

In scope now:
- text that is already in MongoDB: activity titles and taxonomy, lesson slides, game prompts, chapter titles,
  dictionary pairs;
- extractors for files (PDF pages, OCR, SRT/VTT captions, HTML) that are built and tested on small generated files.
  The content folder is empty on the development machine, so they are not yet validated on real Looma content.

Also here: the serve-plane search service `looma-search` (`pipeline/looma_pipeline/service.py`), which answers
search requests from one bundle. Out of scope here: the PHP bridge, Ask Looma tiers B and C, and Box measurements.

Quality goals, in priority order:
1. Never change curated data. The pipeline only reads MongoDB.
2. Repeatable. The same inputs give the same bundle content.
3. Safe to ship. A bundle is signed, and any changed byte or wrong model makes verification fail.
4. Works offline once built. Bundles hold the model files they need.
5. Same code for every scope (`pilot` or `all`), configured by environment variables.

## 2. Constraints

| Constraint | Source |
|---|---|
| MongoDB belongs to Looma-II (`looma-db` on network `loomanet`). This repo is a client and must not write curated fields. | the project's data-safety rule and the Looma-II interface contract |
| The Looma Box is an ODROID-C4: arm64, 4 GB RAM, offline in class. | Skip; Hardkernel product page |
| Languages: English, Nepali (Devanagari), romanized Nepali. Many Nepali fields are code-mixed. | measured 2026-10-28 on lesson slides |
| No PyTorch on the serve plane; CPU-only ONNX Runtime. | `rag-engineering` skill, section 10 |
| The embedding model is a provisional choice until the embedder experiment (EXP-002) and Skip decide. | the project's experiments-and-decisions rule |

## 3. Context (C4 level 1)

```
                 ┌──────────────────────────────┐
  content team   │  Looma-II (looma-web,        │
  edits data ───▶│  looma-db: MongoDB "looma")  │
                 └──────────────┬───────────────┘
                                │ read-only queries (pymongo)
                                ▼
 Hugging Face ──model files──▶ [ build pipeline (looma-pipeline image) ] ──▶ data/bundles/<bundle>/
 (pinned revision,             F1 … F13, runs on demand                        signed, read-only
  build plane only)             │                                               (later copied to Boxes)
                                └──HTTP POST (read-only search)──▶ looma-web (today's search, for comparison)
```

| Arrow | What flows | Direction | Protocol |
|---|---|---|---|
| looma-db → pipeline | activities, lessons, games, chapters, textbooks, dictionary | read only | MongoDB wire protocol |
| Hugging Face → pipeline | the embedder's ONNX file and tokenizer, at a pinned revision | download once | HTTPS |
| pipeline → looma-web | the five comparison questions, through `cmd=search` | read only | HTTP |
| pipeline → `data/` | run reports, embedding cache, bundles, signing key | write | local files |

## 4. Solution strategy

| Idea | Why |
|---|---|
| Build plane and serve plane are separate; the Box never builds. | The Box is too small; results become reproducible. |
| One immutable, signed bundle per build. | Boxes can switch back to the previous bundle; a signature proves origin. |
| The pipeline reads MongoDB through a wrapper that has no write methods. | Data safety is enforced in code, not only by convention. |
| Every stage writes a JSON report into its run folder. | A failed run says exactly where and why. |
| Embeddings are cached by model revision and passage text. | Reruns re-embed only new or changed passages. |
| Retrieval combines meaning (vectors) and words (FTS5), merged with RRF, with filters applied before the top-k cut. | Words win on exact terms, meaning on questions; narrow filters must still return results. |
| Checks (F12) run before the bundle is signed. | A bundle that fails its checks is never produced. |

## 5. Containers and building blocks (C4 level 2)

| Container or job | Responsibility | Technology and version | Code | Reads | Writes |
|---|---|---|---|---|---|
| `looma-pipeline` image (job) | runs F1 to F13, verify, search, e2e | Python 3.12, ONNX Runtime 1.31.1, SQLite 3.46.1 FTS5, Tesseract | `pipeline/` | looma-db (read only), `data/models/`, content folder (read only) | `data/runs/`, `data/cache/`, `data/bundles/`, `data/keys/` |
| `looma-search` (service) | answers `/search` and `/health` from one bundle; built for Looma-II to call with a time limit and fall back to its keyword search, but no Looma-II page calls it yet (the PHP bridge is not built) | Python 3.12, ONNX Runtime, waitress; `pipeline/Dockerfile.serve`, `docker-compose.search.yml` | `pipeline/looma_pipeline/service.py`, `pipeline/looma_pipeline/search.py` | one bundle and the public key (read only) | logs only |
| `looma-streamlit` | prototype admin pages (unchanged) | Streamlit 1.41.1 | `appai/` | looma-db, `looma-qdrant` | looma-db (see the prototype audit) |
| `looma-qdrant` | prototype vector store (unchanged; not used by the pipeline) | Qdrant | n/a | n/a | its volume |
| `looma-ollama` | prototype local LLM server (unchanged; not used by the pipeline) | Ollama | n/a | n/a | its volume |

Pipeline building blocks:

| Stage | Module | Input | Output |
|---|---|---|---|
| F1 snapshot | `pipeline/looma_pipeline/stages/f01_snapshot.py` | MongoDB (read only) | in-scope raw records, snapshot id and hash, curated-field checksum |
| F2 content map | `pipeline/looma_pipeline/stages/f02_content_map.py` | raw records, content folder | for each item: the file Looma would open, or why there is none |
| F3 extract | `pipeline/looma_pipeline/stages/f03_extract.py` + `pipeline/looma_pipeline/extractors/` | raw records, content map, page transcripts (`data/transcripts/`) | text pieces with page or time; PDF pages also carry printed page and text method |
| F4 clean | `pipeline/looma_pipeline/stages/f04_clean.py` | raw records, text pieces | normalized items (grades, chapter ids, language, CEHRD flag) |
| F5 Nepali check | `pipeline/looma_pipeline/stages/f05_nepali.py` | text pieces | language by script; Preeti conversion for legacy-font files |
| F6 chunk | `pipeline/looma_pipeline/stages/f06_chunk.py` | text pieces | small passages with stable ids `<item>:<lang>:<n>` |
| F7 embed | `pipeline/looma_pipeline/stages/f07_embed.py` + `pipeline/looma_pipeline/embedder.py` | passages, model files | int8 vectors; cache statistics; int8 vs full-size agreement |
| F8 word index | `pipeline/looma_pipeline/stages/f08_word_index.py` + `pipeline/looma_pipeline/spelling.py` | items, passages, dictionary | SQLite file with items, passages, FTS5 index, dictionary, spelling vocabulary and its symmetric-delete index |
| F9 suggestions | `pipeline/looma_pipeline/stages/f09_suggestions.py` | staged bundle | chapter → resource proposals (JSONL, never written to MongoDB) |
| F12 checks | `pipeline/looma_pipeline/stages/f12_checks.py` + `pipeline/looma_pipeline/search.py` | staged bundle | self-test queries, known-item and filter results, comparison with today's search |
| F13 pack and sign | `pipeline/looma_pipeline/stages/f13_bundle.py` + `pipeline/looma_pipeline/bundle.py` | staged bundle, model files, signing key | `data/bundles/<bundle>/` with manifest, checksums and signature |

## 6. Runtime views

### Build run
1. `make pipeline-build SCOPE=pilot` starts a container on `loomanet`.
2. F1 reads MongoDB through the read-only wrapper and records a checksum of curated fields.
3. F2 to F8 build the staged bundle in `data/runs/<run_id>/staging/`.
4. F12 opens the staged bundle with the reference search and runs the checks.
   If a check fails, the run stops with exit code 1 and no bundle is written.
5. F13 puts the staged files and model into a temporary folder, writes the manifest and `SHA256SUMS`, signs it,
   and renames the folder into `data/bundles/` in one step. Files are hard-linked, not copied, when the run folder,
   the model and the bundle share a filesystem (they do under `data/`). That is safe because no pipeline file is
   ever rewritten in place: writes go to a temporary file renamed over the target (`pipeline/looma_pipeline/fsutil.py`).
6. The run ends with one summary line: run id, counts, duration, bundle path.

### Verify
`make pipeline-verify BUNDLE=<name>` checks the signature, every file's checksum, the manifest against the model
files and the vectors, then runs the bundle's self-test queries. Any failure prints the reason and exits 1.

### Search (reference implementation)
The query is normalized; English and Nepali terms go to FTS5 (with dictionary expansion) and the query embedding
goes to an exact dot product over every passage in one pass. Filters become one mask over passages: disallowed
passages are dropped from the vector scores and skipped while reading FTS5 matches in rank order, so both lists are
filtered before the cut. They are merged with RRF (k = 60) and grouped by item. The same code serves F9, F12,
`verify` and `make pipeline-search`.

Restricting FTS5 inside SQL (`rowid IN (...)`) was tried first and rejected: SQLite re-ran the match once per
allowed row, about 3 s per query at 40,000 passages. Skipping gives the same lists, because FTS5 ranks with
whole-index statistics; measured at 12-19 ms per query on the full scope (experiment record, section 9).

Before both lists, spelling correction (`pipeline/looma_pipeline/spelling.py`) replaces each unknown query word,
one in neither the index nor the dictionary, with the nearest index word, keeping its capitalization. The meaning
search then embeds the corrected query and the word search looks for both wordings. Correctly spelled queries are
never changed, and real words typed by mistake ("plan" for "plant") are left alone; the evidence is in
[the typo tolerance experiment](experiments/2026-11-01-typo-tolerance.md). F9 searches chapter titles exactly as
written. Bundle schema 1.1 adds the spelling tables; a 1.1 reader treats a 1.0 bundle as having no correction.
Schema 1.2 adds five page-metadata columns to `passages` (`printed_page`, `text_method`, `source_run`,
`source_model`, `review_status`). Search does not read them yet, so a 1.2 reader handles 1.0 and 1.1 bundles
unchanged, and an older bundle's content hash is computed exactly as before.

### PDF pages with a page transcript
```
 PDF page (file sha256, page)
   ├─ usable transcript row? ── yes ─> transcript text ─> clean markers ─┐   OCR skipped for this page
   │     (reviewed; or unreviewed with TRANSCRIPTS_ALLOW_UNREVIEWED=1)    │
   └─ no ─> text layer / OCR ─> running header and footer cleanup ────────┤
                                                                          ▼
              F6 passage + page, printed_page, text_method, source_run, source_model, review_status
```
- Rows are matched by the PDF file's sha256 and 1-based page, so a replaced PDF never picks up an old transcript;
  such rows are reported as stale. Rejected rows are never used. For one page, a reviewed row replaces unreviewed
  ones; two different texts with the same status are both dropped and the page keeps its PDF text.
- Markers become plain text (`pipeline/looma_pipeline/text/markers.py`): caption labels stay ("Figure 4.6: ..."),
  figure, callout, screenshot and table words stay without tags, blanks and `[illegible]` go, cut-off labels keep
  their visible letters. Any other bracket is kept and listed in the F3 report, because it may be real text.
- F3 stops the run when a transcript file cannot be read or more than 1% of its rows are malformed.
- Every PDF page records how its text was made (`text`, `ocr` or `transcript`); a transcript page also records
  its printed page, transcription run, model and review status. F6 copies them to each passage.
- `page` is the PDF page Looma's viewer opens (`chapters.pn` is 77 for 10S04, used as `data-page` in Looma-II's
  `looma-chapters.php`); `printed_page` (73 there) is for display only.
- `pipeline/looma_pipeline/extractors/transcripts.py` reads the files; `pipeline/looma_pipeline/stages/f03_extract.py`
  uses them and reports used, stale, unmatched and malformed rows in the run folder's `f03_extract.json`.
- Evidence: [page transcript build](experiments/2026-11-26-pdf-transcript-ingest.md) and
  [quality evaluation](experiments/2026-11-27-transcript-quality.md).

## 7. Deployment

| Where | What runs | Notes |
|---|---|---|
| Developer machine (amd64, Docker) | `looma-pipeline` image on network `loomanet` | the only place builds run |
| Looma Box (arm64, offline) | `looma-search` with one bundle (`docker-compose.search.yml`); no builds | not verified on a Box yet |

Volumes: `data/` is mounted at `/data`, the content folder read-only at `/content`. The container runs as the host
user and has a 2 GiB memory limit. Measured peaks: 1,592 MB for a full-scope build and 1,666 MB for a full-scope
e2e run, of which 1,176 MB are the int8 and full-size model sessions loaded together in F7. The full-size model
serves only F7's int8 agreement report and is released straight after.

Disk on the build machine: a full-scope build adds about 92 MB (run reports plus the new index; the model is
shared by hard link) and a full-scope e2e run about 183 MB; the e2e run deletes its tampered copies. Old outputs are
removed with `make pipeline-clean` (a dry run unless `APPLY=1`; `pipeline/looma_pipeline/retention.py`), which keeps
the newest bundles and runs of each kind and never touches models, the embedding cache or keys.

## 8. Cross-cutting concepts

- **Data safety:** MongoDB is read through `pipeline/looma_pipeline/mongo_readonly.py`, which exposes only read methods and rejects
  aggregation stages that write (`$out`, `$merge`). F1 records a checksum of curated fields; the end-to-end test
  compares it before and after.
- **Provenance:** every run has a `run_id`; manifests record the snapshot hash, model revision and file hashes, the
  chunker settings and the code version. Each passage records how its text was made (`text_method`) and, for
  page-transcript text, the transcription run, model and review status.
- **Bilingual text:** text is NFC-normalized and stripped of zero-width joiners and byte-order marks. Language is
  decided by the share of Devanagari letters, not by the field it came from.
- **Configuration:** environment variables with defaults, read once in `pipeline/looma_pipeline/config.py` (see [configuration.md](configuration.md)).
- **Logging and errors:** JSON log lines; a stage that cannot continue raises a clear error; per-item failures are
  counted in the stage report, never silently dropped.
- **Security:** no secrets in the image; the signing key stays in `data/keys/` (ignored by Git); the container runs
  as a non-root user.

## 9. Decisions

No ADR is accepted yet. Provisional choices, each to be confirmed by an experiment and Skip:

| Choice | Provisional value | Decided by |
|---|---|---|
| Embedding model | `intfloat/multilingual-e5-small` at revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, int8 ONNX | EXP-002 |
| Vector store | int8 vectors in a NumPy file, exact search | EXP-003 |
| Passage size | target 200, at most 256 tokens, 32 tokens overlap | EXP-002 |

## 10. Quality requirements

The end-to-end check (`make pipeline-e2e`) decides whether the pipeline works. The gates were fixed before the first
run; results are in [testing.md](testing.md) and the experiment record.

| Gate | Requirement |
|---|---|
| G1 | curated-field checksum identical before and after; the read-only wrapper rejects writes |
| G2 | `make pipeline-build SCOPE=pilot` runs F1 to F13 with exit code 0 and every stage report present |
| G3 | verify passes; one changed byte is refused; a bundle built for another model is refused |
| G4 | a second build gives the same content hash and re-embeds 0 passages |
| G5 | the bundle's self-test queries pass after loading |
| G6 | 200 English titles: at least 95% found in the top 10; up to 200 Nepali titles: at least 90%; 0 CEHRD-only items returned |
| G7 | a one-chapter filter returns only that chapter's items, and is non-empty for at least 95% of pilot chapters with linked items |
| G8 | report only: today's search and the bundle side by side on five questions |
| G9 | unit and integration tests pass |
| G10 | time per stage, bundle size and search latency are recorded, labeled "dev machine, not Box numbers" |

These gates show the pipeline is correct, safe and repeatable. They do not measure search quality judged by people
(that needs the golden question set) or fit on the Box (that needs Box measurements).

## 11. Risks and technical debt

| Risk | Impact | Plan |
|---|---|---|
| File extractors are not validated on real Looma content | text quality unknown for PDFs, captions, HTML | rerun F3 to F5 when content arrives (open question S1) |
| Page transcripts are AI-made and none is reviewed yet | wrong text could reach students if `TRANSCRIPTS_ALLOW_UNREVIEWED=1` is used for a real bundle | default `0`; every passage records `review_status`; a review step is still to be agreed |
| The Preeti converter (`npttf2utf/`) is GPL-3.0 | licensing question for redistribution | recorded for Skip; it is used only on the build plane |
| Debian packages in the image (Tesseract, fonts) are not version-pinned | rebuilds can change OCR output | pinned base image digest; pin packages before release |
| Grade bands are provisional (age rule is open question S7) | filters may change | grade logic is isolated in `pipeline/looma_pipeline/grades.py` |
| No stage-level resume | a failed run restarts from F1 | reruns are cheap because embeddings are cached |

## 12. Glossary

| Term | Meaning |
|---|---|
| `activities` | MongoDB collection with one record per Looma resource; the unit search returns |
| `ft` | file type of an activity (`video`, `pdf`, `lesson`, `chapter`, …) |
| `dn` / `ndn` | display name in English / Nepali |
| `fp` / `fn` | file path / file name, relative to Looma's web root (`../content/...`) |
| `ch_id` / `nch_id` | chapter ids an activity is linked to (English / Nepali textbook) |
| `cl_lo` / `cl_hi` | curated lowest and highest grade for an activity |
| `key1`–`key4` | taxonomy levels; `key1` is the subject |
| `src` | content source (khan, wikipedia, CEHRD, …) |
| CEHRD | items whose file path starts with `../content/CEHRD`, shown only on the CEHRD server |
| EP | ePaath activity |
| Looma Box | the offline school computer (ODROID-C4) |
| Build plane / serve plane | where bundles are made (office) / used (Box) |
| Index bundle | the signed folder of vectors, word index, model and manifest that a Box reads |
| Passage | a small piece of text (about 200 tokens) with its item id and page or time |

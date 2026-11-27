# Experiment: Do page transcripts flow through the build with clean text and page metadata?

For: reviewers of issues #1 to #4 on ganesh-786/loomaai, and the next developer who adds transcripts. Covers whether
the pipeline uses page transcripts in place of PDF text (#2), cleans their markers (#3) and keeps page metadata on
each passage (#4), measured on one full-scope build.

| | |
|---|---|
| Date | 2026-11-26 (tests and bundle re-checked 2026-11-27) |
| Status | done |
| Owner | TEJ (ganesh-786) |
| Informs | issues #1 to #4; no decision yet |
| Code | built as `ca66da95-dirty` (the files of `857f4faf`). The same code is now split into `1730c33d` (#2), `9db243b2` (#3) and `be0c5999` (#4): `git diff 857f4faf be0c5999 -- Makefile pipeline` is empty, and a rebuild at `be0c5999` gives the same content hash (`6b13f338...`) |

- **What:** the new transcript path in F3, run once with unreviewed transcripts allowed (run A) and once without (run B).
- **How:** run D's 44 page transcripts, full scope (23,681 items), local `looma-db`, dev laptop; 9 targets.
- **Why:** 8 of 9 targets pass; target 5 fails on a defect in the gold caption file, not in the pipeline (section 6).

## 1. Question and hypothesis
Run D (a transcription of 44 page images) kept all 26 critical facts and all 26 figure captions that the PDF text
layer loses or damages ("46 (2×23)" became "46 (223)"); see the A-D extraction evaluation (section 8). The question
is whether the pipeline can use that text: match each transcript row to its PDF page, clean the markers, record where
the text came from, and still pass the existing build gates. Expected: every target passes.

## 2. Options under test
| Option | Exact id and version | License | Size on disk | Notes |
|---|---|---|---|---|
| Run A | `build --scope all`, `TRANSCRIPTS_ALLOW_UNREVIEWED=1` | n/a | bundle 185 MB, run folder 43 MB | uses the 44 unreviewed rows |
| Run B | `build --scope all --until f03`, `TRANSCRIPTS_ALLOW_UNREVIEWED=0` (default) | n/a | run folder 5.6 MB | checks the review gate only |

The transcripts are run D's output (`run: D-claude-direct-read`, model `claude-opus-5-5`), made by an AI model and not
reviewed by a person. They are used here only to test the plumbing. They are not approved content.

## 3. Setup
- Hardware: development laptop (WSL2, x86-64), container limit 2 GiB. Every time and memory figure is from this
  machine: **not Box numbers**.
- Software: image `looma-pipeline:dev` (Python 3.12, pinned `pipeline/requirements.lock`), embedder
  `intfloat/multilingual-e5-small@614241f622f53c4eeff9890bdc4f31cfecc418b3`, int8 ONNX.
- Data: local `looma-db` (curated checksum `8e58fba1...`, unchanged), Looma's content folder mounted read only.
- Transcripts: `data/transcripts/D-claude-direct-read.jsonl` (44 rows, sha256 `ac4a08d2...`). Converted from run D's
  `pages.jsonl`: the `text` of every row is unchanged; `file_sha256` (of the PDF), `model` and
  `review_status: unreviewed` were added; run D's counter fields and `item_id` were dropped (rows match by file hash).
  Pages: Grade 10 Science `Science_10_0016.pdf` PDF pages 77-114 (chapter 10S04, printed 73-110) and 3 pages each of
  two PhET guides.
- To reproduce (run A reads MongoDB read only and writes `data/runs/` and `data/bundles/`):
```bash
make pipeline-build SCOPE=all TRANSCRIPTS_ALLOW_UNREVIEWED=1 PIPELINE_CONTENT_DIR=<content sample folder>
docker run --rm --network loomanet --memory 2g --user $(id -u):$(id -g) \
  -v $PWD/data:/data -v <content sample folder>:/content:ro \
  -e TRANSCRIPTS_ALLOW_UNREVIEWED=0 looma-pipeline:dev build --scope all --until f03
make pipeline-test
```
  The content sample is the main checkout's `data/content/` (3 PDFs, listed with sha256 in its `manifest.json`).
  Looma's default content folder is empty on the development machine, so a build against it extracts no PDF text.
  The image copies the code in at build time. The 2026-11-27 runs used the 2026-11-02 image with the branch's
  `pipeline/` mounted read only over `/app/pipeline` (dependencies unchanged), which tests the same code without a
  rebuild.

## 4. Metrics and gate (fixed before running)
The targets were written before the runs. The plan lived in a session scratch folder that has since been cleared;
the list below is copied from the run summary written at the time.

| # | Target |
|---|---|
| 1 | Run A, F3: 44 transcript pages, 44 rows used, 0 stale, 0 unmatched, 0 malformed |
| 2 | Run B, F3: 0 transcript pages, 44 rows skipped as unreviewed |
| 3 | 0 known marker tags left in the passages of the 3 items |
| 4 | 26/26 critical facts (for example "2×23") found in the bundle |
| 5 | 26/26 figure captions found in the bundle |
| 6 | Every passage from the 44 pages carries provenance; every textbook page has `printed_page` |
| 7 | Item metadata of the 3 items: grades, grade source and subject as expected |
| 8 | Build gates G5-G7 pass, `verify` ok, peak memory under the 2 GiB limit |
| 9 | hit@3 on 48 queries over the whole bundle: report only, no gate |

## 5. Results

| # | Result | Pass? | Re-checked 2026-11-27 |
|---|---|---|---|
| 1 | 44 pages · 44 used · 0 stale · 0 unmatched · 0 problems · 0 unknown markers | pass | yes, `f03_extract.json` |
| 2 | 0 pages · 44 skipped unreviewed · 1 page went to OCR instead | pass | yes, `f03_extract.json` |
| 3 | 0 known tags, and 0 `[...]` of any kind, in 104 passages | pass | yes, SQL on `chunks.db` |
| 4 | 26/26 (`gold/probes.jsonl`) | pass | yes: 26/26 as exact text, as words split at spaces, and with the A-D harness |
| 5 | **25/26**: F07 not found | **fail** | yes, see section 6 |
| 6 | 104 passages from 44 (item, page) pairs; all `transcript` / `D-claude-direct-read` / `claude-opus-5-5` / `unreviewed`; 38/38 textbook pages have `printed_page`, 0 differ from the transcript; the 6 PhET pages have none (their transcript rows have none either) | pass | yes |
| 7 | Heredity (10S04): 10-10, chapter · Gene Expression Guide: 9-10, curated · Natural Selection Guide: 9-11, chapter · all Science | pass | yes |
| 8 | G5 20/20 · G6 English 198/200 (0.99), Nepali 200/200 · G7 1,645/1,645 chapters, 0 outside · `verify ok` · peak 1,652 MB (F7) | pass | yes: rebuilt at `be0c5999` (bundle `2026.11.27-all-r5`), same gates, `verify ok` |
| 9 | 42/48 = 0.875 | info | yes: re-run on both bundles, 42/48 each; analysed in the [quality evaluation](2026-11-27-transcript-quality.md) |

Other figures from run A (not Box numbers): stage times add up to 226 s; search p50 26.2 ms, p95 64.6 ms
(G10, 400 queries); 23,681 items, 40,265 passages (31,266 English, 8,733 Nepali, 266 mixed).

Marker counts in run A's F3 report: 26 figure captions, 19 figure text, 5 callouts, 5 screenshot text, 4 tables,
3 cut off, 3 blank, 1 concept map.

Unit and integration tests: `pytest` in the pipeline image, 2026-11-27, code `857f4faf` and again at `be0c5999`:
**391 passed, 0 failed, 0 skipped** (about 31 s), MongoDB and model tests included.

## 6. Analysis

### Target 5: a defect in the gold file, recorded and not fixed
- **What:** gold caption F07 in the A-D evaluation's `gold/captions.json` reads `"Figure 4.7Structure of RNA"`, with
  no space between the figure number and the title. The bundle has `"Figure 4.7: Structure of RNA"` (1 passage).
  The other 25 gold captions all separate the number from the title.
- **Why the result depends on the matcher:** the same gold file against the same bundle gives

  | Matcher | Found |
  |---|---|
  | words split at spaces, exact (this experiment's target 5) | 25/26, F07 missing |
  | the A-D harness tokenizer (`evalx.tokens`), exact | 26/26 |
  | the A-D harness, up to 10% edits (`evaluate.py`, T5) | 26/26 |

  At spaces, `4.7Structure` is one word that appears nowhere in the bundle. The harness tokenizer splits letters from
  digits, and the A-D evaluation also allowed 10% edits, so the defect stayed hidden there.
- **Why the gold file has it:** the A-D plan says the gold captions were read by Claude from page images
  (`plan.md`, line 48). Nobody has checked them by hand.
- **Why it is not fixed here:** target 5 was fixed before the run, and changing the gold file or the matcher after
  seeing the result would move the target. The verdict stays "fail" with this cause. The caption itself is in the
  bundle.
- **To close it:** a person checks F07 against the page image (crops are in the A-D folder) and corrects the gold
  file. The other 25 captions and the 26 facts need the same check before any number based on them is quoted as
  final.

### Other findings
- **The review gate holds.** Without the setting, all 44 rows were skipped and the pages kept their PDF text. One of
  those pages needs OCR (run B: `pages_ocr: 1`). In run A, that page took the transcript and OCR was skipped, which is
  what `skip_ocr` is for.
- **Page numbers.** `page` is the 1-based PDF page and `printed_page` the number printed on it (10S04: 77 and 73).
  Looma opens a chapter at the PDF page (`chapters.pn` is 77 for 10S04, used as `data-page` in Looma-II's
  `looma-chapters.php`), so links must use `page`; `printed_page` is for display.
- **A bug the tests caught.** The caption pattern also matched "Figure **text**:" as a caption. A test failed, the
  pattern now needs a figure number, and both marker types are counted separately.
- **Target 9 is not comparable** with the A-D evaluation's 1.000: that searched only the 44 pages, this searched all
  23,681 items. The 6 misses were examined on 2026-11-27: in all of them the expected page's text is in the bundle,
  and search shows a neighbouring page of the right item or ranks other items first
  ([quality evaluation](2026-11-27-transcript-quality.md), section 6).

### Threats to validity
- 3 items and 44 pages, all from one transcription run, all English. Nepali pages and other books are untested.
- The transcripts are unreviewed AI output. The run proves the plumbing, not that the text is correct.
- Targets 4 and 5 use gold files made by the same kind of model that made the transcripts.
- Dev-machine numbers only.

## 7. Conclusion
The pipeline uses page transcripts end to end: rows match by file hash and page, the review gate keeps unreviewed text
out by default, markers are cleaned without losing caption or figure words, and every passage records how its text
was made and its printed page. The one failed target is caused by the gold file. Still open: a person reviews the
transcripts and the gold files, search's choice of page within an item is improved, and transcripts for Nepali pages
are tried.

## 8. Artifacts
None of these are in Git.

| Artifact | Location | sha256 | Size |
|---|---|---|---|
| Transcripts used | `data/transcripts/D-claude-direct-read.jsonl` | `ac4a08d2ce7149eaf1c7f57e2bcf2a35e70bde64d9e9e179d4038d80a3ea49ca` | 76.6 KB |
| Run A | `data/runs/20261126T173318Z-all-cc83/` | n/a | 43 MB |
| Run B | `data/runs/20261126T173744Z-all-30ea/` | n/a | 5.6 MB |
| Bundle | `data/bundles/looma-ai-bundle-2026.11.26-all-r1/` | content hash `6b13f3387225065c2033fe9ac030c96887d483b5fcc8ea58a7980d48c05cbeb1` | 185 MB |
| Rebuild at `be0c5999` | `data/bundles/looma-ai-bundle-2026.11.27-all-r5/` (run `20261127T055134Z-all-30ba`) | same content hash | 185 MB |
| Gold captions (with the F07 defect) | `data/content/extracted/eval-2026-11-26-extraction-ABCD/gold/captions.json` | `4bd3b1cd7e90d336d74655b03d34f12a0ba50a712f3684a3e2f41c7109a58aba` | 26 entries |
| A-D evaluation (plan, harness, report) | `data/content/extracted/eval-2026-11-26-extraction-ABCD/` | n/a | n/a |

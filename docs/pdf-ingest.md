# Page-level PDF ingest

For developers who build Looma's search index. After reading this, you can run the page-level PDF ingest, read its
output, and tell why a page or an item was skipped.

Last verified: 2026-11-27 at 92c1136a

## What it does

`python -m appai.cli.ingest_pdfs` reads Looma PDFs page by page and writes one JSON record per page. It covers
textbook chapters (their English page range), `pdf` activities and `worksheet` activities. It runs on the build
plane only; the Looma Box never runs it.

```text
looma-db (read only)                 content folder (local copy)        output (only with --write)
activities ─┐                        <fp><fn>  the PDF                  data/ingest/<run_id>/
textbooks  ─┼─ which file, which ──► │                                    pages.jsonl   one record per page
chapters   ─┘   pages (pn, len)      ├─ transcript for this page? ──►     report.json   counts, reasons, versions
                                     │    yes, passes the gate → transcript text → marker cleaning (M1-M9)
                                     │    no                   → PDF text layer   → text-layer cleaning (C1-C4)
```

- It reads MongoDB with `find`, `find_one` and `ping` only. It writes nothing to MongoDB or Qdrant.
- It downloads nothing. Every PDF comes from the local content folder.
- `appai/common/embed.py` is unchanged; this is a separate path.
- Every page is cleaned before it is written, and every line the cleaning removes is listed in the report
  ([Cleaning](#cleaning)).
- Every record carries Looma's metadata as stored in MongoDB, plus a grade range and a printed page number that
  each record where they came from ([Looma metadata](#looma-metadata)). Curated fields are only read.

## Run it

You need the Looma-II stack running (it provides `looma-db`) and a local copy of Looma's content folder. The
examples use `data/content`.

Dry run (prints a summary, writes nothing):

```bash
python -m appai.cli.ingest_pdfs --content-dir data/content --ch-id 10S04 --linked
```

Write the output:

```bash
python -m appai.cli.ingest_pdfs --content-dir data/content --ch-id 10S04 --linked --write \
  --transcripts <transcript run folder>
```

The same run in the `loomaai` image, with the repository and content folder mounted read-only:

```bash
docker run --rm --network loomanet -e MONGO_URI=mongodb://looma-db:27017 \
  -v "$PWD:/repo:ro" -v "$PWD/data/content:/content:ro" -w /repo \
  loomaai:latest /app/.venv/bin/python -m appai.cli.ingest_pdfs --content-dir /content --ch-id 10S04 --linked
```

Expected last line of a dry run:

```text
run_id=pdfingest-<time>-<hash> items={'ok': 3} pages=44 methods={'text_layer': 44} duration_s=<s> output=dry-run (nothing written)
```

Checked on 2026-11-27 against the local `looma-db`: chapter 10S04 and its 2 linked PDFs gave 3 items, 44 pages.
With unreviewed transcripts and the default gate, all 44 pages used the text layer (`transcript_unreviewed`).
With `--allow-unreviewed`, all 44 used the transcript. On the text layer, the cleaning removed the running footer
from 44 pages and 1 page number, joined 1 line-break hyphen and kept 4. PDF page 93 of 10S04 is a concept-map image
whose text layer holds only the footer, so it is listed in `empty_pages`. Timings were dev-machine numbers, not
Box numbers.

## Options and settings

| Option | Environment variable | Default | Meaning |
|---|---|---|---|
| `--ch-id` | n/a | none | Chapter id such as `10S04`. Repeatable. |
| `--linked` | n/a | off | With `--ch-id`, also take the `pdf` and `worksheet` items whose `ch_id` holds it. |
| `--activity-id` | n/a | none | An `activities._id`. Repeatable. |
| `--all` | n/a | off | Every chapter, `pdf` and `worksheet` activity. |
| `--content-dir` | `CONTENT_DIR` | none (required) | Local copy of Looma's content folder. |
| `--transcripts` | n/a | none | A transcript run folder. Repeatable. |
| `--allow-unreviewed` | `TRANSCRIPTS_ALLOW_UNREVIEWED=1` | off | Also use unreviewed transcripts. Rejected ones are never used. |
| `--write` | n/a | off | Write `pages.jsonl` and `report.json`. Without it, nothing is written. |
| `--out` | `INGEST_OUT_DIR` | `data/ingest` | Output root. |
| `--run-id` | n/a | generated | Name of the run folder. An existing run is never overwritten. |
| `--mongo-uri` | `MONGO_URI` | `mongodb://localhost:47017` | MongoDB address. |
| `--mongo-db` | `MONGO_DB` | `looma` | Database name. |
| n/a | `CODE_COMMIT` | `unknown` | Commit recorded in the report. |

You must choose items with `--ch-id`, `--activity-id` or `--all`. Only English is in scope: an item with
`lang` other than `en`, `both` or unset is skipped with `language_not_in_scope`.

Exit codes: `0` done; `1` done, but some items failed (see `report.json` `items`); `2` a setting is wrong or MongoDB
can't be reached.

## Where the pages come from

| Item | File | Pages |
|---|---|---|
| Chapter | `textbooks.fp` + `textbooks.fn` (the English textbook) | `chapters.pn` to `chapters.pn + chapters.len - 1` |
| `pdf`, `worksheet` | `activities.fp` + `activities.fn` (default folder `../content/pdfs/`) | every page |

Paths that point outside the content folder are refused (`path_outside_content_dir`).

## Transcripts and the review gate

A transcript run folder holds `report.json` (the run, its method and the sha256 of each input PDF) and
`pages.jsonl` (one row per page: `file`, `page`, `text`, optional `printed_page` and `review_status`). A row's
`review_status` overrides the run's.

A transcript replaces a page's text layer only when all of these hold:

1. It was made from the same PDF bytes (same sha256). Otherwise: `transcript_stale_sha256`.
2. Its status is `approved`, or `unreviewed` with `--allow-unreviewed`. A `rejected` row is never used.
3. Usable transcripts of the page agree. Otherwise: `transcript_conflict`.

When no transcript is used, the record says why in `fallback_reason`: `no_transcript`, `transcript_stale_sha256`,
`transcript_unreviewed`, `transcript_rejected` or `transcript_conflict`. Rows that can't be used at all are listed in
`report.json` `transcript_problems` (`transcript_header_invalid`, `transcript_malformed`).

## Page record (`pages.jsonl`, schema `looma.pdf_page/1`)

| Field | Meaning |
|---|---|
| `schema`, `run_id` | Record format and the run that made it. |
| `record_id` | `<item id>:<lang>:p<PDF page>`. |
| `source` | `collection`, `item_id`, `ft`, `file` (relative to the content folder), `file_sha256`, `pdf_page` (1-based), `printed_page` and `printed_page_source`. |
| `looma` | `ch_id` (list), `dn`, `ndn`, `lang`, `subject` (`key1`-`key4`) and `grade` (`lo`, `hi`, `source`, `raw`, `conflict`). See [Looma metadata](#looma-metadata). |
| `text` | The cleaned page text. |
| `text_method` | `transcript` or `text_layer`. |
| `fallback_reason` | Why the text layer was used, or `null`. |
| `transcript` | `run`, `model`, `review_status`, `line` of the transcript used, or `null`. |
| `review_status` | `approved`, `unreviewed` or `unchecked` (text layer). |
| `checked` | `true` only for an approved transcript. |
| `cleaning` | Text layer: `lines_removed`, `hyphens_joined`, `hyphens_kept`. Transcript: `markers`, a count per marker type. |
| `quality` | `chars` and `words` of `text`. |

## Run report (`report.json`)

It holds the run id, schema, whether it was a dry run, the time, `code_commit`, Python and PyMuPDF versions, the
configuration, the transcript runs loaded and their problems, a hash of the records (`content_sha256`, equal for two
runs over the same input), one entry per item with its status, reason, grade source and printed-page offset vote,
counts of grade and printed-page sources, every removed line (`removed_lines`:
item, PDF page, line, rule), every line-break hyphen decision (`hyphens`), counts of markers, removed lines and
hyphens, the pages left with no text (`empty_pages`), duration and peak memory (dev-machine numbers, not Box
numbers).

## Cleaning

The rules were fixed before any results were seen. C2 was changed once after the pilot (the first version left
the footer on all 6 PhET pages); the comment in `appai/common/text_cleaning.py` records why.

Text layer (all pages of one item together):

| Rule | What it does |
|---|---|
| C1 | Unicode NFC; ligatures U+FB00-FB06 become letters; soft hyphen, zero-width space and BOM are removed. ZWJ and ZWNJ stay, because Devanagari needs them. |
| C2 | Removes running lines (footers and headers) in items with 3 or more pages. The running line is the line found on the most pages (3 or more), at a page edge on at least one page, and on at least half the pages. Matching lines go wherever they sit, because PyMuPDF's text order puts the footer mid-page on some pages. Lines that are only a number at a page edge go too. |
| C3 | Joins `word-` + line break + `word` only if the joined word appears elsewhere in the item; otherwise it keeps `word-word`. |
| C4 | Turns non-breaking and other spaces into one space, strips lines, keeps at most one blank line in a row. |

Transcripts (one page at a time: C1, then M1-M9, then C4):

| Rule | Marker | Result |
|---|---|---|
| M1 | `[Figure N: caption]` | `Figure N caption` |
| M2 | `[Figure text: a; b]` | `a; b` |
| M3 | `[Callouts: ...]`, `[Screenshot text: ...]` | their words |
| M4 | `[Table]` rows `[End table]` | rows, cells joined by `; `, empty cells dropped |
| M5 | `[Concept map]` ... `[End concept map]` | the lines, arrows kept |
| M6 | `[blank]` | dropped |
| M7 | `x[cut off]` | `x` |
| M8 | `[illegible]` | dropped |
| M9 | any other `[Name: ...]` | its words, counted as `unknown_marker`; other brackets such as `[1]` stay as printed |

Markers are resolved innermost first, because cut-off labels sit inside figure text. Unpaired block tags and
unbalanced brackets are counted (`unpaired_block_tag`, `unbalanced_bracket`) so a reviewer can find them.

## Looma metadata

Fields copied as stored (read only):

| Record field | From | Note |
|---|---|---|
| `looma.ch_id` | chapter: its `ID`; other items: `activities.ch_id` | a string or an array in MongoDB; always a de-duplicated list here |
| `looma.dn`, `looma.ndn` | `activities.dn`, `activities.ndn` | English and Nepali titles |
| `looma.lang` | `activities.lang` | `en` for a chapter, because only its English textbook pages are read |
| `looma.subject` | `activities.key1`-`key4` | as stored |

Grade (`looma.grade`), first rule that applies:

| `source` | Rule |
|---|---|
| `chapter_id` | A chapter's grade from its id (`10S04` is grade 10). |
| `activity_cl` | `cl_lo` and `cl_hi`, when both are grades 1-12 and `cl_lo <= cl_hi`. Some documents store these keys with a leading BOM (`﻿cl_lo`); both spellings are read, and `conflict` is `true` when they disagree. |
| `linked_chapters` | Otherwise the lowest and highest grade of the chapters in `ch_id`. This is inferred, not curated. |
| `none` | Nothing usable. `lo` and `hi` are `null`. |

`raw` keeps the stored grade fields unchanged, so a reviewer can see what the rule started from. `0` counts as "not
set", because documents such as the natural-selection guide below store `0`/`0`.

Printed page (`source.printed_page`), first that applies:

| `printed_page_source` | Rule |
|---|---|
| `transcript` | The page number written in the transcript row used for the page. |
| `footer_offset` | The PDF page minus an offset voted from the page numbers in removed footer lines. The vote needs 3 or more agreeing numbers and at least twice the runner-up's votes. A number on half the footer lines (the 10 of "Grade 10") or below half its PDF page (an OCR fragment) doesn't vote. |
| `none` | No reliable number. |

Links keep using `pdf_page`, because Looma's viewer opens a chapter at `chapters.pn`, a PDF page.

Checked on 2026-11-27 with chapter 10S04 and its 2 linked PDFs:

- 10S04 got grade 10 from its id. The gene-expression guide got 9-10 from `cl_lo`/`cl_hi`. The natural-selection
  guide stores `0`/`0`, so it got 9-11 from its linked chapters (`linked_chapters`).
- 10S04's footer numbers voted for offset 4 (4 votes against 1): PDF pages 77-114 are printed pages 73-110. On all
  38 pages this matches the page number in the transcript. The PhET guides have no page numbers and get `none`.

## Why an item was skipped or failed

| Reason | Status | Meaning |
|---|---|---|
| `no_page_range` | skipped | `chapters.pn` or `len` is empty or not a positive number. |
| `no_english_textbook` | skipped | The textbook has no English file (`fn`). |
| `language_not_in_scope` | skipped | The item isn't English. |
| `type_not_in_scope` | skipped | The item isn't a chapter, `pdf` or `worksheet`. |
| `chapter_activity_not_found` | failed | No chapter activity has that `--ch-id`. |
| `activity_not_found` | failed | No activity has that `--activity-id`. |
| `bad_chapter_id` | failed | The chapter id doesn't match Looma's pattern. |
| `textbook_not_found` | failed | No textbook record for the chapter. |
| `textbook_record_incomplete` | failed | The textbook record lacks a field it needs. |
| `chapter_not_found` | failed | No `chapters` document for the chapter. |
| `no_file_name` | failed | The activity has no `fn`. |
| `path_outside_content_dir` | failed | The stored path escapes the content folder. |
| `missing_file` | failed | The PDF isn't in the content folder. |
| `unreadable_file` | failed | The path is a folder or can't be read. |
| `unreadable_pdf` | failed | PyMuPDF can't open the file, or it has no pages. |
| `damaged_pdf` | failed | PyMuPDF had to repair the file, so its text may be incomplete. |
| `page_range_out_of_bounds` | failed | The chapter's page range is outside the file. |

Skipped reasons are facts about the data. Failed reasons need someone to fix the data or the content folder.

# Experiment: How good are the cleaned transcript passages and their metadata?

For: reviewers of issues #2 to #4 on ganesh-786/loomaai, and whoever decides when transcript text may reach students.
Covers the quality of the text, chunking, metadata and search results of the 44 transcript pages once the pipeline
has plumbed, cleaned and stored them.

| | |
|---|---|
| Date | 2026-11-27 |
| Status | done |
| Owner | TEJ (ganesh-786) |
| Informs | issues #2 to #4; the review step for transcripts (no decision yet) |
| Code | `be0c5999` on `feat/p5-05-passage-page-metadata`; first run on bundle `2026.11.26-all-r1` (code `857f4faf`, identical) |

- **What:** 14 checks (Q1-Q14) on the 104 passages that came from run D's 44 page transcripts.
- **How:** bundle `meta/chunks.db` read only, the A-D gold files, local `looma-db` read only, the production search.
- **Why:** text, chunking and metadata pass every check (Q1-Q11, Q13); page-exact search fails (Q12: 0.875 < 0.90),
  because search shows one page per item and sometimes picks a neighbouring page.

## 1. Question and hypothesis
The [page transcript build](2026-11-26-pdf-transcript-ingest.md) showed that transcripts flow through the build.
This asks whether what arrives is right: are words lost or added by cleaning, do symbols survive, are passages the
right size, is the metadata correct against `looma-db`, and does search find the right page? Expected: all pass.

## 2. Options under test
One configuration: bundle `looma-ai-bundle-2026.11.27-all-r5` (code `be0c5999`, `TRANSCRIPTS_ALLOW_UNREVIEWED=1`,
content sample, 23,681 items, 40,265 passages). The first run used `looma-ai-bundle-2026.11.26-all-r1`; both bundles
have the same content hash (`6b13f338...`) and gave byte-identical Q1-Q11 results.

## 3. Setup
- Hardware: development laptop (WSL2, x86-64). Times are **not Box numbers**.
- Gold data, made 2026-11-26 for the A-D extraction evaluation: 40 hand-read lines (`lines_gold.tsv`), 26 critical
  facts (`probes.jsonl`), 26 captions (`captions.json`), 53 queries (`queries.jsonl`: 33 body, 7 image, 8 PhET,
  5 with no relevant source). The A-D plan says they were read by Claude from page images; no person has checked them.
- Text checks use a separate reference cleaner (not `text/markers.py`), so the pipeline is not checked against itself.
- Search: `SearchEngine` with the bundle's own model, run with `--network none`, spelling on, `k = 10`.
- To reproduce (scripts and results are in `data/eval/2026-11-27-transcript-quality/`, not in Git):
```bash
python3 text_meta_eval.py <worktree> <A-D eval folder> mongo_items.json looma-ai-bundle-2026.11.27-all-r5
docker run --rm --network none --memory 2g --user $(id -u):$(id -g) -v $PWD/data:/data:ro \
  -v $PWD/pipeline:/app/pipeline:ro -v <eval folder>:/eval:ro -v <A-D gold folder>:/gold:ro \
  --entrypoint python looma-pipeline:dev /eval/retrieval_eval.py /data/bundles/<bundle> /gold/queries.jsonl
```
  `mongo_items.json` is a read-only export of the 3 items' `activities` records (`dn`, `ft`, `cl_lo`, `cl_hi`,
  `ch_id`, `key1`, `ID`).

## 4. Metrics and gate (fixed before running)
Written to `plan.md` before any result was computed. Q1 and Q12 reuse the A-D gates (T3 and T7).

| # | Check | Target |
|---|---|---|
| Q1 | accuracy against the 40 gold lines | WER ≤ 2.0 %, CER ≤ 1.0 % |
| Q2 | transcript words kept in the page's passages | every page ≥ 99 %, overall ≥ 99.5 % |
| Q3 | words in passages that are not in the transcript | 0 |
| Q4 | symbols (× → = + % & — •) kept | 100 % |
| Q5 | table pipes, running footers, bare page numbers, empty passages | 0 each |
| Q6 | passage size ≤ 256 tokens | 104/104 |
| Q7 | language tag of the English pages | 104/104 `en` |
| Q8 | `printed_page` = PDF page − 4 on the textbook | 38/38 |
| Q9 | grade band, grade source and subject against `looma-db` (curated, else chapter, else unknown) | 3/3 |
| Q10 | chapter links against `looma-db` `ch_id` | 3/3 |
| Q11 | every PDF-page passage in the bundle has `text_method` | 100 % |
| Q12 | right item in the top 3 and showing an expected page (48 answerable queries) | ≥ 0.90 |
| Q13 | queries with no relevant source do not bring the 3 items into the top 3 | 5/5 |
| Q14 | item hit@1/3/10, MRR@10, Grade 10 + Science filter, latency | report only |

Q11 counts passages with a page number. HTML documents have no page and no method by design (`models.py`), so they
are not PDF pages.

## 5. Results

| # | Result | Pass? |
|---|---|---|
| Q1 | WER 0.0 %, CER 0.0 % (360 words, 40 lines) | pass |
| Q2 | 100 % (9,955 words, 0 lost) | pass |
| Q3 | 0 | pass |
| Q4 | 114/114 | pass |
| Q5 | 0 pipes, 0 footers, 0 page-number lines, 0 empty passages | pass |
| Q6 | max 200 tokens, median 176; 1 passage under 30 tokens | pass |
| Q7 | 104 `en` | pass |
| Q8 | 38/38 | pass |
| Q9 | Heredity 10-10 chapter, Gene Expression Guide 9-10 curated, Natural Selection Guide 9-11 chapter, all Science | pass |
| Q10 | 3/3 (Natural Selection Guide links `9S04`, `10S04`, `11SS04.01`) | pass |
| Q11 | 1,074/1,074 (970 text, 104 transcript) | pass |
| Q12 | **0.875** (42/48, 95 % interval 0.75-0.94) | **fail** |
| Q13 | 5/5 | pass |

Q14 (report only):

| | No filter | Grade 10 + Science |
|---|---|---|
| Item hit@1 / @3 / @10 | 0.875 / 0.958 / 1.000 | 0.896 / 1.000 / 1.000 |
| Item MRR@10 | 0.925 | 0.948 |
| Page-exact hit@3 | 0.875 | 0.875 |
| By category, page-exact hit@3 | body 0.848, image 0.857, PhET 1.000 | body 0.848, image 1.000, PhET 0.875 |
| Search p50 / p95 (r5 run) | 30.6 / 70.4 ms | 23.2 / 38.5 ms |

### The checks can fail
Eight defects were planted in a scratch copy of `chunks.db` (a dropped word, × turned into x, a leftover tag and a
pipe, a wrong printed page, a wrong grade, an extra chapter link, a missing `text_method`, a misspelled word). Each
was caught by the check meant for it. That script ran inline and was not saved.

## 6. Analysis

### Why Q12 fails
Search returns one hit per item, with that item's best passage and its page. In all 8 misses (6 without the filter,
6 with it, 4 shared) the evidence sentence of the query is in the bundle on the expected page.

| Kind | Queries | What happened |
|---|---|---|
| Neighbouring page shown | Q01, Q07, Q17, Q19, Q33, Q41 | the right item at rank 1, a page 1-2 away shown; pages of one chapter score within 0.01-0.03 |
| Other items ranked first | Q28 (rank 4), Q38 (rank 7) | "Tomatoes", "Potato" and "seeds" items outrank the chapter; the Grade 10 + Science filter puts it in the top 3 |

- Ranking only the right item's passages by meaning similarity puts the expected page first for Q07, Q28 and Q38,
  2nd-3rd for Q01, Q19 and Q41, and 4th-5th for Q17 and Q33. For Q07 and Q38, the word-search side of the fusion
  moves the shown page away from it; Q28 shows the right page, but its item ranks 4th.
- Q33 is a wording gap: the answer page says "IVF", the query "in vitro fertilization".
- Some gold labels look too narrow: page 82 also defines karyokinesis (Q01), page 96 also says "Mendel studied seven
  pairs" (Q17), and page 3 also holds Q41's evidence. With Q01 and Q17 widened, Q12 would be 44/48 = 0.917. The labels
  are not changed after seeing the results; a reviewed gold set is needed first.
- This is a search behavior (one page per item, fusion choosing the page), not a text or metadata problem. A change
  needs its own experiment with a gate fixed first.

### Threats to validity
- The gold lines, facts, captions and labels were made by the same model family as the transcripts, so an error
  both share scores as correct (Q1 = 0 % may be optimistic).
- Small samples: 44 pages, 40 lines, 48 queries; English only.
- Page 108 reads "isnot"; it is in the transcript too. Whether the book prints it that way is not verified.

## 7. Conclusion
The cleaned transcript text and its metadata are correct on every check: nothing lost, nothing added, symbols kept,
passages within size, and grade, subject, chapter and page metadata matching `looma-db`. Search finds the right item
(0.958, 1.000 with the Grade 10 filter) but shows the expected page in only 0.875 of queries, below the 0.90 gate.
Open: a person reviews the gold files and the transcripts; search's choice of page within an item gets its own
experiment.

## 8. Artifacts
In `data/eval/2026-11-27-transcript-quality/` (not in Git). `text_meta_eval.py` gained a bundle-name argument after
the first run; the logic did not change.

| File | sha256 |
|---|---|
| `plan.md` (targets, written first) | `00ec2c439ba1d9bea2262c3938b29b7294231ab77c721bb6101ae33970dbb866` |
| `text_meta_eval.py` | `e667fc9f7e21c9b14d1fe1917c64c4ff66e8e62ab1a9c664361d0ffec629b92a` |
| `retrieval_eval.py` | `a36a72aa97686516b1047722d236fdafb9b90ea6c175abf378e579573e0a045f` |
| `within_item.py` | `0d997f224cda630d2a948aebe4c4925765f1d4bc4f93c58a54ab0c1bfff2196d` |
| `mongo_items.json` | `5b208bfcac664531ce7288aba6cbce30b589debbbc256bac1f19097dbf9275d5` |
| `text_meta_results.json`, `text_meta_results_r5.json` (identical) | `f8f93c1df3672c849aa763442f1b6b168845c8792857af7bffdec039fee08e50` |
| `retrieval_results.json` (r1) | `05be76f7f144dbde78838d6c32714f954d1ae4904f420b38937724971ffe6246` |
| `retrieval_results_r5.json` | `7b9f37f7a05e3cbc45100374502815ef58db18a65fec84ca559a5cf7ce13900b` |
| `within_item_results.jsonl` | `4af50989dabd262e19963d9342f723123bee852c1d2e41daf64a092807eff778` |

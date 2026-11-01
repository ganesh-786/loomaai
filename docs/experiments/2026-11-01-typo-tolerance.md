# Experiment: Can search tolerate students' typos without changing results for correctly spelled queries?

| | |
|---|---|
| Date | 2026-11-01 |
| Status | done |
| Owner | Ganesh (TEJ) |
| Informs | no decision yet: the serve-plane search design in `../architecture.md` |
| Code | branch `feat/p5-02-e2e-build-pipeline`; commits listed in section 8 |

## 1. Question and hypothesis

Students misspell words. On the full-scope bundle `looma-ai-bundle-2026.11.01-all-r6`, a misspelled query and its
correct spelling shared only 2 to 8 of their top 10 results (12 hand-made pairs, measured before this record). Two
kinds of typo behave differently:

- **Unknown words** (`nutritoin`, `enviroment`, `democrasy`, `tapa`): not in the word index, so the word search finds
  nothing for them, and the meaning search sees broken word pieces.
- **Real words typed by mistake** ("How does plan make food?"): "plan" is in 46 passages, and the dictionary expands it
  to "योजना", which pulls in a Nepali meal-plan lesson. In passages that also contain "make" and "food", "plant" is
  only about twice as likely as "plan" (co-occurrence 10 and 16 against 11 and 2, weighted by frequency).

Hypothesis: correcting unknown words from the bundle's own vocabulary makes typo queries return what the correct
spelling returns, without touching correctly spelled queries. Real-word slips can only be suggested ("Did you
mean ...?"): the corpus evidence is too weak to change results.

## 2. Options under test

| Option | What it does | Size on disk | Notes |
|---|---|---|---|
| A, baseline | no spelling help (search as at `2aba695a`) | 0 | |
| B, spelling help | unknown words corrected automatically; real-word slips suggested only | measured | details below |

Option B, as built:
- F8 stores every index word with a letter, no digit and at least 4 characters, with its document frequency, plus a
  symmetric-delete index (Garbe, SymSpell, 2012): keys are the first 7 characters with up to 2 deleted.
- A query word is **unknown** if it is in neither the index vocabulary nor the English-Nepali dictionary. It is
  replaced by the nearest index word, by Damerau-Levenshtein distance (at most 1 edit for words up to 6 characters,
  2 for longer ones). Ties go to the word that appears with more of the query's other words, then to the more
  frequent word.
- A **known** word gets a suggestion only if the query has other known words, and a word one edit away (not just a
  plural or other inflection) appears with every one of them, is at least as frequent, and is at least 1.5 times as
  likely under a smoothed co-occurrence model. The ratio 1.5 was chosen after seeing the plan/plant figures above;
  the clean-query checks below guard against it firing too often.
- The meaning search embeds the corrected query. The word search looks for the original and the corrected words.
  Suggestions do not change results.

## 3. Setup
- Hardware: 12-CPU laptop, WSL2, Docker 29.9.2. Dev-machine numbers, not Box numbers.
- Software: image `looma-pipeline:dev` built from the commit under test (Python 3.12, ONNX Runtime 1.31.1, SQLite
  3.46.1); embedder `intfloat/multilingual-e5-small` at `614241f6`, int8.
- Data: the full scope of the local MongoDB copy (23,681 items, 40,212 passages), built into one bundle; options A
  and B run on that same bundle (A with spelling turned off).
- Test sets, fixed before the run:
  1. **Synthetic typos, English**: 200 items sampled as in G6 (seed 20261101, CEHRD-only items left out). In each
     title the longest word of at least 5 letters gets one random edit (delete, insert, substitute or swap two
     neighbours; seeded), redrawn until the result is an unknown word.
  2. **Synthetic typos, Nepali**: the same for 200 Devanagari titles. Report only: real Nepali typing errors need a
     native speaker's review.
  3. **Hand-made pairs**: `pipeline/eval/typo_pairs.jsonl`, 30 English and 3 Nepali typo and correct pairs (two
     are a user's own queries), plus 14 correctly spelled queries. Whether a pair is an unknown-word or a
     real-word pair is decided from the bundle's vocabulary when the evaluation runs.
  4. **Clean queries**: the 400 G6 title queries (200 English, 200 Nepali), the correct half of every pair, and the
     14 correctly spelled queries.
- To reproduce:
```bash
make pipeline-build SCOPE=all
make pipeline-eval-typos BUNDLE=<the new bundle>
make pipeline-e2e SCOPE=all
```

## 4. Metrics and gate (fixed before running)
- Quality: known-item recall@10 on the synthetic typos (found = the item, or an item with the same title, in the top
  10, as in G6); overlap@10 between the results of a typo query and of its correct spelling; share of pairs whose
  correction (unknown words) or suggestion (real words) equals the correct spelling.
- Safety: corrections and suggestions made on clean queries.
- Cost: added search latency p50/p95 (spelling on against off, same queries), bundle growth, F8 time.
- Gates for option B:

| Gate | Pass if |
|---|---|
| T1 | English synthetic typos: recall@10 at least 0.90 |
| T2 | hand-made unknown-word pairs: mean overlap@10 at least 0.70, and the correction equals the correct spelling for at least 85% of them |
| T3 | clean queries: no automatic corrections at all; suggestions on at most 2% |
| T4 | the full-scope e2e run still passes G5, G6 and G7 |
| T5 | added search latency p95 at most 15 ms |
| T6 | bundle growth at most 20 MB |

Real-word suggestions and the Nepali sets are reported, not gated.

## 5. Results

All runs on the full-scope bundle `looma-ai-bundle-2026.11.01-all-r8` (23,681 items, 40,212 passages), dev machine,
not Box numbers.

### Option B as planned: fails T3
`make pipeline-eval-typos`, run `eval-typos-20261101T135014Z`:

| Gate | Result | Measured |
|---|---|---|
| T1 | PASS | English synthetic typos recall@10 0.979 (option A: 0.876) |
| T2 | PASS | 25 unknown-word pairs: mean overlap@10 0.964 (A: 0.476); correction equals the correct spelling for 23 (0.92) |
| T3 | **FAIL** | 447 clean queries: 0 corrected, **9 suggested** (2.01%, limit 2%) |
| T5 | PASS | measured over unequal query sets, see below |

Suggestions made on correctly spelled queries: "five year plan" → "give hear play", "make a plan" → "make a play",
"Does This Look White" → "write", "Tick It Right" → "pick", "Our national days" → "ways", "Health Support" →
"healthy", "Social Studies 11 (Nepali)" → "nepal", "हाम्रा खानेकुरा" → "हाम्रो", "एक चिहान" → "चिह्न". On the 5
real-word pairs, 3 suggestions were right (both "plan" queries, "dessert animals"), 1 wrong ("parts of a flour" →
"four") and 1 missing ("photosyntesis", which is itself in a Looma title).

### Option B2: B without suggestions, keeping the typed capitalization
Changed after seeing B's results (see section 6): suggestions removed; corrections keep the case a word was typed
in; the synthetic generator keeps the title's case too (it had lowercased the edited word). One more harness fix
came from reading the first B2 report: latency had been timed over unequal query sets (401 off, 881 on), so every
query is now timed both ways, alternately. Final run `eval-typos-20261101T135611Z` at `22e028d1`:

| Gate | Result | Measured |
|---|---|---|
| T1 | PASS | English synthetic typos recall@10 **0.989** (184/186; option A: 0.855, 159/186; 14 titles skipped) |
| T2 | PASS | 25 unknown-word pairs: mean overlap@10 **0.964** (A: 0.476); fixed 23/25 (0.92); same top hit 0.92 |
| T3 | PASS | 447 clean queries: **0 corrected**; no suggestions are made |
| T4 | PASS | full-scope e2e `e2e-20261101T135626Z`: G5 20/20, G6 English 199/200 and Nepali 200/200, G7 1,645/1,645 (and again at `98f8a807`, `e2e-20261101T141011Z`) |
| T5 | PASS | 848 queries timed both ways: p50 18.3 against 18.0 ms, p95 45.5 against 43.0 ms (**+2.5 ms**) |
| T6 | PASS | bundle 191.2 MB against 176.2 MB (**+15.1 MB**): 32,081 words, 753,750 delete keys; F8 +2.5 s |

Reported, not gated:

| Set | Option A | Option B2 |
|---|---|---|
| Nepali synthetic typos, recall@10 (182 titles; 18 skipped) | 0.962 | **1.000** (corrected back to the original word: 180) |
| Nepali hand-made pairs, mean overlap@10 (3) | 0.233 | **1.000**, all 3 fixed |
| Real-word pairs, mean overlap@10 (5) | 0.46 | 0.46 (left alone by design) |

Hand-made pairs, option A against B2 (overlap@10 with the correct spelling):

| Typo | A | B2 | Searched for |
|---|---|---|---|
| How does plan make food? | 0.1 | 0.1 | unchanged (real word) |
| why does plan make food? | 0.3 | 0.3 | unchanged (real word) |
| nutritoin | 0.3 | 1.0 | nutrition |
| respiraton in plants | 0.0 | 1.0 | respiration in plants |
| area of a triangel | 0.2 | 1.0 | area of a triangle |
| gautam budha | 0.3 | 1.0 | gautam buddha |
| bhimsen tapa | 0.4 | 1.0 | bhimsen thapa |
| fotosynthesis | 0.8 | 1.0 | photosynthesis (2 edits) |
| volcanos and earthquaks | 0.2 | 0.7 | volcano and earthquake |
| the human hart | 0.5 | 0.5 | the human **part** (wrong) |
| पनीको चक्र | 0.2 | 1.0 | पानीको चक्र |

The full table of 33 pairs is in the report.

## 6. Analysis
- Unknown-word correction works as hypothesised: every misspelled word that is not a word of the index or the
  dictionary is corrected to an existing index word, and correctly spelled queries are never changed (0 of 447).
  The meaning search alone already tolerates many typos (option A finds 0.855 of English typo titles); correction
  closes most of the gap, and for Nepali it closes all of it on these samples.
- Real-word suggestions were rejected on evidence. Comparing co-occurrence likelihoods without an error model favours
  any more frequent neighbour, so correct queries get changed. A proper noisy-channel error model (Mays, Damerau
  and Mercer, 1991) needs the alternative to be about 20 times as likely; "plant" is only 1.7 times as likely as "plan"
  next to "make" and "food" in Looma's text, so no threshold separates them from "five year plan". Fixing real-word
  slips needs another signal: what students retype after a failed search (query logs, a privacy decision for Skip),
  or a language model judging the sentence (the small Box LLM tiers).
- Remaining errors: "hart" became "part", not "heart": both are one edit away and "part" appears with "human" more
  often; telling them apart needs sound-alike or keyboard-distance information. "Old Nepag 00094" was corrected but
  its item still missed, the known near-identical numbered-title problem (G6's one miss).
- Threats to validity: B2 was defined after B's results, so its design saw the clean set; it removes a feature and
  adds no threshold, which limits the risk. The hand-made pairs were written by the developer, not collected from
  students, and the synthetic typos are uniform random edits, not real typing errors. Nepali typo patterns need a
  native speaker's review. Latency is from a 12-CPU laptop.

## 7. Conclusion
Correcting unknown words from the bundle's own vocabulary makes typo queries return what the correct spelling
returns (overlap 0.964 against 0.476) at +2.5 ms and +15 MB, without changing any correctly spelled query: B2 is
in use, provisionally. Real-word slips such as "plan" for "plant" are not handled, and corpus co-occurrence cannot
handle them safely; that stays open, with query logs or a language-model check as the candidates.

## 8. Artifacts

| Artifact | Location | sha256 | Size |
|---|---|---|---|
| option B report (fails T3) | `data/runs/eval-typos-20261101T135014Z/report.json` (not in Git) | `0bf596bd14c41976d7228e58fd53b3c6a2b6f4fff8ef088754a9e160dc9f3f41` | 19,001 bytes |
| option B2 report (final) | `data/runs/eval-typos-20261101T135611Z/report.json` (not in Git) | `cb6913e76af366dd2d635e9c5f4df4f944db34e87952256dd0894b8f6c2fa330` | 16,378 bytes |
| full-scope e2e with spelling | `data/runs/e2e-20261101T135626Z/e2e-report.json` (not in Git) | `5c9476206a156d303a2b4284abcd9892f8ac7b5cf30c8ae3f02028bfb11b1bce` | 5,990 bytes |
| evaluated bundle | `data/bundles/looma-ai-bundle-2026.11.01-all-r8/` (not in Git) | manifest says `c899268c`: built from uncommitted changes on top of it, whose table-building code is unchanged in `22e028d1`; the e2e bundles at `22e028d1` have the same spelling tables (G4 content hash `2bddd48c…`) | 191,227,862 bytes |
| test pairs | `pipeline/eval/typo_pairs.jsonl` (in Git) | committed before the run in `c899268c` | 47 lines |

Commits on `feat/p5-02-e2e-build-pipeline`: `3d1fa315` this record's plan and gates, `c899268c` the hand-made pairs,
`22e028d1` spelling correction and the evaluation.

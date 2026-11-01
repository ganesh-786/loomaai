# Experiment: Can search tolerate students' typos without changing results for correctly spelled queries?

| | |
|---|---|
| Date | 2026-11-01 |
| Status | running |
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
Not run yet.

## 6. Analysis
Not run yet.

## 7. Conclusion
Not run yet.

## 8. Artifacts
Not run yet.

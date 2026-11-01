# Changes from the prototype

For: reviewers comparing this branch with upstream `de3b4b9`, and anyone deciding what to keep from the prototype.
Covers what was added, what was left unchanged, and which prototype problems the new pipeline avoids.

Last verified: 2026-11-01 at 865883ff

## What changed
- **Added `pipeline/`**: a separate build pipeline (F1 to F13) with its own image, tests and pinned dependencies.
- **Added `pipeline-*` targets** to the `Makefile`. Existing targets are unchanged.
- **Added `docs/`.**
- **Nothing in `appai/` changed.** The prototype still has the problems listed below; the pipeline does not use it.

## Prototype problems and how the pipeline handles them

| Prototype problem (audit id) | Where | In the pipeline |
|---|---|---|
| No chunking: one vector per whole document, cut at the model limit (B1) | `appai/common/embed.py` | F6 cuts small passages (about 200 tokens) covering the whole text |
| English-only model; Nepali ignored (B2) | `appai/common/embed.py` | multilingual model; Nepali titles, slides and pages are indexed; 200/200 Nepali titles found (G6) |
| Only four file types embedded (B3) | `appai/common/embed.py` | every activity gets at least its title; lessons and games add their text |
| Overwrites curated `cl_lo`/`cl_hi` in MongoDB (B4) | `appai/common/embed.py` | read-only wrapper; curated checksum identical before and after (G1) |
| Chapter links without score, provenance or undo (B6) | `appai/common/populate_relevant_resources.py` | F9 writes proposals to a file with run id, model, score and status `proposed`; never MongoDB |
| One-list RRF, no filters (B7) | `appai/common/query.py` | two lists (meaning, words), filters applied before the cut, RRF k = 60 |
| Downloads from looma.website at build time (B8) | `appai/common/activity_pdf.py` and others | reads a mounted content folder; no downloads except the pinned model |
| `.env` copied into the image; unpinned images (B11) | `Dockerfile`, `docker-compose.yml` | allow-list build context, no secrets; base image pinned by digest; dependencies frozen |
| Caption timestamps over an hour not parsed (B13) | `appai/cli/captions.py` | parser handles `HH:MM:SS,mmm` and `MM:SS.mmm` (tested) |
| `npttf2utf` default map path points to a missing file | `npttf2utf/base/fontmapper.py` | the pipeline passes `npttf2utf/files/map.json` explicitly |

## Impact
- No change for anyone using the prototype or Looma-II: the pipeline only reads MongoDB and writes under `data/`.
- New: signed index bundles in `data/bundles/`. Nothing reads them yet; the serve-plane service is later work.

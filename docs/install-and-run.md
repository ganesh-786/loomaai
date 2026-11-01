# Install and run

For: a developer setting up loomaai for the first time, or running the build pipeline (F1 to F13). Covers the
prerequisites, the pipeline commands with what each writes, and every `make` target in the repository.

Last verified: 2026-11-01 at b1b63e54 on a laptop with WSL2 (Linux 6.18), Docker 29.9.2, Compose 5.6.1. The
pipeline targets were run; the prototype targets (`appai/`) are described from the Makefile and were not re-run.

## Prerequisites

| Need | Version | Check with |
|---|---|---|
| Looma-II running (network `loomanet`, container `looma-db`) | local Looma-II stack | `docker ps --filter name=looma-db` |
| Docker with Compose v2 | Docker 29.9.2 used | `docker compose version` |
| Free disk | about 1 GB for the image, 0.6 GB for the model, 0.14 GB per pilot bundle, 0.18 GB per full bundle | `df -h .` |
| Free memory | 2 GiB for the pipeline container (`--memory 2g`); measured peak 1,666 MB | `free -h` |
| Network, once | to download the embedder from Hugging Face | `make pipeline-model` |

You don't need Python on the host for the pipeline: everything runs inside the `looma-pipeline` image.

## Build pipeline: first run

1. Start Looma-II so that `looma-db` is up on the `loomanet` network.
   Check: `docker ps --filter name=looma-db` shows the container.
2. Build the image.
   ```bash
   make pipeline-image
   ```
   Check: `docker images looma-pipeline:dev` shows an image of about 770 MB.
3. Download and prepare the embedder (network, about 490 MB, once).
   ```bash
   make pipeline-model
   ```
   Check: the command prints `model_key` and the SHA-256 of each file. Files go to `data/models/`.
4. Run the tests.
   ```bash
   make pipeline-test
   ```
   Check: the last line says `passed` with no failures.
5. Build a bundle for the pilot scope. Reads MongoDB (read only); writes `data/runs/` and `data/bundles/`.
   ```bash
   make pipeline-build SCOPE=pilot
   ```
   Check: the last line names the bundle, for example `data/bundles/looma-ai-bundle-2026.11.01-pilot-r1`.
6. Verify it, and try a search.
   ```bash
   make pipeline-verify BUNDLE=looma-ai-bundle-2026.11.01-pilot-r1
   make pipeline-search BUNDLE=looma-ai-bundle-2026.11.01-pilot-r1 Q="how do plants make food"
   ```
   Check: `verify` prints `"ok": true` and eight passed checks.

To run every gate at once (two builds, verification, tampered copies, tests), use `make pipeline-e2e SCOPE=pilot`.
It took 57 s on the machine above and writes its report to `data/runs/e2e-<time>/e2e-report.md`.

`SCOPE=all` builds every activity in MongoDB (23,681 items, 40,212 passages). Measured on the machine above:

| Command | Time | Peak memory |
|---|---|---|
| `make pipeline-build SCOPE=all`, first time (every passage embedded) | about 6 min, of which 3.6 min embedding | not measured |
| `make pipeline-build SCOPE=all`, vectors cached | 1 min 58 s | 1,592 MB |
| `make pipeline-e2e SCOPE=all` | 4 min 12 s | 1,666 MB |

The first-time figure is estimated from a build whose F7 embedded 36,124 new passages in 218 s.

To stop a run, press Ctrl+C or run `docker stop <container>`. The stage that was running writes its report with
status `interrupted`, the command exits with 130 (Ctrl+C) or 143 (`docker stop`), and no bundle is written.

## Make targets

| Target | What it does | Writes data | Needs the network |
|---|---|---|---|
| `make pipeline-image` | builds the `looma-pipeline:dev` image from `pipeline/Dockerfile` | no | first build only (base image, packages) |
| `make pipeline-model` | downloads the pinned embedder and writes its int8 model | `data/models/` | yes, once |
| `make pipeline-test` | runs the unit and integration tests in the image | no (pytest temp folders only) | no |
| `make pipeline-info` | prints the effective settings, without secrets | no | no |
| `make pipeline-build` | runs F1 to F13 for `SCOPE` (`pilot` or `all`) | `data/runs/`, `data/cache/`, `data/bundles/`, `data/keys/` (first run) | no; reads `looma-db` read only |
| `make pipeline-keygen` | creates the bundle signing key pair if missing | `data/keys/` | no |
| `make pipeline-verify` | verifies `BUNDLE`: signature, checksums, model, content hash, self-test | no | no |
| `make pipeline-search` | searches `BUNDLE` for `Q` with the reference search | no | no |
| `make pipeline-e2e` | builds `SCOPE` twice, verifies, tampers copies, runs the tests, decides G1 to G10 | `data/` as for a build, plus `data/runs/e2e-<time>/` | no; HTTP to `looma-web` for the comparison |
| `make setup-host` | prototype: creates `env/` and installs `requirements.txt` | `env/` | yes |
| `make build` | prototype: builds the `loomaai` image. **Copies `.env` into the image** | Docker image | yes |
| `make rmi` | prototype: removes the image and runs `docker system prune -f` (machine-wide) | Docker | no |
| `make update` | prototype: `git pull` in this folder | working tree | yes |
| `make run` | prototype: starts Streamlit, Qdrant and Ollama with `docker compose up -d` | containers | no |
| `make halt` | prototype: stops those containers | no | no |
| `make status` | prototype: lists those containers | no | no |
| `make logs` | prototype: follows their logs | no | no |
| `make shell` | prototype: opens a shell in `looma-streamlit` | no | no |
| `make split` | prototype: downloads textbooks from looma.website and writes chapter PDFs | `data/` | yes |
| `make pull_model` | prototype: pulls `llama3.2:3b` into Ollama | Ollama volume | yes |
| `make embed-all` | prototype: deletes and rebuilds the Qdrant collection. **Writes `cl_lo`/`cl_hi` into MongoDB.** Ask before running | Qdrant, MongoDB | yes |
| `make embed-missing` | prototype: like `embed-all` without deleting. **Writes MongoDB.** Ask before running | Qdrant, MongoDB | yes |
| `make translate-lessons` | prototype: LLM translation of every lesson. **Overwrites `lessons.data[].nepali`.** Ask before running | MongoDB | yes |
| `make translate-missing-lessons` | prototype: the same for lessons without a `translated` field. **Writes MongoDB** | MongoDB | yes |
| `make assign-chapters-resources` | prototype: adds `ai_ch_id` to activities. **Writes MongoDB.** Ask before running | MongoDB | no |
| `make video-captions` | prototype: downloads videos and transcribes them with Whisper | `data/` | yes |
| `make translate-captions` | prototype: LLM translation of `.vtt` files | `data/` | yes |

## Run on a Looma Box

Not verified yet. The pipeline runs on the build machine only. A Box will receive signed bundles; copying,
verifying and switching bundles on a Box is later work.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `no tokenizer at ...: run make pipeline-model first` | the embedder is not prepared | run `make pipeline-model` |
| `ServerSelectionTimeoutError` | `looma-db` is not running or not on `loomanet` | start Looma-II, then retry |
| build stops at `f12_checks` with `checks failed` | a gate failed; no bundle was written | read `data/runs/<run_id>/f12_checks.json`, field `gates_failed` |
| `verify` fails at `signature` | the bundle was signed with another key | verify with the public key that signed it (`SIGNING_PUBKEY_PATH`) |
| G8 rows say `not run` | `looma-web` was not reachable | start Looma-II; G8 is report-only |

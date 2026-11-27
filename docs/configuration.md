# Configuration

For: anyone running loomaai or its build pipeline. Covers every environment variable, port, volume and model file,
with its default and the code that reads it.

Last verified: 2026-11-01 at 98f8a807

## Environment variables: build pipeline

Read once by `pipeline/looma_pipeline/config.py`. Defaults work inside the `looma-pipeline` container on `loomanet`.

| Variable | Default | Read by | Purpose | Example | Secret |
|---|---|---|---|---|---|
| `MONGO_URI` | `mongodb://looma-db:27017` | pipeline config | MongoDB to read (read only) | `mongodb://looma-db:27017` | no (credentials, if any, are hidden in reports) |
| `MONGO_DB` | `looma` | pipeline config | database name | `looma` | no |
| `PIPELINE_DATA_DIR` | `/data` | pipeline config | runs, cache, models, bundles, keys | `/data` | no |
| `PIPELINE_CONTENT_DIR` | `/content` | pipeline config | Looma's content folder, mounted read only | `/content` | no |
| `LOOMA_SERVER` | `looma` | pipeline config | `CEHRD` lets CEHRD-only items through | `CEHRD` | no |
| `EMBED_MODEL_REPO` | `intfloat/multilingual-e5-small` | pipeline config | embedder (provisional) | same | no |
| `EMBED_MODEL_REVISION` | `614241f622f53c4eeff9890bdc4f31cfecc418b3` | pipeline config | pinned model revision | same | no |
| `EMBED_QUERY_PREFIX` | `query: ` | pipeline config | prefix the e5 family needs on queries | same | no |
| `EMBED_PASSAGE_PREFIX` | `passage: ` | pipeline config | prefix the e5 family needs on passages | same | no |
| `EMBED_THREADS` | `4` | pipeline config | ONNX Runtime threads | `4` | no |
| `EMBED_BATCH_SIZE` | `32` | pipeline config | batch size for the full-size model only; the int8 model always embeds one text per call | `32` | no |
| `CHUNK_TARGET_TOKENS` | `200` | pipeline config | passage size to aim for | `200` | no |
| `CHUNK_MAX_TOKENS` | `256` | pipeline config | passage size limit | `256` | no |
| `CHUNK_OVERLAP_TOKENS` | `32` | pipeline config | tokens repeated between passages | `32` | no |
| `OCR_ENABLED` | `1` | pipeline config | OCR for scanned PDF pages | `0` | no |
| `OCR_LANGS` | `eng+nep` | pipeline config | Tesseract languages | `nep` | no |
| `LOOMA_WEB_URL` | `http://looma-web:8080` | pipeline config | today's search, for the G8 comparison | same | no |
| `SIGNING_KEY_PATH` | `<PIPELINE_DATA_DIR>/keys/release-ed25519.key` | pipeline config | private key that signs bundles | default | **yes**: never commit or share it |
| `SIGNING_PUBKEY_PATH` | `<PIPELINE_DATA_DIR>/keys/release-ed25519.pub` | pipeline config | trusted public key for `verify` | default | no |
| `PIPELINE_GIT_SHA` | `unknown` | pipeline config | code version written into manifests | set by the Makefile | no |
| `HF_HUB_OFFLINE` | `1` (image) | `huggingface_hub` | blocks network access except in `make pipeline-model`, which sets `0` | `1` | no |
| `HF_HUB_DISABLE_TELEMETRY` | `1` (image) | `huggingface_hub` | no telemetry | `1` | no |
| `ORT_DISABLE_TELEMETRY` | `1` (both images; also set by `pipeline/looma_pipeline/__init__.py` when unset) | ONNX Runtime | keeps ONNX Runtime from sending usage events; checked by `pipeline/tests/test_no_phone_home.py` | `1` | no |

## Make variables for the pipeline targets

| Variable | Default | Purpose |
|---|---|---|
| `SCOPE` | `pilot` | `pilot` (grades 5-6 Science and Social Studies) or `all` |
| `BUNDLE` | none | bundle name for `make pipeline-verify` and `make pipeline-search` |
| `Q` | none | query for `make pipeline-search` |
| `PIPELINE_IMAGE` | `looma-pipeline:dev` | image tag |
| `PIPELINE_CONTENT_DIR` | `/usr/local/var/www/content` | host content folder mounted read only at `/content` |
| `KEEP` | `2` | newest bundles and runs of each kind kept by `make pipeline-clean` |
| `APPLY` | empty | `1` makes `make pipeline-clean` delete; otherwise it only lists |
| `SEARCH_BUNDLE` | none | bundle folder in `data/bundles/` that `make search-up` serves |
| `SEARCH_IMAGE` | `looma-search:dev` | tag of the search service image |

## Environment variables: search service

Read by `pipeline/looma_pipeline/service.py` (`Policy.from_env`, `Listen.from_env`). `docker-compose.search.yml` sets
the first three; the image sets `SEARCH_HOST=0.0.0.0` and `SEARCH_PORT=47200`. `LOOMA_SERVER` is read here too.

| Variable | Default | Purpose | Example | Secret |
|---|---|---|---|---|
| `SEARCH_THREADS` | `4` | worker threads that answer requests | `4` | no |
| `SEARCH_GRADE_WINDOW` | `1` | `related` mode: chapter grade plus or minus this many grades (provisional, open question S7) | `1` | no |
| `SEARCH_MIN_SIMILARITY` | empty (off) | drop results below this cosine similarity; off until calibrated on the golden questions | `0.84` | no |
| `SEARCH_HOST` | `127.0.0.1` (`0.0.0.0` in the image) | address to listen on | `0.0.0.0` | no |
| `SEARCH_PORT` | `47200` | port to listen on | `47200` | no |
| `SEARCH_MAX_QUERY_CHARS` | `200` | longer queries are refused | `200` | no |
| `SEARCH_MAX_RESULTS` | `50` | largest `k` a request may ask for | `50` | no |
| `SEARCH_RELATED_MIN_RESULTS` | `3` | `related` mode widens to all subjects below this many results | `3` | no |

## Environment variables: prototype (`appai/`)

| Variable | Default | Read by | Purpose | Example | Secret |
|---|---|---|---|---|---|
| `MONGO_URI` | `mongodb://localhost:47017` (Makefile), `mongodb://looma-db:27017` (compose) | `appai/cli/*.py`, pages | MongoDB | same | no |
| `MONGO_DB` | `looma` | `appai/cli/*.py`, pages | database name | `looma` | no |
| `QDRANT_URL` | `http://localhost:46333` (Makefile), `http://looma-qdrant:6333` (compose) | `appai/cli/populate_mongo.py`, pages | Qdrant | same | no |
| `DATADIR` | `data` (Makefile), `/app/data/files` (compose) | `appai/cli/*.py`, pages | working files | same | no |
| `OPENAI_API_KEY` | none | `appai/common/llmselect.py`, `appai/cli/translate_lessons.py` | OpenAI | none | **yes** |
| `GOOGLE_API_KEY` | none | `appai/common/llmselect.py` | Gemini | none | **yes** |
| `OLLAMA_URL` | `http://looma-ollama:11434` (compose) | `appai/common/llmselect.py` | Ollama | same | no |

## Secrets
API keys and the signing key never go in the repository, in logs, or in an image. The prototype's `Dockerfile`
copies `.env` into the image, so `.env` must not contain real keys. The pipeline image copies only `pipeline/` and
`npttf2utf/` (see `pipeline/Dockerfile.dockerignore`). The signing key lives in `data/keys/`, which Git ignores.

## Ports and URLs

| Service | Container port | Host port and bind address | URL |
|---|---|---|---|
| pipeline | none | none | n/a (a job, not a service) |
| `looma-search` | 47200 | `47200` on `127.0.0.1` only, in `docker-compose.search.yml` | `http://127.0.0.1:47200/health`; Looma-II uses `http://looma-search:47200` on `loomanet` |
| `looma-streamlit` (prototype) | 4700 | `47000` on all interfaces in `docker-compose.yml` | `http://localhost:47000/loomaai` |
| `looma-qdrant` (prototype) | 6333 | `46333` on all interfaces | `http://localhost:46333` |
| `looma-ollama` (prototype) | 11434 | `11434` on all interfaces | `http://localhost:11434` |

## Volumes and files

| Host path | Mounted at | Holds | Size measured |
|---|---|---|---|
| `data/` | `/data` (pipeline) | `data/runs/`, `data/cache/embeddings.sqlite`, `data/models/`, `data/bundles/`, `data/keys/` | models 0.6 GB (1.1 GB if prepared before `e6da198e`, which copied the download instead of linking it); cache 82 MB; each full-scope build adds about 92 MB, see [install-and-run.md](install-and-run.md) |
| Looma's content folder | `/content`, read only | PDFs, captions, HTML | empty on the development machine |

## Models and index bundles

| Artifact | Location | Version or manifest | Size |
|---|---|---|---|
| Embedder (full size) | `data/models/intfloat--multilingual-e5-small/<revision>/model.fp32.onnx` | revision `614241f622f53c4eeff9890bdc4f31cfecc418b3` | 470 MB |
| Embedder (int8) | same folder, `model.int8.onnx` | the model folder's model_info.json records SHA-256 and quantization | 118 MB |
| Index bundle | `data/bundles/` (one folder per bundle, named looma-ai-bundle-DATE-SCOPE-rN) | its manifest.json and signed SHA256SUMS; schema 1.1 (with spelling tables) | 143 MB pilot, 191 MB full scope; on the build machine the model part (130 MB) is a hard link to `data/models/` |

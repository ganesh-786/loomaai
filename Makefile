# Makefile for managing Looma-II and loomaai

# Variables
LOOMA_AI_DIR := .
COMPOSE_FILE := docker-compose.yml

# Targets
.PHONY: build update run halt status

define setup_env
    export MONGO_URI=mongodb://localhost:47017; \
    export MONGO_DB=looma; \
    export QDRANT_URL=http://localhost:46333; \
    export DATADIR=data; \
    . ./.env; \
    . ./env/bin/activate;
endef

setup-host:
	@python3.12 -m venv env
	@env/bin/pip install --upgrade pip wheel "setuptools<71"
	@env/bin/pip install --no-build-isolation -r requirements.txt
	@env/bin/python -m nltk.downloader punkt
	@env/bin/python -m nltk.downloader punkt_tab


build:
	@echo "Building loomaai..."
	@docker build -t loomaai -f Dockerfile .
	@echo "Build complete."

rmi:
	@echo "Removing loomaai image..."
	@docker rmi loomaai
	@docker system prune -f
	@echo "Image removed."

update:
	@echo "Updating loomaai..."
	@git -C $(LOOMA_AI_DIR) pull
	@echo "Update complete."

run:
	@echo "Make sure Looma-II docker compose is running first!"
	@echo "Make sure your .env file is populated with the OpenAI api key"
	. ./.env
	@echo "Starting loomaai services..."
	@docker compose -f $(LOOMA_AI_DIR)/$(COMPOSE_FILE) up -d
	@echo "loomaai is running."

halt:
	@echo "Stopping loomaai services..."
	@docker-compose -f $(LOOMA_AI_DIR)/$(COMPOSE_FILE) down
	@echo "loomai services stopped."

status:
	@echo "Checking status of loomaai services..."
	@docker-compose -f $(LOOMA_AI_DIR)/$(COMPOSE_FILE) ps

logs:
	@echo "Showing logs for loomaai services..."
	@docker-compose -f $(LOOMA_AI_DIR)/$(COMPOSE_FILE) logs -f

shell:
	@echo "Opening a shell in the loomaai container..."
	@docker exec -it looma-streamlit /bin/bash

split:
	@$(setup_env) python3 -m appai.cli.split


pull_model:
	@echo "Pulling the latest model...for llama3.2:3b"
	@docker exec -ti looma-ollama /usr/bin/ollama pull llama3.2:3b

embed-all:
	@$(setup_env) python3 -m appai.cli.embed

embed-missing:
	@$(setup_env) python3 -m appai.cli.embed --missing-only

translate-lessons:
	@$(setup_env) python3 -m appai.cli.translate_lessons

translate-missing-lessons:
	@$(setup_env) python3 -m appai.cli.translate_lessons --missing-only

assign-chapters-resources:
	@$(setup_env) python3 -m appai.cli.populate_mongo

video-captions:
	@$(setup_env) python3 -m appai.cli.captions

translate-captions:
	@$(setup_env) python3 -m appai.cli.translate_captions

# ---- Build pipeline F1-F13 (docs/architecture.md) ----
# Reads looma-db read-only and writes only under data/. Runs in its own image on the loomanet network.
PIPELINE_IMAGE ?= looma-pipeline:dev
PIPELINE_CONTENT_DIR ?= /usr/local/var/www/content
SCOPE ?= pilot
KEEP ?= 2
# 1 also uses page transcripts nobody has reviewed yet (data/transcripts/*.jsonl); keep 0 for real bundles.
TRANSCRIPTS_ALLOW_UNREVIEWED ?= 0
PIPELINE_DOCKER = docker run --rm --network loomanet --memory 2g \
	--user $(shell id -u):$(shell id -g) \
	-v $(CURDIR)/data:/data -v $(PIPELINE_CONTENT_DIR):/content:ro \
	-e PIPELINE_GIT_SHA=$(shell git rev-parse --short HEAD) \
	-e TRANSCRIPTS_ALLOW_UNREVIEWED=$(TRANSCRIPTS_ALLOW_UNREVIEWED)

.PHONY: pipeline-image pipeline-test pipeline-info pipeline-build pipeline-model pipeline-keygen \
	pipeline-verify pipeline-search pipeline-e2e pipeline-eval-typos pipeline-clean

pipeline-image:
	@mkdir -p data
	docker build -f pipeline/Dockerfile -t $(PIPELINE_IMAGE) .

pipeline-test: pipeline-image
	$(PIPELINE_DOCKER) -w /app/pipeline --entrypoint python $(PIPELINE_IMAGE) -m pytest

pipeline-info: pipeline-image
	$(PIPELINE_DOCKER) $(PIPELINE_IMAGE) info

# Runs the build stages for SCOPE (pilot or all). Reads looma-db read only; writes data/runs/<run_id>/.
pipeline-build: pipeline-image
	$(PIPELINE_DOCKER) $(PIPELINE_IMAGE) build --scope $(SCOPE)

# Downloads the pinned embedder (network, about 500 MB once) and writes the int8 model into data/models/.
pipeline-model: pipeline-image
	$(PIPELINE_DOCKER) -e HF_HUB_OFFLINE=0 $(PIPELINE_IMAGE) prepare-model

# Creates the bundle signing key pair in data/keys/ if missing (the first build also does this).
pipeline-keygen: pipeline-image
	$(PIPELINE_DOCKER) $(PIPELINE_IMAGE) keygen

# Verifies a bundle: make pipeline-verify BUNDLE=<name in data/bundles/>
pipeline-verify: pipeline-image
	@test -n "$(BUNDLE)" || { echo "usage: make pipeline-verify BUNDLE=<name>"; exit 2; }
	$(PIPELINE_DOCKER) $(PIPELINE_IMAGE) verify $(BUNDLE)

# Searches a bundle: make pipeline-search BUNDLE=<name> Q="how do plants make food"
pipeline-search: pipeline-image
	@test -n "$(BUNDLE)" -a -n "$(Q)" || { echo 'usage: make pipeline-search BUNDLE=<name> Q="..."'; exit 2; }
	$(PIPELINE_DOCKER) $(PIPELINE_IMAGE) search $(BUNDLE) "$(Q)"

# End-to-end check of gates G1-G10: builds SCOPE twice, verifies, tampers, runs the tests. Writes data/ only.
pipeline-e2e: pipeline-image
	$(PIPELINE_DOCKER) $(PIPELINE_IMAGE) e2e --scope $(SCOPE)

# Typo tolerance on a bundle (gates T1, T2, T3, T5): make pipeline-eval-typos BUNDLE=<name>. Writes data/runs/ only.
pipeline-eval-typos: pipeline-image
	@test -n "$(BUNDLE)" || { echo "usage: make pipeline-eval-typos BUNDLE=<name>"; exit 2; }
	$(PIPELINE_DOCKER) $(PIPELINE_IMAGE) eval-typos $(BUNDLE)

# Lists old bundles and run folders that can go (newest KEEP of each kind stay; models, cache and keys never).
# Nothing is deleted unless APPLY=1: make pipeline-clean [KEEP=2] [APPLY=1]
pipeline-clean: pipeline-image
	$(PIPELINE_DOCKER) $(PIPELINE_IMAGE) clean --keep $(KEEP) $(if $(filter 1,$(APPLY)),--apply,)

# ---- Search service, serve plane (docs/install-and-run.md) ----
# The looma-search image holds only what search needs. SEARCH_BUNDLE is a folder name in data/bundles.
SEARCH_IMAGE ?= looma-search:dev
SEARCH_COMPOSE = SEARCH_BUNDLE=$(SEARCH_BUNDLE) docker compose -f docker-compose.search.yml

.PHONY: search-image search-image-arm64 search-up search-down search-health

search-image:
	docker build -f pipeline/Dockerfile.serve -t $(SEARCH_IMAGE) .

# Same image for an arm64 Box (Odroid C4), built with emulation on an x86 machine.
search-image-arm64:
	docker buildx build --platform linux/arm64 -f pipeline/Dockerfile.serve -t $(SEARCH_IMAGE)-arm64 --load .

search-up:
	@test -n "$(SEARCH_BUNDLE)" || { echo "usage: make search-up SEARCH_BUNDLE=<folder in data/bundles>"; exit 2; }
	$(SEARCH_COMPOSE) up -d

search-down:
	SEARCH_BUNDLE=unused docker compose -f docker-compose.search.yml down

search-health:
	curl -fsS http://127.0.0.1:47200/health

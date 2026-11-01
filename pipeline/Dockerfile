# looma-pipeline: the build-plane image that runs stages F1 to F13 (see docs/architecture.md).
# Runs on a developer or office machine only, never on a Looma Box. No secrets are copied in.
# Build from the repository root:  make pipeline-image
FROM python@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

# Tesseract with English and Nepali models for OCR of scanned pages; a Devanagari font for the OCR test
# fixtures. Debian package versions follow the pinned base image's release (see docs/architecture.md, risks).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-nep fonts-lohit-deva \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONPATH=/app/pipeline:/app

WORKDIR /app
COPY pipeline/requirements.lock /app/pipeline/requirements.lock
RUN pip install -r /app/pipeline/requirements.lock

# The Preeti-to-Unicode converter already in this repo (GPL-3.0; build plane only, see docs/architecture.md).
COPY npttf2utf/ /app/npttf2utf/
COPY pipeline/ /app/pipeline/

RUN useradd --uid 1000 --create-home pipeline
USER 1000

ENTRYPOINT ["python", "-m", "looma_pipeline"]
CMD ["--help"]

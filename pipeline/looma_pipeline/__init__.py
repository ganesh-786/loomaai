"""looma_pipeline: the build-plane pipeline that turns Looma's data into a signed index bundle.

Stages F1 to F13 are described in docs/architecture.md. Run it with `python -m looma_pipeline --help`
inside the `looma-pipeline` image (see `make pipeline-image`).
"""

import os

# ONNX Runtime 1.31 sends telemetry over HTTPS when it loads unless this is set first; Looma makes no outside
# connections (tests/test_no_phone_home.py). Set here so every entry point, with or without Docker, is covered.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

__version__ = "0.1.0"

# Bundle layout version. Bump the major part when a serve-plane reader would need to change.
# 1.1 adds the spelling tables; a 1.1 reader treats a 1.0 bundle as having no spelling help.
# 1.2 adds page metadata to passages (printed_page, text_method, source_run, source_model, review_status; issue #4).
# Search does not read them yet, so a 1.2 reader handles 1.0 and 1.1 bundles unchanged.
BUNDLE_SCHEMA_VERSION = "1.2"

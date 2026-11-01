"""looma_pipeline: the build-plane pipeline that turns Looma's data into a signed index bundle.

Stages F1 to F13 are described in docs/architecture.md. Run it with `python -m looma_pipeline --help`
inside the `looma-pipeline` image (see `make pipeline-image`).
"""

__version__ = "0.1.0"

# Bundle layout version. Bump the major part when a serve-plane reader would need to change.
BUNDLE_SCHEMA_VERSION = "1.0"

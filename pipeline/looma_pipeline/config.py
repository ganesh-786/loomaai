"""Pipeline settings, read once from environment variables.

Import only. Every setting has a default that works inside the `looma-pipeline` container on the `loomanet`
network; docs/configuration.md lists them all. No secrets are read here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

# Provisional embedder: multilingual, MIT license, 384 dimensions. The embedder experiment (EXP-002) and Skip decide
# the production model; this pin only makes runs repeatable.
DEFAULT_EMBED_MODEL_REPO = "intfloat/multilingual-e5-small"
DEFAULT_EMBED_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"

# The e5 family needs these prefixes at index and query time (model card); forgetting them silently hurts recall.
DEFAULT_QUERY_PREFIX = "query: "
DEFAULT_PASSAGE_PREFIX = "passage: "

# The model reads at most 512 tokens; keep room for the prefix and the two special tokens.
MODEL_MAX_TOKENS = 512
PREFIX_AND_SPECIAL_TOKENS = 8

SCOPES = ("pilot", "all")


class ConfigError(ValueError):
    """A setting is missing or invalid. The message says which variable to fix."""


def _text(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name, "")
    return value if value != "" else default


def _int(env: Mapping[str, str], name: str, default: int, minimum: int) -> int:
    raw = env.get(name, "")
    if raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not a whole number") from exc
    if value < minimum:
        raise ConfigError(f"{name}={value} is below the minimum {minimum}")
    return value


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if raw == "":
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name}={raw!r} must be 1 or 0")


@dataclass(frozen=True)
class Settings:
    """All pipeline settings. Build with `Settings.from_env()`."""

    mongo_uri: str
    mongo_db: str
    data_dir: Path
    content_dir: Path
    looma_server: str
    embed_model_repo: str
    embed_model_revision: str
    query_prefix: str
    passage_prefix: str
    embed_threads: int
    embed_batch_size: int
    chunk_target_tokens: int
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    ocr_enabled: bool
    ocr_langs: str
    looma_web_url: str
    signing_key_path: Path
    signing_pubkey_path: Path
    git_sha: str

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def bundles_dir(self) -> Path:
        return self.data_dir / "bundles"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def model_dir(self) -> Path:
        """Where the prepared embedder (int8 ONNX + tokenizer) for the pinned revision lives."""
        return self.models_dir / self.embed_model_repo.replace("/", "--") / self.embed_model_revision

    @property
    def is_cehrd_server(self) -> bool:
        """True when building for the CEHRD portal, the only server that may show CEHRD-only items."""
        return self.looma_server.upper() == "CEHRD"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Read settings from `env` (default: the process environment) and validate them.

        Raises:
            ConfigError: if a value is malformed or the chunk sizes are inconsistent.
        """
        env = os.environ if env is None else env
        data_dir = Path(_text(env, "PIPELINE_DATA_DIR", "/data"))
        settings = cls(
            mongo_uri=_text(env, "MONGO_URI", "mongodb://looma-db:27017"),
            mongo_db=_text(env, "MONGO_DB", "looma"),
            data_dir=data_dir,
            content_dir=Path(_text(env, "PIPELINE_CONTENT_DIR", "/content")),
            looma_server=_text(env, "LOOMA_SERVER", "looma"),
            embed_model_repo=_text(env, "EMBED_MODEL_REPO", DEFAULT_EMBED_MODEL_REPO),
            embed_model_revision=_text(env, "EMBED_MODEL_REVISION", DEFAULT_EMBED_MODEL_REVISION),
            query_prefix=_text(env, "EMBED_QUERY_PREFIX", DEFAULT_QUERY_PREFIX),
            passage_prefix=_text(env, "EMBED_PASSAGE_PREFIX", DEFAULT_PASSAGE_PREFIX),
            embed_threads=_int(env, "EMBED_THREADS", 4, minimum=1),
            embed_batch_size=_int(env, "EMBED_BATCH_SIZE", 32, minimum=1),
            chunk_target_tokens=_int(env, "CHUNK_TARGET_TOKENS", 200, minimum=16),
            chunk_max_tokens=_int(env, "CHUNK_MAX_TOKENS", 256, minimum=16),
            chunk_overlap_tokens=_int(env, "CHUNK_OVERLAP_TOKENS", 32, minimum=0),
            ocr_enabled=_bool(env, "OCR_ENABLED", True),
            ocr_langs=_text(env, "OCR_LANGS", "eng+nep"),
            looma_web_url=_text(env, "LOOMA_WEB_URL", "http://looma-web:8080").rstrip("/"),
            signing_key_path=Path(_text(env, "SIGNING_KEY_PATH", str(data_dir / "keys" / "release-ed25519.key"))),
            signing_pubkey_path=Path(
                _text(env, "SIGNING_PUBKEY_PATH", str(data_dir / "keys" / "release-ed25519.pub"))
            ),
            git_sha=_text(env, "PIPELINE_GIT_SHA", "unknown"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Check the settings that depend on each other.

        Raises:
            ConfigError: with the variable names to change.
        """
        if not self.chunk_overlap_tokens < self.chunk_target_tokens <= self.chunk_max_tokens:
            raise ConfigError(
                "need CHUNK_OVERLAP_TOKENS < CHUNK_TARGET_TOKENS <= CHUNK_MAX_TOKENS, got "
                f"{self.chunk_overlap_tokens} / {self.chunk_target_tokens} / {self.chunk_max_tokens}"
            )
        if self.chunk_max_tokens > MODEL_MAX_TOKENS - PREFIX_AND_SPECIAL_TOKENS:
            raise ConfigError(
                f"CHUNK_MAX_TOKENS={self.chunk_max_tokens} leaves no room for the prefix within the model's "
                f"{MODEL_MAX_TOKENS}-token limit"
            )
        if not self.mongo_uri.startswith(("mongodb://", "mongodb+srv://")):
            raise ConfigError(f"MONGO_URI must start with mongodb:// (got {self.mongo_uri!r})")

    def public_view(self) -> dict[str, str]:
        """Settings safe to print or store in a report (the URI is shown without credentials)."""
        uri = self.mongo_uri
        if "@" in uri:
            scheme, rest = uri.split("://", 1)
            uri = f"{scheme}://***@{rest.split('@', 1)[1]}"
        return {
            "mongo_uri": uri,
            "mongo_db": self.mongo_db,
            "data_dir": str(self.data_dir),
            "content_dir": str(self.content_dir),
            "looma_server": self.looma_server,
            "embed_model": f"{self.embed_model_repo}@{self.embed_model_revision}",
            "chunk_tokens": f"target {self.chunk_target_tokens}, max {self.chunk_max_tokens}, "
            f"overlap {self.chunk_overlap_tokens}",
            "ocr": f"{'on' if self.ocr_enabled else 'off'} ({self.ocr_langs})",
            "looma_web_url": self.looma_web_url,
            "git_sha": self.git_sha,
        }

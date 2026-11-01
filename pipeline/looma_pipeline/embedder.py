"""The embedding model: preparation (download + int8) and inference with ONNX Runtime.

Import only; `python -m looma_pipeline prepare-model` calls `prepare_model()`. The model is pinned to one revision
on Hugging Face and uses its published ONNX export, so no PyTorch is needed anywhere. `prepare_model()` writes:
    <model_dir>/model.fp32.onnx   the published file (kept for the int8-vs-full-size check)
    <model_dir>/model.int8.onnx   dynamic int8 quantization (onnxruntime.quantization), portable to arm64
    <model_dir>/tokenizer.json
    <model_dir>/README.md         the model card (license and usage, including the query/passage prefixes)
    <model_dir>/model_info.json   repo, revision, SHA-256 of every file, quantization settings
Side effects: network access to Hugging Face (prepare only); writes the files above.
Inference (`OnnxEmbedder`) is offline: mean pooling over tokens, then L2 normalization, as the e5 card prescribes.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from looma_pipeline.config import MODEL_MAX_TOKENS, Settings
from looma_pipeline.hashing import sha256_of_file

log = logging.getLogger(__name__)

# Files taken from the pinned revision: (path in the repo, local name)
MODEL_FILES = (("onnx/model.onnx", "model.fp32.onnx"), ("onnx/tokenizer.json", "tokenizer.json"),
               ("README.md", "README.md"))
INT8_NAME = "model.int8.onnx"
INFO_NAME = "model_info.json"
MODEL_LICENSE = "mit"  # from the model card metadata at the pinned revision


@dataclass(frozen=True)
class ModelInfo:
    repo: str
    revision: str
    license: str
    files: dict[str, str]  # local name -> sha256
    quantization: dict[str, str]

    @property
    def key(self) -> str:
        """Identifies the exact model bytes; part of every embedding-cache key."""
        return f"{self.repo}@{self.revision}#{self.files[INT8_NAME][:16]}"

    @classmethod
    def load(cls, model_dir: Path) -> "ModelInfo":
        data = json.loads((model_dir / INFO_NAME).read_text(encoding="utf-8"))
        return cls(data["repo"], data["revision"], data["license"], data["files"], data["quantization"])


def _files_match(model_dir: Path) -> bool:
    try:
        info = ModelInfo.load(model_dir)
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return False
    return all((model_dir / name).is_file() and sha256_of_file(model_dir / name) == digest
               for name, digest in info.files.items())


def prepare_model(settings: Settings) -> ModelInfo:
    """Download the pinned model files and write the int8 model. Does nothing when they are already in place."""
    model_dir = settings.model_dir
    if _files_match(model_dir):
        log.info("model already prepared", extra={"model_dir": str(model_dir)})
        return ModelInfo.load(model_dir)

    from huggingface_hub import hf_hub_download
    from onnxruntime import __version__ as ort_version
    from onnxruntime.quantization import QuantType, quantize_dynamic

    model_dir.mkdir(parents=True, exist_ok=True)
    for remote, local in MODEL_FILES:
        cached = hf_hub_download(settings.embed_model_repo, remote, revision=settings.embed_model_revision,
                                 cache_dir=str(settings.models_dir / "hf-cache"))
        shutil.copyfile(cached, model_dir / local)
        log.info("downloaded", extra={"file": remote, "bytes": (model_dir / local).stat().st_size})

    logging.disable(logging.INFO)  # the quantizer logs one root-logger line per tensor; keep warnings only
    try:
        quantize_dynamic(str(model_dir / "model.fp32.onnx"), str(model_dir / INT8_NAME), weight_type=QuantType.QInt8)
    finally:
        logging.disable(logging.NOTSET)
    files = {name: sha256_of_file(model_dir / name)
             for name in ("model.fp32.onnx", INT8_NAME, "tokenizer.json", "README.md")}
    info = {"repo": settings.embed_model_repo, "revision": settings.embed_model_revision, "license": MODEL_LICENSE,
            "files": files, "quantization": {"method": "onnxruntime.quantization.quantize_dynamic",
                                             "weight_type": "QInt8", "onnxruntime": ort_version}}
    (model_dir / INFO_NAME).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return ModelInfo.load(model_dir)


class OnnxEmbedder:
    """Turns text into L2-normalized vectors with an ONNX model and its tokenizer.json. Works offline."""

    def __init__(self, model_path: Path, tokenizer_path: Path, model_key: str, query_prefix: str,
                 passage_prefix: str, threads: int = 4, batch_size: int = 32) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(MODEL_MAX_TOKENS)
        self._tokenizer.no_padding()
        self._pad_id = self._tokenizer.token_to_id("<pad>") or 0
        self.model_key = model_key
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self.batch_size = batch_size
        self.dims = int(self._embed_batch(["dimension probe"]).shape[1])

    @classmethod
    def from_settings(cls, settings: Settings, model_file: str = INT8_NAME) -> "OnnxEmbedder":
        """The prepared model for the pinned revision.

        Raises:
            FileNotFoundError: if `prepare-model` has not been run.
        """
        model_dir = settings.model_dir
        if not (model_dir / model_file).is_file():
            raise FileNotFoundError(f"no {model_file} in {model_dir}: run `make pipeline-model` first")
        info = ModelInfo.load(model_dir)
        # Dynamic int8 quantization picks activation scales from the whole batch, so a vector would depend on
        # which other texts share its batch (measured 2026-11-01: up to 0.016 per component; the full-size model
        # is exactly batch-independent). One text per call keeps every passage vector identical to what the serve
        # plane computes for a single query, at about half the throughput.
        batch_size = 1 if model_file == INT8_NAME else settings.embed_batch_size
        if model_file == INT8_NAME and settings.embed_batch_size != 1:
            log.info("int8 model embeds one text per call", extra={"configured_batch_size": settings.embed_batch_size})
        model_key = f"{info.key};file={model_file};pool=mean;batch={batch_size}"
        return cls(model_dir / model_file, model_dir / "tokenizer.json", model_key, settings.query_prefix,
                   settings.passage_prefix, settings.embed_threads, batch_size)

    def _embed_batch(self, texts: list[str]) -> np.ndarray:
        encodings = self._tokenizer.encode_batch(texts)
        width = max(len(e.ids) for e in encodings)
        ids = np.full((len(texts), width), self._pad_id, dtype=np.int64)
        mask = np.zeros((len(texts), width), dtype=np.int64)
        for row, encoding in enumerate(encodings):
            ids[row, :len(encoding.ids)] = encoding.ids
            mask[row, :len(encoding.ids)] = 1
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feed)[0]  # (batch, tokens, dims): last hidden state
        summed = (hidden * mask[:, :, None]).sum(axis=1)
        pooled = summed / np.clip(mask.sum(axis=1, keepdims=True), 1, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return (pooled / np.clip(norms, 1e-12, None)).astype(np.float32)

    def embed(self, texts: list[str]) -> np.ndarray:
        """Vectors for texts that already carry their prefix. Batches by length for speed; keeps input order."""
        if not texts:
            return np.zeros((0, getattr(self, "dims", 0)), dtype=np.float32)
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        out = np.zeros((len(texts), self.dims), dtype=np.float32)
        for start in range(0, len(order), self.batch_size):
            batch = order[start:start + self.batch_size]
            out[batch] = self._embed_batch([texts[i] for i in batch])
        return out

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self.embed([self.passage_prefix + t for t in texts])

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self.embed([self.query_prefix + t for t in texts])

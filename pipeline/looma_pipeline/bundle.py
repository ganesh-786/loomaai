"""Signed index bundles: signing keys, content hash, manifest, checksums, signature and verification.

Import only. A bundle is a folder:
    manifest.json        what the bundle is and how it was built (model, chunking, snapshot, counts, content hash)
    model/               model.int8.onnx, tokenizer.json, README.md (model card), model_info.json
    vectors/             passages.i8.npy, vectors_info.json
    meta/chunks.db       items, passages, FTS5 word index, dictionary
    tests/self_test.jsonl
    SHA256SUMS           SHA-256 of every other file
    SHA256SUMS.sig       ed25519 signature of SHA256SUMS (base64)
Checksums catch corruption; the signature proves who built it. `verify_bundle()` trusts only the public key it is
given, never a key inside the bundle. The content hash covers what search reads (vectors, rows, model hashes,
self-test queries) and nothing that changes from run to run (times, run ids, SQLite page layout), so two builds
from the same data give the same content hash.
Side effects: `ensure_keys()` writes the key pair; the other writers write inside a bundle folder.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from looma_pipeline import BUNDLE_SCHEMA_VERSION
from looma_pipeline.hashing import CHUNK_BYTES, canonical_json, sha256_of_file

SUMS_FILE = "SHA256SUMS"
SIGNATURE_FILE = "SHA256SUMS.sig"
MANIFEST_FILE = "manifest.json"
UNSIGNED = {SUMS_FILE, SIGNATURE_FILE}
CONTENT_TABLES = {  # table -> columns, in a fixed order
    "items": "item_id, ft, title_en, title_np, subject, grade_lo, grade_hi, grade_source, src, lang, cehrd, chapter_id",
    "item_chapters": "ch_id, item_id",
    "passages": "vrow, passage_id, item_id, lang, source, page, t_start, n_tokens, text",
    "dictionary": "en, np",
}


# ---- keys --------------------------------------------------------------------------------------------------

def ensure_keys(private_path: Path, public_path: Path) -> str:
    """Create an ed25519 key pair if there is none. Never overwrites. Returns the key id."""
    if not private_path.exists():
        private_path.parent.mkdir(parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(pem)
        public_path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                              serialization.PublicFormat.SubjectPublicKeyInfo))
    return key_id(load_public_key(public_path))


def load_private_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{path} is not an ed25519 private key")
    return key


def load_public_key(path: Path) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError(f"{path} is not an ed25519 public key")
    return key


def key_id(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


# ---- content hash, checksums, signature ------------------------------------------------------------------------

def content_hash(bundle_dir: Path, model_sha256: str, tokenizer_sha256: str) -> str:
    """SHA-256 of everything search reads, independent of run times and SQLite layout."""
    digest = hashlib.sha256()
    digest.update(canonical_json({"model": model_sha256, "tokenizer": tokenizer_sha256}))
    with (bundle_dir / "vectors" / "passages.i8.npy").open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    db = sqlite3.connect(f"file:{bundle_dir / 'meta' / 'chunks.db'}?mode=ro", uri=True)
    try:
        for table, columns in CONTENT_TABLES.items():
            for row in db.execute(f"SELECT {columns} FROM {table} ORDER BY {columns}"):
                digest.update(canonical_json([table, *row]))
    finally:
        db.close()
    digest.update((bundle_dir / "tests" / "self_test.jsonl").read_bytes())
    return digest.hexdigest()


def bundle_files(bundle_dir: Path) -> list[str]:
    """Relative paths of every file that must be listed in SHA256SUMS, sorted."""
    return sorted(str(p.relative_to(bundle_dir)) for p in bundle_dir.rglob("*") if p.is_file()
                  and str(p.relative_to(bundle_dir)) not in UNSIGNED)


def write_checksums_and_sign(bundle_dir: Path, private_key: Ed25519PrivateKey) -> None:
    lines = [f"{sha256_of_file(bundle_dir / rel)}  {rel}\n" for rel in bundle_files(bundle_dir)]
    sums = "".join(lines).encode("utf-8")
    (bundle_dir / SUMS_FILE).write_bytes(sums)
    (bundle_dir / SIGNATURE_FILE).write_text(base64.b64encode(private_key.sign(sums)).decode() + "\n")


# ---- verification -------------------------------------------------------------------------------------------

@dataclass
class VerifyResult:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(passed for _, passed, _ in self.checks)

    def add(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append((name, passed, detail))
        return passed

    def as_dict(self) -> dict:
        return {"ok": self.ok, "checks": [{"check": n, "ok": p, "detail": d} for n, p, d in self.checks]}


def _parse_sums(text: str) -> dict[str, str]:
    entries = {}
    for line in text.splitlines():
        digest, _, rel = line.partition("  ")
        if not rel or len(digest) != 64:
            raise ValueError(f"malformed line in {SUMS_FILE}: {line[:80]!r}")
        entries[rel] = digest
    return entries


def verify_bundle(bundle_dir: Path, public_key_path: Path, expect_model: tuple[str, str] | None = None,
                  self_test: Callable[[Path, dict], tuple[int, int]] | None = None) -> VerifyResult:
    """Check a bundle before anything reads it. Stops at the first failed check.

    Args:
        bundle_dir: the bundle folder.
        public_key_path: the trusted release public key (never taken from the bundle).
        expect_model: (repo, revision) the reader is configured for; a bundle built for another model is refused.
        self_test: optional callback (bundle_dir, manifest) -> (passed, total) that runs the self-test queries.
    """
    result = VerifyResult()
    missing = [name for name in (MANIFEST_FILE, SUMS_FILE, SIGNATURE_FILE) if not (bundle_dir / name).is_file()]
    if not result.add("files present", not missing, f"missing: {missing}" if missing else ""):
        return result

    sums = (bundle_dir / SUMS_FILE).read_bytes()
    public_key = load_public_key(public_key_path)
    try:
        public_key.verify(base64.b64decode((bundle_dir / SIGNATURE_FILE).read_text()), sums)
    except (InvalidSignature, ValueError) as exc:  # ValueError also covers malformed base64
        result.add("signature", False, f"{type(exc).__name__}: not signed by the trusted key")
        return result
    result.add("signature", True, f"key {key_id(public_key)}")

    try:
        listed = _parse_sums(sums.decode("utf-8"))
    except ValueError as exc:
        result.add("checksums", False, str(exc))
        return result
    actual = bundle_files(bundle_dir)
    extra, absent = sorted(set(actual) - set(listed)), sorted(set(listed) - set(actual))
    changed = [rel for rel in sorted(set(listed) & set(actual)) if sha256_of_file(bundle_dir / rel) != listed[rel]]
    detail = "; ".join(f"{label}: {names[:3]}" for label, names in
                       (("changed", changed), ("unlisted", extra), ("missing", absent)) if names)
    if not result.add("checksums", not (extra or absent or changed), detail or f"{len(listed)} files"):
        return result

    manifest = json.loads((bundle_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    major = str(manifest.get("schema_version", "")).split(".")[0]
    if not result.add("schema version", major == BUNDLE_SCHEMA_VERSION.split(".")[0],
                      f"bundle {manifest.get('schema_version')}, reader {BUNDLE_SCHEMA_VERSION}"):
        return result

    embedding = manifest["embedding"]
    model_ok = (sha256_of_file(bundle_dir / "model" / embedding["model_file"]) == embedding["model_sha256"]
                and sha256_of_file(bundle_dir / "model" / "tokenizer.json") == embedding["tokenizer_sha256"])
    if not result.add("model files match manifest", model_ok):
        return result
    if expect_model is not None:
        built_for = (embedding["repo"], embedding["revision"])
        if not result.add("model expected by the reader", built_for == tuple(expect_model),
                          f"bundle built for {built_for[0]}@{built_for[1][:12]}, reader expects "
                          f"{expect_model[0]}@{expect_model[1][:12]}"):
            return result

    recomputed = content_hash(bundle_dir, embedding["model_sha256"], embedding["tokenizer_sha256"])
    if not result.add("content hash", recomputed == manifest["content_hash"], recomputed[:16]):
        return result

    if self_test is not None:
        passed, total = self_test(bundle_dir, manifest)
        result.add("self-test queries", total > 0 and passed == total, f"{passed}/{total}")
    return result

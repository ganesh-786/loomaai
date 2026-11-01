import json
import os
import shutil
import sqlite3
import stat

import looma_fixture as fx
import pytest
from fake_embedder import FakeEmbedder

from looma_pipeline.bundle import (MANIFEST_FILE, SUMS_FILE, ensure_keys, key_id, load_private_key,
                                   load_public_key, write_checksums_and_sign)
from looma_pipeline.chunking import WhitespaceCounter
from looma_pipeline.pipeline import run_build
from looma_pipeline.source import DictSource
from looma_pipeline.verify import verify


def _bundle(settings, fake_model_dir):
    result = run_build(settings, "pilot", source=DictSource(fx.looma_data()), counter=WhitespaceCounter(),
                       embedder=FakeEmbedder(), model_dir=fake_model_dir)
    return result.outputs["bundle"]


def _verify(bundle, settings):
    return verify(bundle, settings, embedder=FakeEmbedder())


def _failed(result):
    return next(name for name, ok, _ in result.checks if not ok)


def test_keys_are_created_once_and_kept_private(tmp_path):
    private, public = tmp_path / "k" / "release.key", tmp_path / "k" / "release.pub"
    first = ensure_keys(private, public)
    assert stat.S_IMODE(os.stat(private).st_mode) == 0o600
    assert ensure_keys(private, public) == first == key_id(load_public_key(public))
    load_private_key(private)  # parses


def test_build_writes_a_complete_signed_bundle(settings, fake_model_dir):
    bundle = _bundle(settings, fake_model_dir)
    assert bundle.parent == settings.bundles_dir and bundle.name.endswith("-pilot-r1")
    assert not list(settings.bundles_dir.glob(".incoming-*"))  # the folder appeared in one rename
    manifest = json.loads((bundle / MANIFEST_FILE).read_text())
    assert manifest["embedding"]["repo"] == settings.embed_model_repo
    assert manifest["snapshot"]["scope"] == "pilot" and len(manifest["content_hash"]) == 64
    listed = {line.split("  ", 1)[1] for line in (bundle / SUMS_FILE).read_text().splitlines()}
    assert {"manifest.json", "meta/chunks.db", "vectors/passages.i8.npy", "model/model.int8.onnx",
            "tests/self_test.jsonl"} <= listed
    result = _verify(bundle, settings)
    assert result.ok, result.checks
    assert [name for name, _, _ in result.checks][-1] == "self-test queries"


def test_two_builds_from_the_same_data_have_the_same_content(settings, fake_model_dir):
    first, second = _bundle(settings, fake_model_dir), _bundle(settings, fake_model_dir)
    assert first.name != second.name
    hashes = [json.loads((b / MANIFEST_FILE).read_text())["content_hash"] for b in (first, second)]
    assert hashes[0] == hashes[1]


@pytest.fixture
def signed(settings, fake_model_dir, tmp_path):
    bundle = _bundle(settings, fake_model_dir)
    return lambda name: shutil.copytree(bundle, tmp_path / name)


def test_a_changed_byte_is_refused(settings, signed):
    copy = signed("byte")
    target = copy / "vectors" / "passages.i8.npy"
    data = bytearray(target.read_bytes())
    data[-1] ^= 0x01
    target.write_bytes(bytes(data))
    assert _failed(_verify(copy, settings)) == "checksums"


def test_missing_and_extra_files_are_refused(settings, signed):
    missing = signed("missing")
    (missing / "tests" / "self_test.jsonl").unlink()
    assert _failed(_verify(missing, settings)) == "checksums"
    extra = signed("extra")
    (extra / "notes.txt").write_text("added later")
    assert _failed(_verify(extra, settings)) == "checksums"


def test_a_bundle_signed_with_another_key_is_refused(settings, signed, tmp_path):
    copy = signed("other-key")
    ensure_keys(tmp_path / "other.key", tmp_path / "other.pub")
    write_checksums_and_sign(copy, load_private_key(tmp_path / "other.key"))
    assert _failed(_verify(copy, settings)) == "signature"


def test_an_edited_manifest_without_re_signing_is_refused(settings, signed):
    copy = signed("manifest")
    manifest = json.loads((copy / MANIFEST_FILE).read_text())
    manifest["counts"]["passages"] += 1
    (copy / MANIFEST_FILE).write_text(json.dumps(manifest))
    assert _failed(_verify(copy, settings)) == "checksums"


def test_a_re_signed_bundle_for_another_model_is_refused(settings, signed):
    copy = signed("model")
    manifest = json.loads((copy / MANIFEST_FILE).read_text())
    manifest["embedding"]["repo"] = "someone/other-model"
    (copy / MANIFEST_FILE).write_text(json.dumps(manifest))
    write_checksums_and_sign(copy, load_private_key(settings.signing_key_path))
    assert _failed(_verify(copy, settings)) == "model expected by the reader"


def test_a_re_signed_bundle_with_edited_index_rows_is_refused(settings, signed):
    """Even someone holding the key cannot change what search reads without the content hash noticing."""
    copy = signed("rows")
    db = sqlite3.connect(copy / "meta" / "chunks.db")
    db.execute("UPDATE passages SET text = 'replaced text' WHERE vrow = 0")
    db.commit()
    db.close()
    write_checksums_and_sign(copy, load_private_key(settings.signing_key_path))
    assert _failed(_verify(copy, settings)) == "content hash"

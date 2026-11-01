import os

import pytest

from looma_pipeline import fsutil


def test_link_or_copy_hard_links_on_one_filesystem(tmp_path):
    source, target = tmp_path / "model", tmp_path / "bundle-model"
    source.write_bytes(b"model bytes")
    assert fsutil.link_or_copy(source, target) is True
    assert os.stat(source).st_ino == os.stat(target).st_ino


def test_link_or_copy_falls_back_to_a_copy_where_links_are_impossible(tmp_path, monkeypatch):
    def no_links(*_args):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(fsutil.os, "link", no_links)
    source, target = tmp_path / "model", tmp_path / "bundle-model"
    source.write_bytes(b"model bytes")
    assert fsutil.link_or_copy(source, target) is False
    assert target.read_bytes() == b"model bytes" and os.stat(source).st_ino != os.stat(target).st_ino


def test_rewriting_a_file_never_changes_the_copies_linked_to_it(tmp_path):
    """A bundle shares bytes with the prepared model: preparing the model again must leave the bundle as signed."""
    model, in_bundle, newer = tmp_path / "model", tmp_path / "bundle-model", tmp_path / "newer"
    model.write_bytes(b"old")
    fsutil.link_or_copy(model, in_bundle)
    newer.write_bytes(b"new")
    fsutil.link_or_copy(newer, model)
    fsutil.write_atomically(model, lambda path: path.write_bytes(b"newest"))
    assert model.read_bytes() == b"newest" and in_bundle.read_bytes() == b"old"


def test_a_failed_write_leaves_the_target_and_no_temporary_file(tmp_path):
    target = tmp_path / "model"
    target.write_bytes(b"keep")

    def half_written(path):
        path.write_bytes(b"half")
        raise RuntimeError("quantizer crashed")

    with pytest.raises(RuntimeError):
        fsutil.write_atomically(target, half_written)
    assert target.read_bytes() == b"keep" and [p.name for p in tmp_path.iterdir()] == ["model"]


def test_copy_tree_linked_links_every_file(tmp_path):
    (tmp_path / "staging" / "meta").mkdir(parents=True)
    (tmp_path / "staging" / "meta" / "chunks.db").write_bytes(b"db")
    (tmp_path / "staging" / "vectors.npy").write_bytes(b"vectors")
    assert fsutil.copy_tree_linked(tmp_path / "staging", tmp_path / "bundle") == (2, 0)
    assert os.stat(tmp_path / "bundle" / "meta" / "chunks.db").st_ino == \
        os.stat(tmp_path / "staging" / "meta" / "chunks.db").st_ino

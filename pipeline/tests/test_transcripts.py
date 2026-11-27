"""Tests for extractors/transcripts.py: loading page transcripts that replace PDF text (issue #2).

Pure: transcript files are written under tmp_path. No MongoDB, model or network.
"""

import json

import pytest

from looma_pipeline.extractors.transcripts import TranscriptError, load_transcripts, parse_row

SHA_A = "a" * 64
SHA_B = "b" * 64
_DROP = object()  # pass as a field value to leave that field out of the row


def row(**overrides):
    """One valid transcript row; keyword arguments change or (with _DROP) remove fields."""
    base = {"file": "textbooks/Class10/Science/Science_10_0016.pdf", "file_sha256": SHA_A, "page": 77,
            "printed_page": "73", "text": "4 Heredity", "run": "D-test", "method": "visual-transcription",
            "model": "test-model", "review_status": "reviewed", "lang": "en"}
    base.update(overrides)
    return {key: value for key, value in base.items() if value is not _DROP}


def write(folder, name, lines):
    """Write a .jsonl file; dict lines are JSON-encoded, str lines are written as they are."""
    folder.mkdir(parents=True, exist_ok=True)
    text = "\n".join(line if isinstance(line, str) else json.dumps(line, ensure_ascii=False) for line in lines)
    (folder / name).write_text(text + "\n", encoding="utf-8")


def test_a_reviewed_row_is_found_by_file_hash_and_page(tmp_path):
    write(tmp_path, "run.jsonl", [row()])
    index = load_transcripts(tmp_path, allow_unreviewed=False)
    page = index.lookup(SHA_A, 77)
    assert page is not None and page.text == "4 Heredity"
    assert index.lookup(SHA_A, 78) is None and index.lookup(SHA_B, 77) is None
    assert index.counts["pages_usable"] == 1


def test_a_row_keeps_its_optional_fields():
    page = parse_row(row())
    assert (page.file, page.printed_page, page.method, page.model, page.lang, page.run) == (
        "textbooks/Class10/Science/Science_10_0016.pdf", "73", "visual-transcription", "test-model", "en", "D-test")


def test_an_upper_case_hash_matches_the_lower_case_one_the_pipeline_computes():
    assert parse_row(row(file_sha256="A" * 64)).file_sha256 == SHA_A


@pytest.mark.parametrize("overrides, field", [
    ({"file_sha256": _DROP}, "file_sha256"),
    ({"file_sha256": "abc"}, "file_sha256"),
    ({"file_sha256": "g" * 64}, "file_sha256"),
    ({"page": _DROP}, "page"),
    ({"page": 0}, "page"),
    ({"page": "77"}, "page"),
    ({"page": True}, "page"),
    ({"text": _DROP}, "text"),
    ({"text": "   \n"}, "text"),
    ({"text": 5}, "text"),
    ({"run": ""}, "run"),
    ({"review_status": "approved"}, "review_status"),
    ({"review_status": _DROP}, "review_status"),
])
def test_a_malformed_row_is_refused_with_the_field_to_fix(overrides, field):
    with pytest.raises(TranscriptError, match=field):
        parse_row(row(**overrides))


def test_malformed_lines_are_counted_and_skipped_without_stopping_the_load(tmp_path):
    write(tmp_path, "run.jsonl", [row(), "{not json", "[1, 2]", row(page=0, text="x"), ""])
    index = load_transcripts(tmp_path, allow_unreviewed=False)
    assert index.lookup(SHA_A, 77) is not None
    assert index.counts["rows_malformed"] == 3
    assert [problem["line"] for problem in index.problems] == [2, 3, 4]
    assert all(problem["file"] == "run.jsonl" for problem in index.problems)


def test_unreviewed_rows_are_used_only_when_allowed(tmp_path):
    write(tmp_path, "run.jsonl", [row(review_status="unreviewed")])
    refused = load_transcripts(tmp_path, allow_unreviewed=False)
    assert refused.lookup(SHA_A, 77) is None and refused.counts["rows_unreviewed_skipped"] == 1
    assert load_transcripts(tmp_path, allow_unreviewed=True).lookup(SHA_A, 77) is not None


def test_rejected_rows_are_never_used(tmp_path):
    write(tmp_path, "run.jsonl", [row(review_status="rejected")])
    index = load_transcripts(tmp_path, allow_unreviewed=True)
    assert index.lookup(SHA_A, 77) is None and index.counts["rows_rejected"] == 1


def test_two_different_texts_for_one_page_are_both_dropped(tmp_path):
    write(tmp_path, "a.jsonl", [row(text="first reading")])
    write(tmp_path, "b.jsonl", [row(text="second reading", run="other")])
    index = load_transcripts(tmp_path, allow_unreviewed=False)
    assert index.lookup(SHA_A, 77) is None
    assert index.counts["pages_conflicting"] == 1 and index.counts["pages_usable"] == 0
    assert any("conflict" in problem["reason"] for problem in index.problems)


def test_a_reviewed_row_wins_over_an_unreviewed_row_for_the_same_page(tmp_path):
    write(tmp_path, "a.jsonl", [row(text="first reading", review_status="unreviewed")])
    write(tmp_path, "b.jsonl", [row(text="checked reading", run="review-1")])
    index = load_transcripts(tmp_path, allow_unreviewed=True)
    assert index.lookup(SHA_A, 77).text == "checked reading"
    assert index.counts["rows_superseded"] == 1 and index.counts["pages_conflicting"] == 0


def test_pages_of_a_file_are_listed_so_ocr_can_skip_them(tmp_path):
    write(tmp_path, "run.jsonl", [row(page=77), row(page=78, text="next page"), row(file_sha256=SHA_B, page=1)])
    index = load_transcripts(tmp_path, allow_unreviewed=False)
    assert index.pages_of(SHA_A) == frozenset({77, 78})
    assert index.pages_of(SHA_B) == frozenset({1}) and index.pages_of(None) == frozenset()


def test_an_identical_duplicate_row_counts_once(tmp_path):
    write(tmp_path, "run.jsonl", [row(), row()])
    index = load_transcripts(tmp_path, allow_unreviewed=False)
    assert index.lookup(SHA_A, 77) is not None
    assert index.counts["rows_duplicate"] == 1 and index.counts["pages_usable"] == 1


def test_a_missing_folder_gives_an_empty_index(tmp_path):
    index = load_transcripts(tmp_path / "absent", allow_unreviewed=True)
    assert len(index) == 0 and index.counts["files"] == 0 and not index.problems


def test_a_file_that_is_not_utf8_is_counted_and_the_others_still_load(tmp_path):
    write(tmp_path, "good.jsonl", [row()])
    (tmp_path / "bad.jsonl").write_bytes(b"\xff\xfe not utf-8")
    index = load_transcripts(tmp_path, allow_unreviewed=False)
    assert index.counts["files_unreadable"] == 1 and index.counts["files"] == 2
    assert index.lookup(SHA_A, 77) is not None


def test_only_jsonl_files_are_read(tmp_path):
    write(tmp_path, "notes.txt", [row()])
    assert len(load_transcripts(tmp_path, allow_unreviewed=False)) == 0

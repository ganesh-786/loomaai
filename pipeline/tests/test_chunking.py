import pytest
from tokenizers import Tokenizer, models, pre_tokenizers

from looma_pipeline.chunking import HfTokenCounter, WhitespaceCounter, chunk_text, split_units
from looma_pipeline.models import TextPiece
from looma_pipeline.stages.f06_chunk import make_passages

WS = WhitespaceCounter()


def _sentences(n, words=5, prefix="s"):
    return " ".join(" ".join([f"{prefix}{i}w{j}" for j in range(words - 1)] + [f"{prefix}{i}end."]) for i in range(n))


def test_units_split_on_lines_and_sentence_ends_including_the_danda():
    assert split_units("One. Two!\nलम्बाइ नापिन्छ। मिटर हो।") == ["One.", "Two!", "लम्बाइ नापिन्छ।", "मिटर हो।"]


def test_chunks_stay_under_the_limit_and_cover_every_sentence():
    text = _sentences(20)
    chunks = chunk_text(text, WS, target=20, max_tokens=30, overlap=5)
    assert len(chunks) > 1
    assert all(c.n_tokens <= 30 for c in chunks)
    joined = " ".join(c.text for c in chunks)
    assert all(f"s{i}end." in joined for i in range(20))  # nothing lost, including the last sentence


def test_consecutive_chunks_overlap():
    chunks = chunk_text(_sentences(12), WS, target=20, max_tokens=30, overlap=5)
    assert chunks[1].text.split()[0] in chunks[0].text.split()


def test_a_sentence_longer_than_the_limit_is_cut():
    long_sentence = " ".join(f"w{i}" for i in range(95)) + "."
    chunks = chunk_text(long_sentence, WS, target=20, max_tokens=30, overlap=5)
    assert all(c.n_tokens <= 30 for c in chunks)
    assert " ".join(c.text for c in chunks).split() == long_sentence.split()


def test_invalid_sizes_are_rejected():
    with pytest.raises(ValueError):
        chunk_text("x", WS, target=10, max_tokens=5, overlap=0)


def test_hf_counter_counts_and_splits_on_token_boundaries():
    vocab = {"[UNK]": 0, "length": 1, "is": 2, "measured": 3, "in": 4, "metres": 5}
    tokenizer = Tokenizer(models.WordLevel(vocab, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    counter = HfTokenCounter.__new__(HfTokenCounter)
    counter._tokenizer = tokenizer
    assert counter.count("length is measured in metres") == 5
    assert counter.split("length is measured in metres", 2) == ["length is", "measured in", "metres"]


def test_passage_ids_are_stable_per_item_and_language():
    pieces = [TextPiece("b", "lesson", 0, _sentences(10), page=None),
              TextPiece("a", "title", 1, "नाप र एकाइ", expect_nepali=True),
              TextPiece("a", "title", 0, "Measurement and unit"),
              TextPiece("a", "textbook", 9, "Second page text.", page=9),
              TextPiece("a", "textbook", 8, "First page text.", page=8)]
    first, _ = make_passages(pieces, WS, target=20, max_tokens=30, overlap=5)
    second, _ = make_passages(list(reversed(pieces)), WS, target=20, max_tokens=30, overlap=5)
    assert [p.passage_id for p in first] == [p.passage_id for p in second]
    ids = {p.passage_id: p for p in first}
    assert ids["a:en:0"].text == "Measurement and unit" and ids["a:np:0"].text == "नाप र एकाइ"
    assert (ids["a:en:1"].page, ids["a:en:2"].page) == (8, 9)
    assert all(p.passage_id.startswith("b:en:") for p in first if p.item_id == "b")


def test_pieces_without_letters_are_dropped():
    passages, counts = make_passages([TextPiece("a", "lesson", 0, "123 456")], WS, 20, 30, 5)
    assert passages == [] and counts["dropped_no_letters"] == 1


def test_every_passage_keeps_the_page_metadata_of_its_piece():
    piece = TextPiece("a", "textbook", 77, _sentences(10), page=77, printed_page="73", text_method="transcript",
                      source_run="D-test", source_model="test-model", review_status="unreviewed")
    passages, _counts = make_passages([piece], WS, 20, 30, 5)
    assert len(passages) > 1
    assert {(p.page, p.printed_page, p.text_method, p.source_run, p.source_model, p.review_status)
            for p in passages} == {(77, "73", "transcript", "D-test", "test-model", "unreviewed")}

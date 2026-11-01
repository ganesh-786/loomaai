"""F6 chunk: cut every text piece into small passages with stable ids.

Import only (called by looma_pipeline.pipeline). Titles become one passage each; longer texts are packed by
looma_pipeline.chunking. Passage ids are `<item_id>:<lang>:<n>`, numbered in a fixed order (titles, lessons, games,
documents, captions, textbook pages; then position), so the same input always gives the same ids. Each passage keeps
its page or video time and is tagged with the language of its own text.
Side effects: writes `f06_chunk.json` and `passages.jsonl` in the run folder.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict

from looma_pipeline.chunking import TokenCounter, chunk_text
from looma_pipeline.models import Passage, TextPiece
from looma_pipeline.runctx import RunContext
from looma_pipeline.text.script import language_of

SOURCE_ORDER = {"title": 0, "lesson": 1, "game": 2, "document": 3, "captions": 4, "textbook": 5}


def piece_sort_key(piece: TextPiece) -> tuple:
    return (piece.item_id, SOURCE_ORDER.get(piece.source, 99), piece.order, piece.expect_nepali, piece.page or 0)


def make_passages(pieces: list[TextPiece], counter: TokenCounter, target: int, max_tokens: int,
                  overlap: int) -> tuple[list[Passage], Counter]:
    """Chunk all pieces. Returns (passages in id order, counts)."""
    counts: Counter = Counter()
    numbers: dict[tuple[str, str], int] = defaultdict(int)
    passages: list[Passage] = []
    for piece in sorted(pieces, key=piece_sort_key):
        if piece.source == "title":
            chunks = chunk_text(piece.text, counter, max_tokens, max_tokens, 0)[:1]
        else:
            chunks = chunk_text(piece.text, counter, target, max_tokens, overlap)
        for chunk in chunks:
            lang = language_of(chunk.text)
            if lang == "none":
                counts["dropped_no_letters"] += 1
                continue
            n = numbers[(piece.item_id, lang)]
            numbers[(piece.item_id, lang)] += 1
            passages.append(Passage(f"{piece.item_id}:{lang}:{n}", piece.item_id, lang, piece.source, chunk.text,
                                    piece.page, piece.t_start, chunk.n_tokens))
    return passages, counts


def _percentile(values: list[int], share: float) -> int:
    ordered = sorted(values)
    return ordered[min(int(share * len(ordered)), len(ordered) - 1)] if ordered else 0


def run(ctx: RunContext, pieces: list[TextPiece], counter: TokenCounter) -> list[Passage]:
    settings = ctx.settings
    with ctx.stage("f06_chunk") as report:
        passages, counts = make_passages(pieces, counter, settings.chunk_target_tokens, settings.chunk_max_tokens,
                                         settings.chunk_overlap_tokens)
        tokens = [p.n_tokens for p in passages]
        report.counts.update({"pieces": len(pieces), "passages": len(passages), **dict(counts)})
        report.counts.update({f"lang_{k}": v for k, v in sorted(Counter(p.lang for p in passages).items())})
        report.counts.update({f"source_{k}": v for k, v in sorted(Counter(p.source for p in passages).items())})
        report.details["tokens"] = {"mean": round(sum(tokens) / max(len(tokens), 1), 1),
                                    "p95": _percentile(tokens, 0.95), "max": max(tokens, default=0),
                                    "target": settings.chunk_target_tokens, "limit": settings.chunk_max_tokens}
        ctx.write_jsonl("passages.jsonl", (asdict(p) for p in passages))
        return passages

"""Cut text into small passages measured in the embedding model's own tokens.

Import only; pure functions plus a tokenizer wrapper. Text is split on structure first (lines, then sentence ends
including the Nepali danda `।`), then sentences are packed into passages of about `target` tokens, never more than
`max_tokens`, with the last `overlap` tokens of one passage repeated at the start of the next so a fact that spans
a boundary is still findable. A single sentence longer than `max_tokens` is cut at token boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_SENTENCE_END = re.compile(r"(?<=[.!?।॥])\s+")


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...
    def split(self, text: str, max_tokens: int) -> list[str]: ...


class HfTokenCounter:
    """Counts tokens with a Hugging Face `tokenizer.json`, the same tokenizer the embedder uses."""

    def __init__(self, tokenizer_path: Path) -> None:
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.no_truncation()
        self._tokenizer.no_padding()

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def split(self, text: str, max_tokens: int) -> list[str]:
        offsets = self._tokenizer.encode(text, add_special_tokens=False).offsets
        parts = []
        for start in range(0, len(offsets), max_tokens):
            window = offsets[start:start + max_tokens]
            parts.append(text[window[0][0]:window[-1][1]].strip())
        return [part for part in parts if part]


class WhitespaceCounter:
    """Counts words. For tests and for estimating sizes without a model."""

    def count(self, text: str) -> int:
        return len(text.split())

    def split(self, text: str, max_tokens: int) -> list[str]:
        words = text.split()
        return [" ".join(words[i:i + max_tokens]) for i in range(0, len(words), max_tokens)]


@dataclass(frozen=True)
class Chunk:
    text: str
    n_tokens: int


def split_units(text: str) -> list[str]:
    """Lines, then sentences: the smallest pieces a passage boundary may fall between."""
    units = []
    for line in text.split("\n"):
        units.extend(part.strip() for part in _SENTENCE_END.split(line) if part.strip())
    return units


def chunk_text(text: str, counter: TokenCounter, target: int, max_tokens: int, overlap: int) -> list[Chunk]:
    """Pack `text` into chunks of about `target` tokens (at most `max_tokens`), overlapping by up to `overlap`.

    Raises:
        ValueError: if the sizes are inconsistent (they are validated in config.py too).
    """
    if not 0 <= overlap < target <= max_tokens:
        raise ValueError(f"need 0 <= overlap < target <= max_tokens, got {overlap}/{target}/{max_tokens}")
    units: list[tuple[str, int]] = []
    for unit in split_units(text):
        size = counter.count(unit)
        if size > max_tokens:
            units.extend((part, counter.count(part)) for part in counter.split(unit, max_tokens))
        elif size:
            units.append((unit, size))

    chunks: list[list[tuple[str, int]]] = []
    current: list[tuple[str, int]] = []
    size = 0
    for unit, unit_size in units:
        if current and size + unit_size > target:
            chunks.append(current)
            carry: list[tuple[str, int]] = []
            carried = 0
            for previous, previous_size in reversed(current):
                if carried + previous_size > overlap:
                    break
                carry.insert(0, (previous, previous_size))
                carried += previous_size
            current, size = (carry, carried) if carried + unit_size <= max_tokens else ([], 0)
        current.append((unit, unit_size))
        size += unit_size
    if current:
        chunks.append(current)

    result = []
    for parts in chunks:
        joined = " ".join(part for part, _ in parts)
        result.extend(Chunk(piece, counter.count(piece)) for piece in (
            counter.split(joined, max_tokens) if counter.count(joined) > max_tokens else [joined]))
    return result

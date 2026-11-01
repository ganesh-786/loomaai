"""Which script a text is written in, and so which language to tag it with.

Import only; pure functions. Language is decided from the characters themselves, not from the field a text came
from, because Looma's `nepali` fields are often code-mixed or still English (measured 2026-10-28).
"""

from __future__ import annotations

import unicodedata

DEVANAGARI_FIRST, DEVANAGARI_LAST = 0x0900, 0x097F
NEPALI_MIN_SHARE = 0.6    # at least 60% Devanagari letters: Nepali
ENGLISH_MAX_SHARE = 0.1   # at most 10%: English (or another Latin-script language)


def _is_letter(char: str) -> bool:
    category = unicodedata.category(char)
    return category.startswith("L") or category.startswith("M")


def devanagari_share(text: str) -> float:
    """Share (0-1) of letters, vowel signs included, that are Devanagari. 0.0 for text without letters."""
    letters = [c for c in text if _is_letter(c)]
    if not letters:
        return 0.0
    devanagari = sum(DEVANAGARI_FIRST <= ord(c) <= DEVANAGARI_LAST for c in letters)
    return devanagari / len(letters)


def language_of(text: str) -> str:
    """'np', 'en', 'mixed', or 'none' when the text has no letters."""
    if not any(_is_letter(c) for c in text):
        return "none"
    share = devanagari_share(text)
    if share >= NEPALI_MIN_SHARE:
        return "np"
    if share <= ENGLISH_MAX_SHARE:
        return "en"
    return "mixed"

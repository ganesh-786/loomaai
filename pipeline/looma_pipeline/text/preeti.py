"""Legacy Preeti-font Nepali to Unicode, using the converter already in this repo (`npttf2utf/`).

Import only. Many older Nepali PDFs use the Preeti font: the text layer holds ASCII letters that only look like
Devanagari on screen, so extraction gives text like `gfk / PsfO` instead of `नाप र एकाइ`. The converter's default
map path points at a file that doesn't exist, so the map in `npttf2utf/files/map.json` is passed explicitly.
`npttf2utf` is GPL-3.0 (see docs/architecture.md, risks); it runs on the build plane only.

The converter turns *any* ASCII into Devanagari-looking text, English included, so `should_convert()` only allows
text that does not read as English and that becomes mostly Devanagari after conversion.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

from looma_pipeline.text.script import devanagari_share

LEGACY_MAX_SHARE = 0.3         # text that is already 30%+ Devanagari is not legacy-font text
CONVERTED_MIN_SHARE = 0.8      # after conversion at least 80% must be Devanagari
ENGLISH_WORD_SHARE = 0.15      # 15%+ common English words means the text is English, not Preeti
_COMMON_ENGLISH = frozenset(
    "the a an and or of to in on is are was were be by for with as at from this that it its we you they "
    "he she not can will which what how why".split()
)
_WORD = re.compile(r"[A-Za-z]+")


def english_word_share(text: str) -> float:
    words = [w.lower() for w in _WORD.findall(text)]
    return sum(w in _COMMON_ENGLISH for w in words) / len(words) if words else 0.0


class PreetiConverter:
    """Converts Preeti-encoded text to Unicode Devanagari."""

    def __init__(self, map_path: Path | None = None) -> None:
        with warnings.catch_warnings():
            # npttf2utf/base/preetimapper.py has invalid escape sequences ('\\w', '\\l', '\\j') that raise
            # SyntaxWarning on import; that third-party code is left unchanged here.
            warnings.simplefilter("ignore", SyntaxWarning)
            import npttf2utf
            from npttf2utf.base.fontmapper import FontMapper
        default_map = Path(npttf2utf.__file__).parent / "files" / "map.json"
        self._mapper = FontMapper(str(map_path or default_map))

    def to_unicode(self, text: str) -> str:
        return self._mapper.map_to_unicode(text, from_font="Preeti")

    def should_convert(self, text: str) -> tuple[bool, str]:
        """Decide whether `text` is Preeti-encoded. Returns (decision, converted text or the original)."""
        if devanagari_share(text) >= LEGACY_MAX_SHARE or english_word_share(text) >= ENGLISH_WORD_SHARE:
            return False, text
        converted = self.to_unicode(text)
        if devanagari_share(converted) >= CONVERTED_MIN_SHARE:
            return True, converted
        return False, text

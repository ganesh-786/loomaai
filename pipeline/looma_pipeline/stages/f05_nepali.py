"""F5 Nepali check: is text that should be Nepali really Devanagari? Convert legacy Preeti PDFs.

Import only (called by looma_pipeline.pipeline). For every piece expected to be Nepali (a Nepali title, a lesson's
Nepali field, a Nepali textbook page) it measures the share of Devanagari letters. Nepali PDF pages
(document or textbook sources) that turn out to be Preeti-encoded are converted to Unicode. MongoDB fields are
never converted: when they are not Devanagari they are usually untranslated English, so they are only counted.
Language tags are refreshed after conversion.
Side effects: writes `f05_nepali.json` in the run folder.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from looma_pipeline.models import TextPiece
from looma_pipeline.runctx import RunContext
from looma_pipeline.text.preeti import PreetiConverter
from looma_pipeline.text.script import NEPALI_MIN_SHARE, devanagari_share, language_of

PDF_SOURCES = frozenset({"document", "textbook"})
MAX_EXAMPLES = 20


def check_pieces(pieces: list[TextPiece], converter: PreetiConverter) -> tuple[list[TextPiece], Counter, list]:
    """Returns (pieces with Preeti pages converted, counts, examples of non-Devanagari Nepali pieces)."""
    counts: Counter = Counter()
    examples = []
    checked: list[TextPiece] = []
    for piece in pieces:
        if not piece.expect_nepali:
            checked.append(piece)
            continue
        counts["expected_nepali"] += 1
        if devanagari_share(piece.text) >= NEPALI_MIN_SHARE:
            counts["devanagari_ok"] += 1
            checked.append(piece)
            continue
        if piece.source in PDF_SOURCES:
            convert, converted = converter.should_convert(piece.text)
            if convert:
                counts["converted_from_preeti"] += 1
                checked.append(replace(piece, text=converted, lang=language_of(converted)))
                continue
        counts[f"not_devanagari_{piece.source}"] += 1
        if len(examples) < MAX_EXAMPLES:
            examples.append({"item_id": piece.item_id, "source": piece.source, "order": piece.order,
                             "devanagari_share": round(devanagari_share(piece.text), 2), "start": piece.text[:60]})
        checked.append(piece)
    return checked, counts, examples


def run(ctx: RunContext, pieces: list[TextPiece]) -> list[TextPiece]:
    with ctx.stage("f05_nepali") as report:
        checked, counts, examples = check_pieces(pieces, PreetiConverter())
        report.counts.update(dict(sorted(counts.items())))
        report.counts.update({f"lang_{lang}": n for lang, n in sorted(Counter(p.lang for p in checked).items())})
        report.details["not_devanagari_examples"] = examples
        return checked

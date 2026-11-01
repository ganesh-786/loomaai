"""Text that already lives in MongoDB: activity titles, lesson slides and game prompts.

Import only; pure functions over records from the F1 snapshot. Lesson slides hold HTML in `html` (English) and
`nepali`; when the Nepali field is just a copy of the English one it is skipped, so the same text is not indexed
twice. Games hold `prompts` and `responses` lists.
"""

from __future__ import annotations

from looma_pipeline.models import TextPiece
from looma_pipeline.records import merged_fields
from looma_pipeline.text.normalize import html_to_text, normalize_text

TAXONOMY_KEYS = ("key1", "key2", "key3", "key4")


def title_pieces(doc: dict) -> list[TextPiece]:
    """The English title with its taxonomy, and the Nepali title, as separate pieces."""
    fields, _ = merged_fields(doc)
    item_id = str(fields["_id"])
    pieces = []
    english = fields.get("dn") if isinstance(fields.get("dn"), str) else ""
    taxonomy = [" ".join(str(fields.get(key)).split()) for key in TAXONOMY_KEYS if fields.get(key)]
    if english.strip():
        suffix = f" ({' · '.join(taxonomy)})" if taxonomy else ""
        pieces.append(TextPiece(item_id, "title", 0, f"{english}{suffix}"))
    nepali = fields.get("ndn") if isinstance(fields.get("ndn"), str) else ""
    if nepali.strip() and nepali.strip() != english.strip():
        pieces.append(TextPiece(item_id, "title", 1, nepali, expect_nepali=True))
    return pieces


def lesson_pieces(item_id: str, lesson: dict) -> list[TextPiece]:
    """One piece per inline slide and language. Slides that only reference another activity are skipped."""
    pieces = []
    for order, slide in enumerate(lesson.get("data") or []):
        if not isinstance(slide, dict) or slide.get("ft") != "inline":
            continue
        english = html_to_text(slide.get("html"))
        nepali = html_to_text(slide.get("nepali"))
        if english:
            pieces.append(TextPiece(item_id, "lesson", order, english))
        if nepali and nepali != english:
            pieces.append(TextPiece(item_id, "lesson", order, nepali, expect_nepali=True))
    return pieces


def _game_line(prompt: object, response: object) -> str:
    """One searchable line for a game entry.

    Matching and vocabulary games store a prompt string with a response string. Multiple-choice games store
    `{question, correctAns, wrongAns}`; only the question and the correct answer are kept, because the wrong
    answers are deliberately false and would make the game match searches for them.
    """
    if isinstance(prompt, dict):
        question, answer = prompt.get("question"), prompt.get("correctAns")
        question = question if isinstance(question, str) else ""
        answer = answer if isinstance(answer, str) else ""
        return f"{question} — {answer}" if question and answer else question or answer
    if isinstance(prompt, str):
        return f"{prompt} — {response}" if isinstance(response, str) and response else prompt
    return ""


def game_pieces(item_id: str, game: dict) -> list[TextPiece]:
    """One line per game entry ("metre — unit of length", "Through what do insects breathe? — Spiracles")."""
    prompts = game.get("prompts") or []
    responses = game.get("responses") or []
    lines = [_game_line(prompt, responses[i] if i < len(responses) else None) for i, prompt in enumerate(prompts)]
    text = normalize_text("\n".join(line for line in lines if line))
    return [TextPiece(item_id, "game", 0, text)] if text else []

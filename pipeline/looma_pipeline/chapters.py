"""Looma chapter ids: parsing and normalization.

Import only; pure functions. A chapter id such as `6S01.02` is grade + subject code + chapter number + optional
section. The pattern mirrors Looma-II's `LOOMA.CH_IDregex` (js/looma-utilities.js), anchored to the whole value.
In MongoDB, `ch_id` appears as a string, a list of strings, or (in `dictionary`) a list of `{subject: id}` objects;
`normalize_ch_ids()` turns all of these into one sorted tuple of valid ids.
"""

from __future__ import annotations

import re
from typing import Any

CHAPTER_ID_RE = re.compile(r"([1-9]|1[0-2])(EN|ENa|Sa|S|SF|Ma|M|SSa|SS|N|H|V|CS)(\d{2})(\.\d{2})?")


def is_chapter_id(value: str) -> bool:
    return CHAPTER_ID_RE.fullmatch(value) is not None


def chapter_grade(chapter_id: str) -> int | None:
    """The grade (1-12) of a chapter id, or None if the id is not valid."""
    match = CHAPTER_ID_RE.fullmatch(chapter_id)
    return int(match.group(1)) if match else None


def chapter_prefix(chapter_id: str) -> str | None:
    """Grade plus subject code, e.g. `6S` for `6S01.02`. Textbooks are keyed by this prefix."""
    match = CHAPTER_ID_RE.fullmatch(chapter_id)
    return f"{match.group(1)}{match.group(2)}" if match else None


def _flatten(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for nested in value.values() for item in _flatten(nested)]
    if isinstance(value, (list, tuple, set)):
        return [item for nested in value for item in _flatten(nested)]
    return []


def normalize_ch_ids(*values: Any) -> tuple[tuple[str, ...], int]:
    """Collect valid chapter ids from any of Looma's `ch_id` shapes.

    Args:
        *values: raw `ch_id` / `nch_id` field values (string, list, dict, list of dicts, or None).

    Returns:
        (sorted unique valid ids, number of non-empty values that were not valid chapter ids)
    """
    valid: set[str] = set()
    invalid = 0
    for raw in (part.strip() for value in values for part in _flatten(value)):
        if not raw:
            continue
        if is_chapter_id(raw):
            valid.add(raw)
        else:
            invalid += 1
    return tuple(sorted(valid)), invalid

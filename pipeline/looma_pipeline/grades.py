"""Grade values and grade bands.

Import only; pure functions. Looma stores `cl_lo` / `cl_hi` as integers, text or decimals, and 0 often means
"not set" (measured: int 5,098, string 657, double 224 in `activities`). A band is chosen by precedence (rag-engineering
skill, section 6): curated `cl_lo`/`cl_hi`, else the grades of linked chapters, else the game record, else unknown.
The age-window policy is open question S7; this module only records the band and where it came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from looma_pipeline.chapters import chapter_grade

MIN_GRADE, MAX_GRADE = 1, 12


@dataclass(frozen=True)
class GradeBand:
    lo: int | None
    hi: int | None
    source: str  # "curated" | "chapter" | "game" | "unknown"

    @property
    def known(self) -> bool:
        return self.lo is not None


UNKNOWN = GradeBand(None, None, "unknown")


def parse_grade(value: Any) -> int | None:
    """A grade 1-12 from an int, float or numeric string; None for 0, blanks, fractions or anything else."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if not number.is_integer():
        return None
    grade = int(number)
    return grade if MIN_GRADE <= grade <= MAX_GRADE else None


def band_from_pair(lo_value: Any, hi_value: Any, source: str) -> GradeBand | None:
    """A band when both ends are valid and in order; otherwise None."""
    lo, hi = parse_grade(lo_value), parse_grade(hi_value)
    if lo is None or hi is None or lo > hi:
        return None
    return GradeBand(lo, hi, source)


def band_from_chapters(chapter_ids: Iterable[str]) -> GradeBand | None:
    grades = [g for g in (chapter_grade(cid) for cid in chapter_ids) if g is not None]
    return GradeBand(min(grades), max(grades), "chapter") if grades else None


def choose_band(curated: GradeBand | None, chapter: GradeBand | None, game: GradeBand | None) -> GradeBand:
    return curated or chapter or game or UNKNOWN

"""Turn a search query into an FTS5 MATCH expression, with English-Nepali dictionary expansion.

Import only; pure functions plus dictionary lookups. Words are lowercased (Latin) and NFC-cleaned; very common words
are dropped. Word terms are prefix matches (`"term" *`), which also absorbs Nepali postpositions written as part of
the word (`नापमा` for `नाप`) and English plurals. Numbers are matched exactly: in titles such as "Old Nepal 00152"
they are identifiers. Each term is quoted, so user input can never inject FTS syntax.
"""

from __future__ import annotations

import re
import sqlite3

from looma_pipeline.text.normalize import normalize_text

STOP_WORDS = frozenset(
    "a an and are as at be by did do does for from how in is it of on or the to was what when where which who why "
    "with we you your our".split()
    + "र को का की मा ले लाई हो छ छन् तथा वा पनि भने गर्न".split()
)
MIN_PREFIX_CHARS = 2      # shorter terms are matched exactly, not as prefixes
MAX_TERMS = 12            # long pasted text is cut, so a query stays fast
MAX_EXPANSIONS_PER_TERM = 3
_TERM = re.compile(r"[\w\u0900-\u097F]+")


def query_terms(query: str) -> list[str]:
    """Distinct search terms in query order."""
    seen: list[str] = []
    for term in _TERM.findall(normalize_text(query).lower()):
        if term not in STOP_WORDS and term not in seen:
            seen.append(term)
    return seen[:MAX_TERMS]


def expand(terms: list[str], db: sqlite3.Connection) -> list[str]:
    """Add dictionary translations: English terms get their Nepali pairs and Nepali terms their English pairs."""
    expanded = list(terms)
    for term in terms:
        rows = db.execute("SELECT np FROM dictionary WHERE en = ? UNION SELECT en FROM dictionary WHERE np = ? "
                          "LIMIT ?", (term, term, MAX_EXPANSIONS_PER_TERM)).fetchall()
        for (translation,) in rows:
            for word in query_terms(translation):
                if word not in expanded:
                    expanded.append(word)
    return expanded


def match_expression(terms: list[str]) -> str | None:
    """`"t1" * OR "t2" * ...`, or None when there is nothing to search for.

    Terms are FTS5 strings: a double quote inside a term is doubled, so no input can add FTS operators.
    """
    if not terms:
        return None
    quoted = ['"' + t.replace('"', '""') + '"' for t in terms]
    return " OR ".join(f"{q} *" if len(t) >= MIN_PREFIX_CHARS and not t.isdigit() else q
                       for q, t in zip(quoted, terms))

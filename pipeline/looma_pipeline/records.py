"""Helpers for raw Looma records. Import only; pure functions."""

from __future__ import annotations


def merged_fields(doc: dict) -> tuple[dict, int]:
    """Fold BOM-prefixed keys from CSV imports (e.g. "\\ufeffcl_lo") into their clean names.

    The clean key wins when both exist.

    Returns:
        (fields with clean names, number of BOM-prefixed keys seen)
    """
    clean = {k: v for k, v in doc.items() if not k.startswith("\ufeff")}
    bom_keys = [k for k in doc if k.startswith("\ufeff")]
    for key in bom_keys:
        clean.setdefault(key.lstrip("\ufeff"), doc[key])
    return clean, len(bom_keys)

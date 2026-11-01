"""Retention for generated build outputs: which old bundles and run folders can go.

Import only; `python -m looma_pipeline clean` prints the plan (a dry run) and `clean --apply` carries it out. Only
folders the pipeline itself names are considered, and only directly inside `data/bundles/` and `data/runs/`:
- bundles: the newest `keep` per scope stay; older ones, and `.incoming-*` folders left by a stopped F13, can go;
- build runs: the newest `keep` per scope stay, plus every run that built a bundle that stays;
- e2e and eval-typos runs: the newest `keep` of each kind stay.
`data/models/`, `data/cache/` and `data/keys/` are never touched, nor anything else, and symbolic links are skipped.
Freed space counts a file only when every hard link to it is being deleted, because bundles share bytes with
their run's staging folder and with the prepared model.
Side effects: none for `plan()`; `remove()` deletes the planned folders.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from looma_pipeline.config import Settings

BUNDLE_NAME = re.compile(r"looma-ai-bundle-(\d{4}\.\d{2}\.\d{2})-([a-z]+)-r(\d+)")
INCOMING_NAME = re.compile(r"\.incoming-looma-ai-bundle-.+")
BUILD_RUN_NAME = re.compile(r"(\d{8}T\d{6}Z)-([a-z]+)-([0-9a-f]+)")
OTHER_RUN_NAME = re.compile(r"(e2e|eval-typos)-(\d{8}T\d{6}Z)")


@dataclass(frozen=True)
class Removal:
    path: Path
    reason: str


@dataclass(frozen=True)
class Plan:
    removals: list[Removal]
    kept: list[Path]
    freed_bytes: int          # space returned to the disk if every planned folder is deleted


def plan(settings: Settings, keep: int = 2) -> Plan:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    removals: list[Removal] = []
    kept: list[Path] = []

    bundles: dict[str, list[tuple[tuple[str, int], Path]]] = {}
    for path in _folders(settings.bundles_dir):
        if INCOMING_NAME.fullmatch(path.name):
            removals.append(Removal(path, "half-written bundle from a stopped F13"))
        elif match := BUNDLE_NAME.fullmatch(path.name):
            bundles.setdefault(match.group(2), []).append(((match.group(1), int(match.group(3))), path))
    kept_runs: set[str] = set()
    for scope, entries in bundles.items():
        ordered = [path for _key, path in sorted(entries, reverse=True)]
        kept += ordered[:keep]
        removals += [Removal(p, f"older than the newest {keep} {scope} bundles") for p in ordered[keep:]]
        kept_runs |= {run for p in ordered[:keep] if (run := _run_of(p))}

    runs: dict[str, list[tuple[str, Path]]] = {}
    for path in _folders(settings.runs_dir):
        if match := BUILD_RUN_NAME.fullmatch(path.name):
            runs.setdefault(f"{match.group(2)} build", []).append((match.group(1), path))
        elif match := OTHER_RUN_NAME.fullmatch(path.name):
            runs.setdefault(match.group(1), []).append((match.group(2), path))
    for kind, entries in runs.items():
        ordered = [path for _stamp, path in sorted(entries, reverse=True)]
        for index, path in enumerate(ordered):
            if index < keep or path.name in kept_runs:
                kept.append(path)
            else:
                removals.append(Removal(path, f"older than the newest {keep} {kind} runs"))
    return Plan(removals, kept, _freed_bytes([r.path for r in removals]))


def remove(planned: Plan) -> int:
    """Delete the planned folders. Returns the number deleted."""
    for removal in planned.removals:
        shutil.rmtree(removal.path)
    return len(planned.removals)


def _folders(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()) if root.is_dir() else []


def _run_of(bundle: Path) -> str | None:
    try:
        return json.loads((bundle / "manifest.json").read_text(encoding="utf-8")).get("run_id")
    except (OSError, ValueError):
        return None


def _freed_bytes(folders: list[Path]) -> int:
    links: Counter = Counter()
    sizes: dict[tuple[int, int], tuple[int, int]] = {}
    for folder in folders:
        for path in folder.rglob("*"):
            if path.is_file() and not path.is_symlink():
                info = path.stat()
                key = (info.st_dev, info.st_ino)
                links[key] += 1
                sizes[key] = (info.st_nlink, info.st_blocks * 512)
    return sum(size for key, (nlink, size) in sizes.items() if links[key] >= nlink)

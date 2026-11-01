"""File helpers for build outputs that are never changed after they are written.

Import only. `link_or_copy` hard-links when source and target are on one filesystem, so a bundle shares the bytes
of the prepared model and of its run's staged files instead of copying them (about 183 MB per full-scope build),
and falls back to a copy where a link is impossible. Sharing is safe only because no file here is ever rewritten in
place: every write goes to a temporary file that is then renamed over the target, which gives the target a new
inode and leaves linked copies untouched. `verify` also refuses a bundle whose files changed.
Side effects: creates files; `os.replace` removes the target's previous directory entry.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable


def temporary_sibling(target: Path) -> Path:
    """A path next to `target` for writing before the rename; any stale one is removed first."""
    temporary = target.with_name(f".{target.name}.part")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    return temporary


def link_or_copy(source: Path, target: Path) -> bool:
    """Put `source`'s content at `target` as a new directory entry. Returns True if it was hard-linked."""
    temporary = temporary_sibling(target)
    try:
        os.link(source, temporary)
        linked = True
    except OSError:  # another filesystem, or one without hard links
        shutil.copy2(source, temporary)
        linked = False
    os.replace(temporary, target)
    return linked


def write_atomically(target: Path, write: Callable[[Path], None]) -> None:
    """Call `write(path)` on a temporary file, then rename it over `target`."""
    temporary = temporary_sibling(target)
    try:
        write(temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def copy_tree_linked(source: Path, target: Path) -> tuple[int, int]:
    """Copy a folder tree, hard-linking each file where possible. Returns (files linked, files copied)."""
    counts = [0, 0]

    def place(file_source: str, file_target: str) -> str:
        counts[0 if link_or_copy(Path(file_source), Path(file_target)) else 1] += 1
        return file_target

    shutil.copytree(source, target, copy_function=place)
    return counts[0], counts[1]

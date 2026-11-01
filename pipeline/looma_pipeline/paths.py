"""Where Looma keeps a file, resolved the same way Looma-II does.

Import only; pure functions plus `Path` checks. An activity's file is `fp + fn`; when `fp` is missing, Looma uses a
default folder per file type. The defaults below are the union of Looma-II's PHP map
(includes/looma-utilities.php) and JavaScript map (`LOOMA.filepath` in js/looma-utilities.js). Looma paths are
relative to its web root (`../content/...`); `to_local()` maps them into the pipeline's content folder and refuses
anything that would escape it.
"""

from __future__ import annotations

import os
from pathlib import Path

LOOMA_CONTENT_PREFIX = "../content/"

# includes/looma-utilities.php default-path map
_PHP_DEFAULTS = {
    "video": "videos/", "mp4": "videos/", "MP4": "videos/", "mp5": "videos/", "m4v": "videos/", "mov": "videos/",
    "image": "pictures/", "jpg": "pictures/", "jpeg": "pictures/", "JPG": "pictures/", "png": "pictures/",
    "gif": "pictures/", "audio": "audio/", "mp3": "audio/", "m4a": "audio/", "pdf": "pdfs/", "html": "html/",
    "HTML": "html/", "slideshow": "slideshows/", "evi": "videos/",
}
# Types only the JavaScript map knows (js/looma-utilities.js, LOOMA.filepath)
_JS_EXTRAS = {
    "worksheet": "worksheets/", "EP": "epaath/activities/", "epaath": "epaath/activities/",
    "textbook": "textbooks/", "chapter": "chapters/",
}
DEFAULT_FOLDERS = {ft: LOOMA_CONTENT_PREFIX + folder for ft, folder in {**_PHP_DEFAULTS, **_JS_EXTRAS}.items()}


def looma_file_path(ft: str | None, fp: str | None, fn: str | None) -> str | None:
    """The path Looma would open for an activity, relative to its web root, or None if it has no file name."""
    if not fn or not str(fn).strip():
        return None
    folder = (fp or "").strip() or DEFAULT_FOLDERS.get(ft or "", "")
    return f"{folder}{str(fn).strip()}"


def is_external(looma_path: str) -> bool:
    return looma_path.lower().startswith(("http://", "https://", "//"))


def to_local(looma_path: str, content_dir: Path) -> Path | None:
    """Map a Looma path such as `../content/videos/a.mp4` into `content_dir`.

    Returns None when the path is outside Looma's content folder, or when it would escape `content_dir`
    (for example through `..` segments), so the pipeline can never read files it was not given.
    """
    if not looma_path.startswith(LOOMA_CONTENT_PREFIX):
        return None
    relative = looma_path[len(LOOMA_CONTENT_PREFIX):]
    candidate = Path(os.path.normpath(content_dir / relative))
    root = Path(os.path.normpath(content_dir))
    if candidate != root and root not in candidate.parents:
        return None
    return candidate

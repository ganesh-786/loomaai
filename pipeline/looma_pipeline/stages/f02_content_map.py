"""F2 content map: for every in-scope item, the file Looma would open, or the reason there is none.

Import only (called by looma_pipeline.pipeline). Reads the F1 snapshot and checks files under the content folder
(read only). Lessons and games keep their text in MongoDB, so they need no file. Chapters point at page ranges of
their textbook PDF. Text-bearing files (PDF, worksheet, HTML, captions, textbooks) are fingerprinted with SHA-256,
so later runs can tell what changed.
Side effects: writes `f02_content_map.json` and `content_map.jsonl` in the run folder.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from looma_pipeline.chapters import chapter_prefix
from looma_pipeline.hashing import sha256_of_file
from looma_pipeline.paths import LOOMA_CONTENT_PREFIX, is_external, looma_file_path, to_local
from looma_pipeline.runctx import RunContext
from looma_pipeline.stages.f01_snapshot import Snapshot

DATABASE_TYPES = frozenset({"lesson", "game"})       # text lives in MongoDB (lessons, games collections)
DOCUMENT_TYPES = frozenset({"pdf", "worksheet", "html"})  # text is extracted from the file itself


@dataclass(frozen=True)
class FileRef:
    """One file an item's text can come from."""

    role: str                  # "document" | "captions" | "textbook_en" | "textbook_np"
    looma_path: str
    local_path: str | None
    exists: bool
    size: int | None = None
    sha256: str | None = None
    page_start: int | None = None  # 1-based first page, for textbook chapters
    page_count: int | None = None


@dataclass(frozen=True)
class ContentEntry:
    item_id: str
    ft: str
    kind: str                  # "database" | "document" | "captions" | "textbook_pages" | "title_only"
    files: tuple[FileRef, ...]
    reason: str | None         # why no usable file, e.g. "file missing"; None when every file was found


def _file_ref(role: str, looma_path: str, ctx: RunContext, page_start: int | None = None,
              page_count: int | None = None) -> FileRef:
    local = to_local(looma_path, ctx.settings.content_dir)
    if local is None or not local.is_file():
        return FileRef(role, looma_path, str(local) if local else None, False, page_start=page_start,
                       page_count=page_count)
    return FileRef(role, looma_path, str(local), True, local.stat().st_size, sha256_of_file(local),
                   page_start, page_count)


def _missing_reason(files: tuple[FileRef, ...]) -> str | None:
    if not files:
        return "no file"
    if all(f.exists for f in files):
        return None
    if any(f.local_path is None and not f.looma_path.startswith(LOOMA_CONTENT_PREFIX) for f in files):
        return "outside the content folder"
    return "file missing"


def _textbook_files(doc: dict, snapshot: Snapshot, ctx: RunContext) -> tuple[tuple[FileRef, ...], str | None]:
    chapter_id = str(doc.get("ID", "")).strip()
    chapter = snapshot.chapters.get(chapter_id)
    textbook = snapshot.textbooks.get(chapter_prefix(chapter_id) or "")
    if chapter is None or textbook is None:
        return (), "no chapter or textbook record"
    files = []
    for role, name_key, start_key, length_key in (("textbook_en", "fn", "pn", "len"),
                                                  ("textbook_np", "nfn", "npn", "nlen")):
        name, start, length = textbook.get(name_key), chapter.get(start_key), chapter.get(length_key)
        if name and isinstance(start, int) and isinstance(length, int) and length > 0:
            path = f"{LOOMA_CONTENT_PREFIX}{textbook.get('fp', '')}{name}"
            files.append(_file_ref(role, path, ctx, page_start=start, page_count=length))
    if not files:
        return (), "no page range"  # e.g. a chapter heading with len 0
    return tuple(files), None


def map_item(doc: dict, snapshot: Snapshot, ctx: RunContext) -> ContentEntry:
    """Decide where one item's text comes from."""
    item_id, ft = str(doc["_id"]), str(doc.get("ft") or "")
    if ft in DATABASE_TYPES:
        return ContentEntry(item_id, ft, "database", (), None)
    if ft == "chapter":
        files, reason = _textbook_files(doc, snapshot, ctx)
        return ContentEntry(item_id, ft, "textbook_pages", files, reason or _missing_reason(files))
    if ft == "video" and doc.get("captions"):
        captions = str(doc["captions"]).strip()
        files = (_file_ref("captions", captions, ctx),)
        return ContentEntry(item_id, ft, "captions", files, _missing_reason(files))
    path = looma_file_path(ft, doc.get("fp"), doc.get("fn"))
    if ft in DOCUMENT_TYPES:
        if path is None:
            return ContentEntry(item_id, ft, "document", (), "no file name")
        if is_external(path):
            return ContentEntry(item_id, ft, "document", (), "external url")
        files = (_file_ref("document", path, ctx),)
        return ContentEntry(item_id, ft, "document", files, _missing_reason(files))
    return ContentEntry(item_id, ft, "title_only", (), None)


def run(ctx: RunContext, snapshot: Snapshot) -> dict[str, ContentEntry]:
    """Map every in-scope item. Returns entries keyed by item id."""
    with ctx.stage("f02_content_map") as report:
        entries = {str(doc["_id"]): map_item(doc, snapshot, ctx) for doc in snapshot.activities}
        kinds = Counter(entry.kind for entry in entries.values())
        reasons = Counter(entry.reason for entry in entries.values() if entry.reason)
        files = [f for entry in entries.values() for f in entry.files]
        report.counts.update({f"kind_{k}": v for k, v in sorted(kinds.items())})
        report.counts.update({"files_referenced": len(files), "files_found": sum(f.exists for f in files)})
        report.details["missing_reasons"] = dict(sorted(reasons.items()))
        report.details["content_dir"] = str(ctx.settings.content_dir)
        ctx.write_jsonl("content_map.jsonl", (asdict(entry) for entry in entries.values()))
        return entries

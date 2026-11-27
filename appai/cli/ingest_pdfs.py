"""Ingest Looma PDFs page by page: plumbing, cleaning and metadata (fork issues #2, #3, #4).

What: for textbook chapters (their English page range), `pdf` and `worksheet` activities, reads each page from a
local copy of Looma's content folder, uses a reviewed transcript for a page when one exists, cleans the text
and writes one JSON record per page with Looma metadata and provenance, plus a run report.
Why: main's embed path downloads every PDF, joins its pages, and writes cl_lo/cl_hi back into Mongo. This step
keeps page numbers and provenance, writes nothing to Mongo or Qdrant, and leaves embed.py unchanged.
How (build plane only; the Looma Box never runs it):
    python -m appai.cli.ingest_pdfs --content-dir data/content --ch-id 10S04 --linked            # dry run
    python -m appai.cli.ingest_pdfs --content-dir data/content --ch-id 10S04 --linked --write \\
        --transcripts <transcript run folder> [--allow-unreviewed]
    Selection: --ch-id (repeatable; --linked adds the pdf/worksheet items whose ch_id has it), --activity-id
    (repeatable), or --all. English only: lang "np" items are reported as language_not_in_scope.
Inputs: MONGO_URI (default mongodb://localhost:47017, as in the Makefile), MONGO_DB (looma), CONTENT_DIR or
    --content-dir (Looma's content layout), transcript run folders, TRANSCRIPTS_ALLOW_UNREVIEWED=1 or
    --allow-unreviewed, CODE_COMMIT (recorded in the report).
Outputs: with --write, <out>/<run_id>/pages.jsonl and report.json (default out: data/ingest, gitignored).
    Without --write nothing is written; the summary is printed.
Side effects: reads Mongo (find/find_one/ping only) and local files. No network besides Mongo; no downloads.
Exit codes: 0 done; 1 done but some items failed (see report items); 2 configuration or infrastructure error.
"""

import argparse
import datetime
import hashlib
import json
import logging
import os
import platform
import resource
import sys
import time
from collections import Counter

import fitz
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from ..common.activity import PageSourceError, extract_page_texts
from ..common.activity_chapter import ChapterActivity
from ..common.activity_pdf import PdfActivity
from ..common.page_metadata import SCHEMA, build_page_record, printed_page_offset, resolve_printed_page
from ..common.text_cleaning import clean_text_layer_pages, clean_transcript_text
from ..common.transcripts import load_transcript_runs

logger = logging.getLogger(__name__)

ITEM_TYPES = ("chapter", "pdf", "worksheet")
LINKED_TYPES = ("pdf", "worksheet")
IN_SCOPE_LANGS = ("en", "both", None)   # English first (Task 1 pilot); "both" items hold English text too
SKIP_REASONS = {"no_page_range", "no_english_textbook", "language_not_in_scope", "type_not_in_scope"}  # data facts
DEFAULT_MONGO_URI = "mongodb://localhost:47017"   # Makefile:12
DEFAULT_OUT_DIR = os.path.join("data", "ingest")
MONGO_TIMEOUT_MS = 5000


class ConfigError(Exception):
    """A setting or argument is wrong; the message says how to fix it (exit code 2)."""


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parses command-line arguments; environment variables give the defaults."""
    parser = argparse.ArgumentParser(description="Ingest Looma PDFs page by page (dry run unless --write).")
    parser.add_argument("--ch-id", action="append", default=[], help="chapter id, e.g. 10S04 (repeatable)")
    parser.add_argument("--linked", action="store_true", help="also ingest pdf/worksheet items linked to --ch-id")
    parser.add_argument("--activity-id", action="append", default=[], help="activities _id (repeatable)")
    parser.add_argument("--all", action="store_true", help="every chapter, pdf and worksheet activity")
    parser.add_argument("--content-dir", default=os.environ.get("CONTENT_DIR"), help="Looma content folder")
    parser.add_argument("--transcripts", action="append", default=[], help="transcript run folder (repeatable)")
    parser.add_argument("--allow-unreviewed", action="store_true",
                        default=os.environ.get("TRANSCRIPTS_ALLOW_UNREVIEWED") == "1",
                        help="use unreviewed transcripts too (rejected ones never)")
    parser.add_argument("--write", action="store_true", help="write pages.jsonl and report.json")
    parser.add_argument("--out", default=os.environ.get("INGEST_OUT_DIR", DEFAULT_OUT_DIR), help="output root")
    parser.add_argument("--run-id", help="override the generated run id")
    parser.add_argument("--mongo-uri", default=os.environ.get("MONGO_URI", DEFAULT_MONGO_URI))
    parser.add_argument("--mongo-db", default=os.environ.get("MONGO_DB", "looma"))
    return parser.parse_args(argv)


def check_content_dir(content_dir: str | None) -> str:
    """Fails fast when the content folder is unset, missing or empty (on this machine use data/content)."""
    if not content_dir:
        raise ConfigError("set CONTENT_DIR or --content-dir to a copy of Looma's content folder")
    if not os.path.isdir(content_dir) or not os.listdir(content_dir):
        raise ConfigError(f"content folder {content_dir!r} is missing or empty")
    return content_dir


def select_items(db, args: argparse.Namespace) -> tuple[list[dict], list[dict]]:
    """Finds the activities to ingest.

    Returns:
        (activity documents sorted by _id, item reports for requests that matched nothing).
    """
    if not (args.ch_id or args.activity_id or args.all):
        raise ConfigError("choose items with --ch-id, --activity-id or --all")
    try:
        object_ids = [ObjectId(value) for value in args.activity_id]
    except (InvalidId, TypeError) as error:
        raise ConfigError(f"--activity-id: {error}") from error

    found: dict[str, dict] = {}
    missing: list[dict] = []
    for chapter_id in args.ch_id:
        chapters = list(db.activities.find({"ft": "chapter", "ID": chapter_id}))
        if not chapters:
            missing.append({"item_id": None, "requested": chapter_id, "ft": "chapter", "status": "failed",
                            "reason": "chapter_activity_not_found", "detail": chapter_id, "pages": 0})
        found.update((str(doc["_id"]), doc) for doc in chapters)
        if args.linked:
            linked = db.activities.find({"ft": {"$in": list(LINKED_TYPES)}, "ch_id": chapter_id})
            found.update((str(doc["_id"]), doc) for doc in linked)
    if object_ids:
        by_id = {str(doc["_id"]): doc for doc in db.activities.find({"_id": {"$in": object_ids}})}
        for object_id in object_ids:
            if str(object_id) not in by_id:
                missing.append({"item_id": str(object_id), "ft": None, "status": "failed",
                                "reason": "activity_not_found", "detail": str(object_id), "pages": 0})
        found.update(by_id)
    if args.all:
        found.update((str(doc["_id"]), doc) for doc in db.activities.find({"ft": {"$in": list(ITEM_TYPES)}}))
    return [found[key] for key in sorted(found)], missing


def _activity_for(item: dict):
    return ChapterActivity(item) if item.get("ft") == "chapter" else PdfActivity(item)


def ingest_item(item: dict, db, content_dir: str, transcripts, allow_unreviewed: bool,
                run_id: str) -> tuple[list[dict], dict, dict]:
    """Plumbing, cleaning and metadata for one activity.

    Returns:
        (page records, item report, cleaning details {"removed_lines", "hyphens"} with PDF page numbers).
    """
    report = {"item_id": str(item["_id"]), "ft": item.get("ft"), "dn": item.get("dn"), "status": "ok",
              "reason": None, "detail": None, "pages": 0}
    details = {"removed_lines": [], "hyphens": []}

    def stop(reason: str, detail: str) -> tuple[list[dict], dict, dict]:
        report.update(status="skipped" if reason in SKIP_REASONS else "failed", reason=reason, detail=detail)
        return [], report, details

    if item.get("ft") not in ITEM_TYPES:
        return stop("type_not_in_scope", str(item.get("ft")))
    lang = "en" if item.get("ft") == "chapter" else item.get("lang")
    if lang not in IN_SCOPE_LANGS:
        return stop("language_not_in_scope", str(lang))
    try:
        activity = _activity_for(item)
    except TypeError:  # ChapterActivity's id pattern did not match
        return stop("bad_chapter_id", str(item.get("ID")))
    try:
        source = activity.page_source(db, content_dir)
        with open(source.path, "rb") as handle:
            data = handle.read()
        texts = extract_page_texts(data, source.first_page, source.last_page)
    except PageSourceError as error:
        return stop(error.reason, error.detail)
    except FileNotFoundError:
        return stop("missing_file", source.relative_path)
    except OSError as error:  # a folder, no permission, I/O error
        return stop("unreadable_file", f"{source.relative_path}: {error}")

    file_sha256 = hashlib.sha256(data).hexdigest()
    pdf_pages = list(range(source.first_page, source.first_page + len(texts)))
    cleaned, cleaning = clean_text_layer_pages(texts)
    offset_vote = printed_page_offset(cleaning["removed_lines"], pdf_pages)
    base = activity.payload() if "dn" in item else {"collection": "activities", "source_id": str(item["_id"]),
                                                     "title": None}
    records, methods = [], Counter()
    for index, pdf_page in enumerate(pdf_pages):
        choice = transcripts.choose(source.relative_path, file_sha256, pdf_page, allow_unreviewed)
        removed = [r for r in cleaning["removed_lines"] if r["page_index"] == index]
        hyphens = [h for h in cleaning["hyphens"] if h["page_index"] == index]
        details["removed_lines"] += [{"pdf_page": pdf_page, "line": r["line"], "rule": r["rule"]} for r in removed]
        details["hyphens"] += [{"pdf_page": pdf_page, "parts": h["parts"], "result": h["result"]} for h in hyphens]
        if choice.page:
            text, markers = clean_transcript_text(choice.page.text)
            page_cleaning = {"markers": markers}
        else:
            text = cleaned[index]
            page_cleaning = {"lines_removed": len(removed),
                             "hyphens_joined": sum(1 for h in hyphens if h["result"] == "joined"),
                             "hyphens_kept": sum(1 for h in hyphens if h["result"] == "kept_hyphen")}
        printed = resolve_printed_page(pdf_page, choice.page.printed_page if choice.page else None, offset_vote)
        records.append(build_page_record(
            run_id=run_id, item=item, base=base, lang=lang, relative_path=source.relative_path,
            file_sha256=file_sha256, pdf_page=pdf_page, printed_page=printed, text=text,
            fallback_reason=choice.fallback_reason, transcript=choice.page, cleaning=page_cleaning))
        methods[records[-1]["text_method"]] += 1
    report.update(pages=len(records), file=source.relative_path, file_sha256=file_sha256,
                  page_range=[pdf_pages[0], pdf_pages[-1]], methods=dict(methods), printed_page_offset=offset_vote,
                  grade_source=records[0]["looma"]["grade"]["source"])
    return records, report, details


def _content_sha256(records: list[dict]) -> str:
    """Hash of the records without run_id, so two runs over the same input compare equal."""
    digest = hashlib.sha256()
    for record in records:
        digest.update(json.dumps({k: v for k, v in record.items() if k != "run_id"}, ensure_ascii=False,
                                 sort_keys=True).encode("utf-8") + b"\n")
    return digest.hexdigest()


def _run_id(args: argparse.Namespace) -> str:
    if args.run_id:
        return args.run_id
    config = json.dumps({k: v for k, v in sorted(vars(args).items()) if k not in ("write", "out")}, default=str)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"pdfingest-{stamp}-{hashlib.sha256(config.encode()).hexdigest()[:8]}"


def write_run(out_root: str, run_id: str, records: list[dict], report: dict) -> str:
    """Writes pages.jsonl and report.json into <out_root>/<run_id> atomically; never overwrites a run."""
    final = os.path.join(out_root, run_id)
    partial = final + ".partial"
    if os.path.exists(final) or os.path.exists(partial):
        raise ConfigError(f"{final} already exists; choose another --run-id or remove it yourself")
    os.makedirs(partial)
    with open(os.path.join(partial, "pages.jsonl"), "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    with open(os.path.join(partial, "report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1, sort_keys=True)
        handle.write("\n")
    os.rename(partial, final)
    return final


def run(args: argparse.Namespace, db) -> int:
    """Runs the ingest against an open (read-only used) database; returns the exit code."""
    started = time.monotonic()
    run_id = _run_id(args)
    try:
        content_dir = check_content_dir(args.content_dir)
        items, item_reports = select_items(db, args)
    except ConfigError as error:
        logger.error("%s", error)
        return 2
    transcripts = load_transcript_runs(args.transcripts)

    records, removed_lines, hyphens = [], [], []
    for item in items:
        item_records, item_report, details = ingest_item(item, db, content_dir, transcripts,
                                                         args.allow_unreviewed, run_id)
        records += item_records
        item_reports.append(item_report)
        removed_lines += [dict(d, item_id=item_report["item_id"]) for d in details["removed_lines"]]
        hyphens += [dict(d, item_id=item_report["item_id"]) for d in details["hyphens"]]
        if item_report["status"] != "ok":
            logger.info("%s %s: %s (%s)", item_report["status"], item_report["item_id"], item_report["reason"],
                        item_report["detail"])

    markers = Counter()
    for record in records:
        markers.update(record["cleaning"].get("markers", {}))
    counts = {
        "items": dict(Counter(r["status"] for r in item_reports)),
        "item_reasons": dict(Counter(r["reason"] for r in item_reports if r["reason"])),
        "pages_by_method": dict(Counter(r["text_method"] for r in records)),
        "fallback_reasons": dict(Counter(r["fallback_reason"] for r in records if r["fallback_reason"])),
        "markers": dict(markers),
        "lines_removed": dict(Counter(line["rule"] for line in removed_lines)),
        "hyphens": dict(Counter(h["result"] for h in hyphens)),
        "printed_page_source": dict(Counter(r["source"]["printed_page_source"] for r in records)),
        "grade_source": dict(Counter(r["grade_source"] for r in item_reports if r.get("grade_source"))),
        "review_status": dict(Counter(r["review_status"] for r in records)),
        "empty_pages": sum(1 for r in records if not r["text"]),
    }
    # A page whose text layer held only the footer (10S04 p93 is a concept-map image) keeps its record for
    # traceability; the list tells the next step (chunking) and a reviewer which pages need another source.
    empty_pages = [{"item_id": r["source"]["item_id"], "pdf_page": r["source"]["pdf_page"],
                    "text_method": r["text_method"]} for r in records if not r["text"]]
    report = {
        "run_id": run_id, "schema": SCHEMA, "dry_run": not args.write,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "code_commit": os.environ.get("CODE_COMMIT", "unknown"),
        "versions": {"python": platform.python_version(), "pymupdf": fitz.VersionBind},
        "config": {"content_dir": content_dir, "transcripts": args.transcripts,
                   "allow_unreviewed": args.allow_unreviewed, "ch_id": args.ch_id, "linked": args.linked,
                   "activity_id": args.activity_id, "all": args.all, "mongo_db": args.mongo_db},
        "transcript_runs": transcripts.runs, "transcript_problems": transcripts.problems,
        "counts": counts, "records": len(records), "content_sha256": _content_sha256(records),
        "items": item_reports, "removed_lines": removed_lines, "hyphens": hyphens, "empty_pages": empty_pages,
        "duration_s": round(time.monotonic() - started, 2),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "cost_note": "dev-machine numbers, not Box numbers",
    }
    written = "dry-run (nothing written)"
    if args.write:
        try:
            written = write_run(args.out, run_id, records, report)
        except ConfigError as error:
            logger.error("%s", error)
            return 2
    print(f"run_id={run_id} items={counts['items']} pages={len(records)} methods={counts['pages_by_method']} "
          f"duration_s={report['duration_s']} output={written}")
    return 1 if counts["items"].get("failed") else 0


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point: opens Mongo read-only in practice (find/ping only) and runs the ingest."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    try:
        check_content_dir(args.content_dir)
    except ConfigError as error:
        logger.error("%s", error)
        return 2
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=MONGO_TIMEOUT_MS)
    try:
        db = client[args.mongo_db]
        try:
            db.command("ping")
        except PyMongoError as error:
            logger.error("cannot reach Mongo at %s (set MONGO_URI or --mongo-uri): %s", args.mongo_uri, error)
            return 2
        return run(args, db)
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())

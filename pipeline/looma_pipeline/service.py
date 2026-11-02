"""looma-search: the HTTP search service of the serve plane (Looma Box and online servers).

Import only; `python -m looma_pipeline serve <bundle>` starts it. Looma-II's PHP calls it on the local network with
a time limit and falls back to its keyword search, so the service adds to search and can never take it down.

Endpoints (GET only, JSON, UTF-8):
  /health  the bundle, model, counts and policy in use
  /search  q (required), mode = library | chapter | related, chapter (chapter modes), type (repeatable),
           grade (library mode only), k, spelling = 1 | 0
Modes: `library` searches everything. `chapter` searches only the resources linked to the chapter. `related` searches
the library for the chapter's subject and grade window, and widens to all subjects when too few results come back
(the response says so). The grade window, the unknown-grade rule and the score cutoff are provisional until Skip
decides (open question S7).
Side effects: one JSON log line per request with path, status, time and query length, never the query text.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
import traceback
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import parse_qs

from looma_pipeline.chapters import CHAPTER_ID_RE, chapter_grade
from looma_pipeline.config import Settings, _int, _text
from looma_pipeline.search import Filters, Hit, SearchEngine
from looma_pipeline.spelling import SpellCheck

log = logging.getLogger(__name__)

MODES = ("library", "chapter", "related")
PARAMETERS = frozenset({"q", "mode", "chapter", "type", "grade", "k", "spelling"})
PASSAGE_CHARS = 200          # length of the passage snippet in each result
MAX_QUERY_STRING = 4096      # longer query strings are refused before parsing
MAX_FIELDS = 20
# Subject labels (as cleaned by F4) that count as a chapter's subject, by the subject code in its id. V and CS have
# no matching label, so their related search covers all subjects.
CHAPTER_SUBJECTS = {
    "S": {"Science"}, "SF": {"Science"}, "Sa": {"Science"},
    "M": {"Mathematics"}, "Ma": {"Mathematics"},
    "SS": {"Social Studies"}, "SSa": {"Social Studies"},
    "EN": {"English", "Language"}, "ENa": {"English", "Language"},
    "N": {"Nepali", "Language"}, "H": {"Health"},
}
REASONS = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed", 414: "URI Too Long",
           500: "Internal Server Error"}


@dataclass(frozen=True)
class Policy:
    """Request limits and the provisional search rules; docs/configuration.md lists the environment variables."""

    max_query_chars: int = 200
    max_k: int = 50
    default_k: int = 10
    grade_window: int = 1                # chapter grade plus or minus this many grades (provisional, S7)
    min_similarity: float | None = None  # off until calibrated on the golden questions (provisional)
    related_min_results: int = 3         # fewer results in the chapter's subject: widen to all subjects
    cehrd_server: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str], settings: Settings) -> "Policy":
        cutoff = _text(env, "SEARCH_MIN_SIMILARITY", "")
        try:
            min_similarity = float(cutoff) if cutoff else None
        except ValueError as exc:
            raise ValueError(f"SEARCH_MIN_SIMILARITY must be a number (got {cutoff!r})") from exc
        return cls(max_query_chars=_int(env, "SEARCH_MAX_QUERY_CHARS", 200, 1),
                   max_k=_int(env, "SEARCH_MAX_RESULTS", 50, 1),
                   grade_window=_int(env, "SEARCH_GRADE_WINDOW", 1, 0),
                   min_similarity=min_similarity,
                   related_min_results=_int(env, "SEARCH_RELATED_MIN_RESULTS", 3, 0),
                   cehrd_server=settings.is_cehrd_server)


@dataclass(frozen=True)
class Listen:
    host: str = "127.0.0.1"
    port: int = 47200
    threads: int = 4

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Listen":
        return cls(_text(env, "SEARCH_HOST", "127.0.0.1"), _int(env, "SEARCH_PORT", 47200, 1),
                   _int(env, "SEARCH_THREADS", 4, 1))


class RequestError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class BundleRefused(Exception):
    """The bundle failed verification, so the service does not start."""


class SearchService:
    """Answers health and search requests over one loaded bundle.

    Searches run one at a time behind a lock, because the engine's SQLite connection belongs to one thread. A search
    takes about 10 ms on the development machine, which leaves room for a classroom of queries.
    """

    def __init__(self, engine: SearchEngine, manifest: Mapping[str, Any], policy: Policy) -> None:
        self.engine = engine
        self.manifest = manifest
        self.policy = policy
        self.types = frozenset(str(ft) for ft in engine.item_ft)
        self.chapters = frozenset(engine.chapter_items)
        self._lock = threading.Lock()

    def health(self) -> dict:
        embedding = self.manifest.get("embedding", {})
        return {"status": "ok", "bundle": self.manifest.get("bundle_name"),
                "schema": self.manifest.get("schema_version"), "created_at": self.manifest.get("created_at"),
                "model": {"repo": embedding.get("repo"), "revision": embedding.get("revision")},
                "items": len(self.engine.item_ids), "passages": int(self.engine.vectors.shape[0]),
                "policy": asdict(self.policy)}

    def search(self, params: Mapping[str, list[str]]) -> dict:
        unknown = sorted(set(params) - PARAMETERS)
        if unknown:
            raise RequestError(400, f"unknown parameter: {unknown[0]}")
        query = _single(params, "q", "").strip()
        if not query:
            raise RequestError(400, "q is required")
        if len(query) > self.policy.max_query_chars:
            raise RequestError(400, f"q is longer than {self.policy.max_query_chars} characters")
        mode = _single(params, "mode", "library")
        if mode not in MODES:
            raise RequestError(400, "mode must be library, chapter or related")
        k = _whole_number(params, "k", self.policy.default_k, 1, self.policy.max_k)
        spelling = _single(params, "spelling", "1")
        if spelling not in ("0", "1"):
            raise RequestError(400, "spelling must be 0 or 1")
        types = frozenset(params.get("type", []))
        if types - self.types:
            raise RequestError(400, f"unknown type: {sorted(types - self.types)[0]}")
        chapter = self._chapter(params, mode)
        filters = self._filters(mode, chapter, types, params)

        hits, check, ms = self._run(query, filters, k, spelling == "1")
        widened = False
        if mode == "related" and filters.subjects and len(hits) < self.policy.related_min_results:
            hits, check, more_ms = self._run(query, replace(filters, subjects=frozenset()), k, spelling == "1")
            ms, widened = ms + more_ms, True
        return {"query": query, "mode": mode, "chapter": chapter, "count": len(hits), "widened": widened,
                "results": [_result(hit) for hit in hits], "spelling": _spelling(check), "ms": round(ms, 1),
                "bundle": self.manifest.get("bundle_name")}

    def _chapter(self, params: Mapping[str, list[str]], mode: str) -> str | None:
        chapter = _single(params, "chapter", "").strip()
        if mode == "library":
            if chapter:
                raise RequestError(400, "chapter is only used in chapter and related modes")
            return None
        if not chapter:
            raise RequestError(400, "chapter is required in chapter and related modes")
        if not CHAPTER_ID_RE.fullmatch(chapter):
            raise RequestError(400, "chapter is not a Looma chapter id")
        if chapter not in self.chapters:
            raise RequestError(404, "unknown chapter")
        return chapter

    def _filters(self, mode: str, chapter: str | None, types: frozenset[str],
                 params: Mapping[str, list[str]]) -> Filters:
        cehrd = self.policy.cehrd_server
        if "grade" in params and mode != "library":
            raise RequestError(400, "grade comes from the chapter in chapter and related modes")
        if mode == "library":
            grade = _whole_number(params, "grade", None, 1, 12)
            return Filters(types=types, grade=grade, include_unknown_grade=True, cehrd_server=cehrd)
        if mode == "chapter":
            return Filters(types=types, chapter_id=chapter, cehrd_server=cehrd)
        code = CHAPTER_ID_RE.fullmatch(chapter).group(2)
        return Filters(types=types, subjects=frozenset(CHAPTER_SUBJECTS.get(code, ())), grade=chapter_grade(chapter),
                       grade_window=self.policy.grade_window, include_unknown_grade=False, cehrd_server=cehrd)

    def _run(self, query: str, filters: Filters, k: int, spelling: bool) -> tuple[list[Hit], SpellCheck, float]:
        with self._lock:
            hits, check, ms = self.engine.timed_respond(query, filters, k, spelling=spelling)
        cutoff = self.policy.min_similarity
        if cutoff is not None:
            hits = [hit for hit in hits if hit.similarity >= cutoff]  # no result beats a confident wrong one
        return hits, check, ms


def _single(params: Mapping[str, list[str]], name: str, default: Any) -> Any:
    values = params.get(name)
    if not values:
        return default
    if len(values) > 1:
        raise RequestError(400, f"{name} given more than once")
    return values[0]


def _whole_number(params: Mapping[str, list[str]], name: str, default: int | None, low: int, high: int) -> int | None:
    value = _single(params, name, None)
    if value is None:
        return default
    if not value.strip().isdigit() or not low <= int(value) <= high:
        raise RequestError(400, f"{name} must be a whole number from {low} to {high}")
    return int(value)


def _result(hit: Hit) -> dict:
    similarity = float(hit.similarity)
    return {"id": hit.item_id, "ft": hit.ft, "title": hit.title, "score": round(float(hit.score), 6),
            "similarity": round(similarity, 4) if math.isfinite(similarity) else None, "page": hit.page,
            "passage": hit.passage[:PASSAGE_CHARS]}


def _spelling(check: SpellCheck) -> dict | None:
    if not check.changes:
        return None
    return {"searched_for": check.corrected,
            "changes": [{"from": change.original, "to": change.replacement} for change in check.changes]}


def make_app(service: SearchService) -> Callable[[dict, Callable], Iterable[bytes]]:
    """The WSGI application. Every response is JSON; errors never include internal details."""

    def app(environ: dict, start_response: Callable) -> Iterable[bytes]:
        started = time.perf_counter()
        method, path = environ.get("REQUEST_METHOD", "GET"), environ.get("PATH_INFO") or "/"
        query_string = environ.get("QUERY_STRING", "")
        extra_headers: list[tuple[str, str]] = []
        query_chars = 0
        try:
            if path not in ("/health", "/search"):
                raise RequestError(404, "not found")
            if method != "GET":
                extra_headers.append(("Allow", "GET"))
                raise RequestError(405, "method not allowed")
            if len(query_string) > MAX_QUERY_STRING:
                raise RequestError(414, "query string too long")
            if path == "/health":
                status, body = 200, service.health()
            else:
                try:
                    params = parse_qs(query_string, keep_blank_values=True, max_num_fields=MAX_FIELDS)
                except ValueError as exc:
                    raise RequestError(400, "too many parameters") from exc
                query_chars = len(params.get("q", [""])[0])
                status, body = 200, service.search(params)
        except RequestError as error:
            status, body = error.status, {"error": error.message}
        except Exception as exc:  # the log gets the error type and place, not its text, which may hold the query
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            log.error("search failed", extra={"error_type": type(exc).__name__,
                                              "where": f"{Path(frame.filename).name}:{frame.lineno}"})
            status, body = 500, {"error": "internal error"}
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        start_response(f"{status} {REASONS[status]}", [
            ("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload))),
            ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"), *extra_headers])
        log.info("request", extra={"method": method, "path": path, "status": status, "query_chars": query_chars,
                                   "ms": round((time.perf_counter() - started) * 1000, 1)})
        return [payload]

    return app


def load_service(bundle_dir: Path, settings: Settings, policy: Policy, embedder: Any = None) -> SearchService:
    """Verify the bundle, then load it. Signature, checksums and the expected model are checked before the model
    file is opened; the self-test then runs with the loaded model. Anything that fails raises BundleRefused."""
    from looma_pipeline.bundle import MANIFEST_FILE
    from looma_pipeline.verify import bundle_embedder, run_self_test, verify

    checked = verify(bundle_dir, settings, with_self_test=False)
    if not checked.ok:
        failed = next(name for name, passed, _ in checked.checks if not passed)
        raise BundleRefused(f"bundle refused at '{failed}'")
    manifest = json.loads((bundle_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    embedder = embedder or bundle_embedder(bundle_dir, manifest, settings)
    passed, total = run_self_test(bundle_dir, embedder)
    if passed < total:
        raise BundleRefused(f"bundle refused at 'self-test' ({passed}/{total})")
    return SearchService(SearchEngine(bundle_dir, embedder), manifest, policy)


def serve(service: SearchService, listen: Listen) -> None:
    """Serve until stopped (Ctrl+C or SIGTERM). Blocks."""
    from waitress import serve as waitress_serve  # imported here: build-plane commands never need it

    log.info("serving", extra={"bundle": service.manifest.get("bundle_name"), "host": listen.host,
                               "port": listen.port, "threads": listen.threads})
    waitress_serve(make_app(service), host=listen.host, port=listen.port, threads=listen.threads,
                   ident="looma-search", channel_timeout=30, connection_limit=100,
                   max_request_header_size=8192, max_request_body_size=1024, clear_untrusted_proxy_headers=True)

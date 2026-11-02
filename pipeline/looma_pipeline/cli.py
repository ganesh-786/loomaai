"""Command-line interface: `python -m looma_pipeline <command>`.

Commands:
    info           print the effective settings (no secrets)
    prepare-model  download the pinned embedder and write its int8 model (network, once)
    keygen         create the bundle signing key pair in data/keys/ if there is none
    build          run F1-F13 for a scope: reads MongoDB read only, writes data/runs/<run_id>/ and a signed bundle
    verify         check a bundle: signature, checksums, model, content hash, self-test queries
    search         query a bundle with the reference search (spelling correction on unless --no-spelling)
    e2e            build twice, verify, try tampered copies and decide gates G1-G10
    eval-typos     measure typo tolerance on a bundle and decide gates T1, T2, T3 and T5
    clean          list old bundles and run folders that can go; deletes them only with --apply
    serve          verify a bundle, then answer searches over HTTP (the looma-search service; blocks)

Settings come from environment variables (docs/configuration.md). Exit codes: 0 success, 1 a check or gate
failed, 2 configuration or input error (including a refused bundle), 130 stopped with Ctrl+C, 143 stopped with
SIGTERM (`docker stop`). `serve` exits with 0 when Ctrl+C or SIGTERM stops it: that is its normal stop.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys

from looma_pipeline import __version__
from looma_pipeline.bundle import MANIFEST_FILE, ensure_keys
from looma_pipeline.config import SCOPES, ConfigError, Settings
from looma_pipeline.embedder import prepare_model
from looma_pipeline.logs import setup_logging
from looma_pipeline.pipeline import STAGES, run_build
from looma_pipeline.search import Filters, SearchEngine
from looma_pipeline.stages.f12_checks import ChecksFailed
from looma_pipeline.verify import bundle_embedder, resolve_bundle, verify

log = logging.getLogger(__name__)


def _print(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _cmd_info(settings: Settings, _args: argparse.Namespace) -> int:
    _print({"version": __version__, **settings.public_view()})
    return 0


def _cmd_prepare_model(settings: Settings, _args: argparse.Namespace) -> int:
    info = prepare_model(settings)
    _print({"model_dir": str(settings.model_dir), "model_key": info.key, "files": info.files})
    return 0


def _cmd_keygen(settings: Settings, _args: argparse.Namespace) -> int:
    key_id = ensure_keys(settings.signing_key_path, settings.signing_pubkey_path)
    _print({"key_id": key_id, "public_key": str(settings.signing_pubkey_path)})
    return 0


def _cmd_build(settings: Settings, args: argparse.Namespace) -> int:
    try:
        result = run_build(settings, args.scope, until=args.until)
    except ChecksFailed as exc:
        log.error("checks failed: no bundle written", extra={"error": str(exc)})
        return 1
    bundle = result.outputs.get("bundle")
    _print({"run_id": result.run_id, "run_dir": str(result.run_dir), "seconds": result.seconds,
            "bundle": str(bundle) if bundle else None})
    return 0


def _cmd_verify(settings: Settings, args: argparse.Namespace) -> int:
    bundle = resolve_bundle(settings, args.bundle)
    result = verify(bundle, settings, with_self_test=not args.no_self_test)
    _print({"bundle": str(bundle), **result.as_dict()})
    return 0 if result.ok else 1


def _cmd_search(settings: Settings, args: argparse.Namespace) -> int:
    bundle = resolve_bundle(settings, args.bundle)
    manifest = json.loads((bundle / MANIFEST_FILE).read_text(encoding="utf-8"))
    engine = SearchEngine(bundle, bundle_embedder(bundle, manifest, settings))
    try:
        filters = Filters(types=frozenset(args.type or ()), grade=args.grade, chapter_id=args.chapter,
                          cehrd_server=settings.is_cehrd_server)
        hits, spelling, ms = engine.timed_respond(args.query, filters, args.k, spelling=not args.no_spelling)
    finally:
        engine.close()
    output: dict = {"query": args.query, "ms": round(ms, 1)}
    if spelling.changes:
        output["spelling"] = {"searched_for": spelling.corrected,
                              "changes": [{"from": c.original, "to": c.replacement} for c in spelling.changes]}
    output["hits"] = [{"item_id": h.item_id, "title": h.title, "ft": h.ft, "score": h.score,
                       "similarity": h.similarity, "page": h.page, "passage": h.passage[:160]} for h in hits]
    _print(output)
    return 0


def _cmd_serve(settings: Settings, args: argparse.Namespace) -> int:
    from looma_pipeline import service

    return service.run(args.bundle, settings, os.environ)


def _cmd_clean(settings: Settings, args: argparse.Namespace) -> int:
    from looma_pipeline.retention import plan, remove

    planned = plan(settings, args.keep)
    for removal in planned.removals:
        print(f"{'delete' if args.apply else 'would delete'}  {removal.path.relative_to(settings.data_dir)}"
              f"  ({removal.reason})")
    print(f"keep {len(planned.kept)} folders; {len(planned.removals)} can go, freeing "
          f"{planned.freed_bytes / 1e6:,.0f} MB" + ("" if args.apply else ". Dry run: nothing deleted (add --apply)."))
    if args.apply:
        print(f"deleted {remove(planned)} folders")
    return 0


def _cmd_eval_typos(settings: Settings, args: argparse.Namespace) -> int:
    from looma_pipeline.eval_typos import markdown, run_typo_eval, write_report

    bundle = resolve_bundle(settings, args.bundle)
    manifest = json.loads((bundle / MANIFEST_FILE).read_text(encoding="utf-8"))
    engine = SearchEngine(bundle, bundle_embedder(bundle, manifest, settings))
    try:
        if not engine.speller.available:
            log.error("this bundle has no spelling tables", extra={"schema_version": manifest.get("schema_version")})
            return 2
        report = run_typo_eval(settings, engine, bundle.name)
    finally:
        engine.close()
    folder = write_report(settings, report)
    print(markdown(report))
    print(f"full report: {folder}/report.json")
    return 0 if report["all_gates_pass"] else 1


def _cmd_e2e(settings: Settings, args: argparse.Namespace) -> int:
    from looma_pipeline.e2e import markdown, run_e2e  # imported here: it pulls in the test runner

    try:
        report = run_e2e(settings, args.scope)
    except ChecksFailed as exc:
        log.error("a build failed its checks", extra={"error": str(exc)})
        return 1
    print(markdown(report))
    print(f"full report: {report['work_dir']}/e2e-report.json")
    return 0 if report["all_gates_pass"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="looma_pipeline", description="Build-plane pipeline F1-F13 for Looma AI.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("info", help="print the effective settings").set_defaults(handler=_cmd_info)
    commands.add_parser("prepare-model", help="download the pinned embedder and write the int8 model"
                        ).set_defaults(handler=_cmd_prepare_model)
    commands.add_parser("keygen", help="create the signing key pair if missing").set_defaults(handler=_cmd_keygen)

    build = commands.add_parser("build", help="run the build stages for a scope")
    build.add_argument("--scope", choices=SCOPES, default="pilot")
    build.add_argument("--until", choices=STAGES, help="stop after this stage (default: run all)")
    build.set_defaults(handler=_cmd_build)

    check = commands.add_parser("verify", help="verify a signed bundle")
    check.add_argument("bundle", help="bundle name in data/bundles/ or a path")
    check.add_argument("--no-self-test", action="store_true", help="skip loading the model and the self-test")
    check.set_defaults(handler=_cmd_verify)

    search = commands.add_parser("search", help="search a bundle")
    search.add_argument("bundle", help="bundle name in data/bundles/ or a path")
    search.add_argument("query")
    search.add_argument("--k", type=int, default=10)
    search.add_argument("--grade", type=int)
    search.add_argument("--chapter", help="restrict to one chapter id, e.g. 6S01.02")
    search.add_argument("--type", action="append", help="restrict to a file type (repeatable)")
    search.add_argument("--no-spelling", action="store_true", help="search exactly as typed")
    search.set_defaults(handler=_cmd_search)

    serve = commands.add_parser("serve", help="verify a bundle, then answer searches over HTTP (looma-search)")
    serve.add_argument("bundle", help="bundle name in data/bundles/ or a path")
    serve.set_defaults(handler=_cmd_serve)

    e2e = commands.add_parser("e2e", help="end-to-end check of gates G1-G10")
    e2e.add_argument("--scope", choices=SCOPES, default="pilot")
    e2e.set_defaults(handler=_cmd_e2e)

    typos = commands.add_parser("eval-typos", help="measure typo tolerance on a bundle")
    typos.add_argument("bundle", help="bundle name in data/bundles/ or a path")
    typos.set_defaults(handler=_cmd_eval_typos)

    clean = commands.add_parser("clean", help="list (and with --apply delete) old bundles and run folders")
    clean.add_argument("--keep", type=int, default=2, help="newest bundles and runs to keep of each kind")
    clean.add_argument("--apply", action="store_true", help="delete; without it nothing is deleted")
    clean.set_defaults(handler=_cmd_clean)
    return parser


def stop_on_sigterm(signum: int, _frame: object) -> None:
    """Turn SIGTERM into SystemExit so the running stage writes an `interrupted` report. In a container this
    process is PID 1, and PID 1 ignores SIGTERM unless a handler is installed."""
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level)
    signal.signal(signal.SIGTERM, stop_on_sigterm)
    try:
        return args.handler(Settings.from_env(), args)
    except ConfigError as exc:
        log.error("configuration error", extra={"error": str(exc)})
        return 2
    except FileNotFoundError as exc:
        log.error("file not found", extra={"error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())

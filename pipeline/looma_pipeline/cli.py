"""Command-line interface: `python -m looma_pipeline <command>`.

Commands:
    info           print the effective settings (no secrets)
    build          run the stages for a scope (reads MongoDB read only; writes data/runs/<run_id>/)
    prepare-model  download the pinned embedder and write its int8 model (network, once)

Each command reads settings from environment variables (docs/configuration.md) and exits non-zero on failure.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from looma_pipeline import __version__
from looma_pipeline.config import SCOPES, ConfigError, Settings
from looma_pipeline.embedder import prepare_model
from looma_pipeline.logs import setup_logging
from looma_pipeline.pipeline import STAGES, run_build

log = logging.getLogger(__name__)


def _cmd_info(settings: Settings, _args: argparse.Namespace) -> int:
    print(json.dumps({"version": __version__, **settings.public_view()}, indent=2))
    return 0


def _cmd_build(settings: Settings, args: argparse.Namespace) -> int:
    try:
        result = run_build(settings, args.scope, until=args.until)
    except ConfigError as exc:
        log.error("cannot build", extra={"error": str(exc)})
        return 2
    print(json.dumps({"run_id": result.run_id, "run_dir": str(result.run_dir), "seconds": result.seconds}))
    return 0


def _cmd_prepare_model(settings: Settings, _args: argparse.Namespace) -> int:
    info = prepare_model(settings)
    print(json.dumps({"model_dir": str(settings.model_dir), "model_key": info.key, "files": info.files}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="looma_pipeline", description="Build-plane pipeline F1-F13 for Looma AI.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("info", help="print the effective settings").set_defaults(handler=_cmd_info)
    build = commands.add_parser("build", help="run the build stages for a scope")
    build.add_argument("--scope", choices=SCOPES, default="pilot")
    build.add_argument("--until", choices=STAGES, help="stop after this stage (default: run all)")
    build.set_defaults(handler=_cmd_build)
    commands.add_parser("prepare-model", help="download the pinned embedder and write the int8 model"
                        ).set_defaults(handler=_cmd_prepare_model)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level)
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        log.error("invalid configuration", extra={"error": str(exc)})
        return 2
    return args.handler(settings, args)


if __name__ == "__main__":
    sys.exit(main())

"""Command-line interface: `python -m looma_pipeline <command>`.

Commands:
    info    print the effective settings (no secrets)

Each command reads settings from environment variables (docs/configuration.md) and exits non-zero on failure.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from looma_pipeline import __version__
from looma_pipeline.config import ConfigError, Settings
from looma_pipeline.logs import setup_logging

log = logging.getLogger(__name__)


def _cmd_info(settings: Settings, _args: argparse.Namespace) -> int:
    print(json.dumps({"version": __version__, **settings.public_view()}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="looma_pipeline", description="Build-plane pipeline F1-F13 for Looma AI.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("info", help="print the effective settings").set_defaults(handler=_cmd_info)
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

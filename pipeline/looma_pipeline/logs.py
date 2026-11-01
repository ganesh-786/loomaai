"""JSON-lines logging for pipeline runs.

Import only. `setup_logging()` sends one JSON object per line to stderr and, during a run, to `run.log` in the run
folder, so a run can be read by a person and parsed by a tool.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_RESERVED = set(vars(logging.makeLogRecord({})))


class JsonFormatter(logging.Formatter):
    """Formats a record as one JSON object: time, level, logger, message and any `extra=` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


RUN_LOG_LEVEL = logging.INFO  # run.log always keeps info and above, whatever the console shows


def _allow(level: int) -> None:
    """Make sure the root logger passes records of `level` on to its handlers."""
    root = logging.getLogger()
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)


def setup_logging(level: str = "INFO") -> None:
    """Send JSON log lines at `level` and above to stderr. Safe to call more than once."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_looma_stderr", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.setLevel(level)
    handler._looma_stderr = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    _allow(min(logging.getLevelName(level), RUN_LOG_LEVEL))


def add_file_log(path: Path) -> logging.Handler:
    """Also write JSON log lines (info and above) to `path`, the run's `run.log`.

    Returns the handler so the caller can remove it when the run ends.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    handler.setLevel(RUN_LOG_LEVEL)
    logging.getLogger().addHandler(handler)
    _allow(RUN_LOG_LEVEL)
    return handler

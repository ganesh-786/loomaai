"""Run folders and stage reports.

Import only. Each build gets a run id and a folder `data/runs/<run_id>/`. Every stage runs inside
`RunContext.stage()`, which times it and writes `<stage>.json` with its status, counts and details, also when the
stage fails or is interrupted (Ctrl+C, `docker stop`). Side effects: creates the run folder and writes JSON and
JSONL files in it.
"""

from __future__ import annotations

import json
import logging
import resource
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from looma_pipeline.config import Settings

log = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def peak_rss_mb() -> float:
    """This process's peak resident memory so far, in MiB (Linux reports ru_maxrss in KiB)."""
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def new_run_id(scope: str) -> str:
    """A sortable, unique run id such as `20261101T101500Z-pilot-3f9a`."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{scope}-{secrets.token_hex(2)}"


@dataclass
class StageReport:
    """What a stage did. Stages fill `counts` and `details`; the context fills the rest."""

    stage: str
    counts: dict[str, int] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def count(self, key: str, by: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + by


@dataclass
class RunContext:
    """One build run: its id, scope, settings and folder."""

    run_id: str
    scope: str
    settings: Settings
    run_dir: Path
    stage_seconds: dict[str, float] = field(default_factory=dict)

    @classmethod
    def create(cls, settings: Settings, scope: str, run_id: str | None = None) -> "RunContext":
        run_id = run_id or new_run_id(scope)
        run_dir = settings.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        ctx = cls(run_id=run_id, scope=scope, settings=settings, run_dir=run_dir)
        ctx.write_json("run.json", {"run_id": run_id, "scope": scope, "started_at": utc_now(),
                                     "settings": settings.public_view()})
        return ctx

    @property
    def staging_dir(self) -> Path:
        """Where F7 and F8 assemble the bundle before F12 checks it and F13 signs it."""
        return self.run_dir / "staging"

    @contextmanager
    def stage(self, name: str) -> Iterator[StageReport]:
        """Run one stage: time it and always write `<name>.json`, with status `ok`, `failed` or `interrupted`."""
        report = StageReport(stage=name)
        started = time.perf_counter()
        started_at = utc_now()
        log.info("stage started", extra={"stage": name, "run_id": self.run_id})
        status, error = "ok", None
        try:
            yield report
        except (KeyboardInterrupt, SystemExit) as exc:
            # Not Exception subclasses: without this, a stopped stage would be reported as "ok".
            status, error = "interrupted", type(exc).__name__
            raise
        except Exception as exc:
            status, error = "failed", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            seconds = round(time.perf_counter() - started, 3)
            self.stage_seconds[name] = seconds
            self.write_json(f"{name}.json", {
                "stage": name, "status": status, "error": error, "run_id": self.run_id,
                "started_at": started_at, "finished_at": utc_now(), "seconds": seconds,
                "peak_rss_mb": peak_rss_mb(), "counts": report.counts, "details": report.details,
            })
            log.info("stage finished", extra={"stage": name, "status": status, "seconds": seconds,
                                              "peak_rss_mb": peak_rss_mb(), "counts": report.counts})

    def write_json(self, name: str, data: Any) -> Path:
        path = self.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        return path

    def write_jsonl(self, name: str, rows: Iterable[Any]) -> Path:
        path = self.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        return path

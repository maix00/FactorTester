"""Standalone dispatcher loop: outbox -> RabbitMQ.

Run this next to the Manager, not inside a Celery worker.  It refuses to claim
rows unless this deployment has a complete Nautilus Job executor, so a missing
worker image cannot silently lose messages.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

import settings as Settings

from .celery_app import resolve_executor
from .dispatcher import DispatchRunner, publisher_from_env
from .outbox import DispatchOutbox

LOGGER = logging.getLogger("factortester.job-dispatcher")
DB_ENV = "FACTORTESTER_JOB_DB"
INTERVAL_ENV = "FACTORTESTER_DISPATCH_INTERVAL"


def build_runner() -> DispatchRunner:
    db_path = Path(os.environ.get(DB_ENV, "") or Settings.CACHE_DB_PATH)
    outbox = DispatchOutbox(db_path)
    outbox.ensure_schema()
    from server.jobs.repository.sqlite import JobRepository

    JobRepository(db_path).recover_expired_leases()
    return DispatchRunner(
        outbox,
        publisher_from_env(),
        preflight=resolve_executor,
    )


def run_forever(*, interval: float | None = None) -> None:
    seconds = float(
        interval if interval is not None
        else os.environ.get(INTERVAL_ENV, "1.0")
    )
    if seconds <= 0:
        raise ValueError("dispatch interval must be > 0")
    runner = build_runner()
    LOGGER.info("job dispatcher started interval=%.2fs", seconds)
    while True:
        result = runner.run_once(limit=10)
        if result["claimed"]:
            LOGGER.info("job dispatch %s", result)
        time.sleep(seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    if args.once:
        print(build_runner().run_once(limit=10))
        return 0
    run_forever(interval=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

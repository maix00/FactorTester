"""Operator CLI for the Job dispatch outbox (no broker connection)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import settings as Settings

from .outbox import DispatchOutbox

DB_ENV = "FACTORTESTER_JOB_DB"


def _outbox() -> DispatchOutbox:
    path = Path(os.environ.get(DB_ENV, "") or Settings.CACHE_DB_PATH)
    return DispatchOutbox(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    show = sub.add_parser("show")
    show.add_argument("job_id")
    show.add_argument("attempt", type=int)
    retry = sub.add_parser("retry")
    retry.add_argument("job_id")
    retry.add_argument("attempt", type=int)
    args = parser.parse_args(argv)
    outbox = _outbox()
    if args.command == "status":
        print(json.dumps(outbox.counts(), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "show":
        record = outbox.get((args.job_id, args.attempt))
        if record is None:
            print("not found")
            return 1
        print(json.dumps({
            "job_id": record.job_id,
            "attempt": record.attempt,
            "deployment_id": record.deployment_id,
            "service_port": record.message.service_port,
            "status": record.status,
            "attempts": record.attempts,
        }, ensure_ascii=False, sort_keys=True))
        return 0
    outbox.requeue((args.job_id, args.attempt))
    print("requeued")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Private CLI for exact Graph v1-v3 history recovery."""

from __future__ import annotations

import argparse
from pathlib import Path

import orjson

import settings as Settings
from server.services.research_graph.history_recovery import (
    inspect_history_recovery,
    recover_history,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recover exact canonical factor-research Graph v1-v3",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(Settings.CACHE_DB_PATH),
        help="target SQLite database",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print the immutable recovery plan (default)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="backup and atomically apply the recovery",
    )
    parser.add_argument(
        "--backup",
        type=Path,
        help="new SQLite backup path; required with --apply",
    )
    parser.add_argument(
        "--expected-plan-hash",
        default="",
        help="reject apply if the reviewed dry-run plan changed",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply:
        if args.backup is None:
            raise SystemExit("--backup is required with --apply")
        if not args.expected_plan_hash:
            raise SystemExit(
                "--expected-plan-hash is required with --apply"
            )
        result = recover_history(
            db_path=args.db,
            backup_path=args.backup,
            expected_plan_hash=args.expected_plan_hash,
        )
    else:
        result = inspect_history_recovery(db_path=args.db)
    print(orjson.dumps(result, option=orjson.OPT_SORT_KEYS).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Inspect or prune old Job control events from job-index.sqlite.

Dry-run is the default.  Deleting events is refused while a control-sync
cursor still points at or before the candidate range, unless the operator
explicitly opts in.
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--older-than-days", type=float, default=30)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ignore-cursors", action="store_true")
    parser.add_argument("--vacuum", action="store_true")
    args = parser.parse_args()

    cutoff = time.time() - args.older_than_days * 86400
    connection = sqlite3.connect(args.database)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        candidates = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(LENGTH(payload)), 0) "
            "FROM control_events WHERE created_at < ?",
            (cutoff,),
        ).fetchone()
        count, payload_bytes = int(candidates[0]), int(candidates[1])
        maximum = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM control_events WHERE created_at < ?",
            (cutoff,),
        ).fetchone()[0]
        cursors = connection.execute(
            "SELECT source_server_id, sequence FROM control_sync_cursors"
        ).fetchall()
        print(f"cutoff={cutoff:.0f} candidates={count} payload={payload_bytes / 1024 / 1024:.1f}MiB")
        if cursors:
            print("sync cursors:", ", ".join(f"{source}:{seq}" for source, seq in cursors))
        if not args.apply:
            print("dry-run; pass --apply to delete")
            return 0
        if count == 0:
            return 0
        blocking = [seq for _, seq in cursors if int(seq) < int(maximum)]
        if blocking and not args.ignore_cursors:
            print(f"refusing to delete: a sync cursor is behind sequence {maximum}")
            return 2
        deleted = 0
        while True:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT event_id FROM control_events WHERE created_at < ? LIMIT 5000",
                (cutoff,),
            ).fetchall()
            if not rows:
                connection.commit()
                break
            connection.executemany(
                "DELETE FROM control_events WHERE event_id=?",
                [(row[0],) for row in rows],
            )
            connection.commit()
            deleted += len(rows)
            print(f"deleted={deleted}", flush=True)
        if args.vacuum:
            connection.execute("VACUUM")
        print(f"done deleted={deleted}")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())

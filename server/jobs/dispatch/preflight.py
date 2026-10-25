"""Preflight checks for a dispatcher/worker deployment target."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from tools.data.sqlite.db import connect_sqlite

REQUIRED_ENV = ("FACTORTESTER_BROKER_URL", "FACTORTESTER_JOB_DB", "FACTORTESTER_DEPLOYMENT_ID", "FACTORTESTER_SERVICE_PORT")


def check_deployment(*, check_executor: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    broker = os.environ.get("FACTORTESTER_BROKER_URL", "").strip()
    if not broker:
        errors.append("FACTORTESTER_BROKER_URL is required")
    db_raw = os.environ.get("FACTORTESTER_JOB_DB", "").strip()
    db_path = Path(db_raw) if db_raw else None
    if db_path is None:
        errors.append("FACTORTESTER_JOB_DB is required")
    elif not db_path.parent.is_dir():
        errors.append(f"job DB directory does not exist: {db_path.parent}")
    elif not os.access(db_path.parent, os.W_OK):
        errors.append(f"job DB directory is not writable: {db_path.parent}")
    deployment = os.environ.get("FACTORTESTER_DEPLOYMENT_ID", "").strip()
    if not deployment:
        errors.append("FACTORTESTER_DEPLOYMENT_ID is required")
    raw_port = os.environ.get("FACTORTESTER_SERVICE_PORT", "").strip()
    try:
        port = int(raw_port)
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        port = 0
        errors.append("FACTORTESTER_SERVICE_PORT must be 1..65535")
    journal_mode = ""
    if db_path is not None and db_path.parent.is_dir() and os.access(db_path.parent, os.W_OK):
        try:
            with connect_sqlite(db_path) as conn:
                conn.execute("PRAGMA journal_mode = WAL")
                row = conn.execute("PRAGMA journal_mode").fetchone()
                journal_mode = str(row[0] if row is not None else "")
            if journal_mode.lower() != "wal":
                errors.append(f"job DB journal_mode is {journal_mode!r}, expected WAL")
        except sqlite3.Error as exc:
            errors.append(f"job DB cannot be opened: {exc}")
    executor = None
    if check_executor:
        try:
            from .celery_app import resolve_executor
            resolve_executor()
            executor = "available"
        except Exception as exc:
            errors.append(f"Nautilus executor unavailable: {type(exc).__name__}: {exc}")
            executor = "unavailable"
    return {
        "ok": not errors,
        "errors": errors,
        "target": {
            "deployment_id": deployment,
            "service_port": port,
            "queue": f"factortester.jobs.{deployment}.{port}" if deployment and port else "",
        },
        "job_db": str(db_path) if db_path else "",
        "journal_mode": journal_mode,
        "executor": executor,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check-executor", action="store_true")
    args = parser.parse_args(argv)
    report = check_deployment(check_executor=args.check_executor)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

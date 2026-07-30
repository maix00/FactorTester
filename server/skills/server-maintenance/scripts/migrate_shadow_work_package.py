#!/usr/bin/env python3
"""Plan or apply one exact split-shadow Work Package migration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from server.services.research_graph.shadow_work_package_migration import (
    apply_shadow_work_package_migration,
    plan_shadow_work_package_migration,
)
from tools.cli.release.research_shadow_migration import (
    finalize_local_shadow_migration,
    plan_local_shadow_migration,
    stage_local_shadow_migration,
)
from tools.cli.release.storage import read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    _identity_arguments(plan)
    plan.add_argument("--plan-out", type=Path, required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("--database", type=Path, required=True)
    apply.add_argument("--client-root", type=Path, required=True)
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--backup", type=Path, required=True)
    apply.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        value = _plan(args)
        write_json(args.plan_out, value)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    value = _apply(args)
    write_json(args.receipt, value)
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--client-root", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--source-work-package-id", required=True)
    parser.add_argument("--retained-instance-id", required=True)
    parser.add_argument("--retained-branch-id", required=True)
    parser.add_argument(
        "--retired-instance-id", action="append", required=True,
    )


def _plan(args: argparse.Namespace) -> dict:
    server = plan_shadow_work_package_migration(
        db_path=args.database,
        owner=args.owner,
        source_work_package_id=args.source_work_package_id,
        retained_instance_id=args.retained_instance_id,
        retired_instance_ids=args.retired_instance_id,
    )
    local = plan_local_shadow_migration(
        client_root=args.client_root,
        profile_id=args.profile_id,
        source_work_package_id=args.source_work_package_id,
        retained_instance_id=args.retained_instance_id,
        retained_branch_id=args.retained_branch_id,
        retired_instance_ids=args.retired_instance_id,
        server_plan_hash=server["plan_hash"],
    )
    return {"schema_version": 1, "server": server, "local": local}


def _apply(args: argparse.Namespace) -> dict:
    plan = read_json(args.plan)
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise ValueError("shadow migration plan is invalid")
    if args.backup.exists():
        raise ValueError("migration backup target already exists")
    _integrity(args.database)
    _backup(args.database, args.backup)
    local_stage = stage_local_shadow_migration(
        client_root=args.client_root,
        plan=plan["local"],
    )
    server = apply_shadow_work_package_migration(
        db_path=args.database,
        plan=plan["server"],
    )
    local = finalize_local_shadow_migration(
        client_root=args.client_root,
        plan=plan["local"],
        server_receipt=server,
    )
    _integrity(args.database)
    return {
        "schema_version": 1,
        "status": "applied",
        "server": server,
        "local_stage": local_stage,
        "local": local,
        "backup_integrity_check": "ok",
    }


def _backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    _integrity(target)


def _integrity(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        result = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    if result != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {path.name}")


if __name__ == "__main__":
    main()

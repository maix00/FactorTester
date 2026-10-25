#!/usr/bin/env python3
"""Export FactorTester accounts for Keycloak migration (no passwords)."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def export_accounts(db_path: str | Path) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT username, alias, role, is_admin, organization_name,"
                " parent_username FROM accounts ORDER BY username"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [
        {
            "username": row["username"],
            "alias": row["alias"] or "",
            "role": row["role"] or "user",
            "is_admin": bool(row["is_admin"]),
            "organization": row["organization_name"] or "",
            "parent_username": row["parent_username"] or "",
        }
        for row in rows
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    accounts = export_accounts(args.db)
    payload = {"accounts": accounts, "count": len(accounts)}
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.output:
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps({"count": len(accounts), "output": str(args.output or "")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Project legacy FactorTester roles into managed admin permissions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.permissions.entries import PermissionEntry


def entries_for_accounts(accounts: list[dict]) -> list[dict]:
    result = []
    for account in accounts:
        username = str(account.get("username") or "").strip()
        role = str(account.get("role") or "user").strip()
        if not username:
            continue
        if role == "super_admin" or account.get("is_admin"):
            actions = ("read", "manage")
        elif role in {"admin", "manager", "operator"}:
            actions = ("read", "manage")
        else:
            continue
        for action in actions:
            result.append({
                "subject": f"user:{username}",
                "resource_type": "admin_console",
                "resource_ref": "dispatch",
                "action": action,
                "scope": "explicit",
                "effect": "allow",
                "created_by": "__role_migration__",
                "reason": f"legacy role {role}",
            })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--permissions-db", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    accounts = json.loads(args.input.read_text()).get("accounts") or []
    entries = entries_for_accounts(accounts)
    if not args.dry_run:
        from server.permissions.entries import PermissionStore

        store = PermissionStore(args.permissions_db)
        for item in entries:
            store.add(PermissionEntry(
                subject=item["subject"], resource_type=item["resource_type"],
                resource_ref=item["resource_ref"], action=item["action"],
                scope=item["scope"], effect=item["effect"],
                created_by=item["created_by"], reason=item["reason"],
            ))
    print(json.dumps({"dry_run": args.dry_run, "entries": entries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

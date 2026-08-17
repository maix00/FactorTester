#!/usr/bin/env python3
"""Plan or apply the bounded public visitor account relationship.

The allowlist itself is a deployment setting.  This one-time data helper
only verifies that the named visitor is an ordinary user and makes that user
the recorded parent of the selected account.  It is a dry run by default.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.data.account_manage import load_accounts, save_accounts


def _one_account(accounts: list[dict[str, Any]], alias: str) -> dict[str, Any]:
    matches = [
        item for item in accounts
        if str(item.get("alias") or "") == str(alias or "")
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one account with alias {alias!r}, "
            f"found {len(matches)}"
        )
    return matches[0]


def plan_relationship(
    accounts: list[dict[str, Any]],
    *,
    visitor_alias: str = "testA",
    child_alias: str = "MaxJJW",
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Return updated rows and a non-secret summary without writing data."""
    rows = [dict(item) for item in accounts]
    visitor = _one_account(rows, visitor_alias)
    child = _one_account(rows, child_alias)
    role = str(visitor.get("role") or "user")
    if bool(visitor.get("is_admin")) or role != "user":
        raise ValueError("the visitor account must remain a non-admin user")
    visitor_username = str(visitor.get("username") or "").strip()
    child_username = str(child.get("username") or "").strip()
    if not visitor_username or not child_username:
        raise ValueError("both accounts must have canonical usernames")
    if visitor_username == child_username:
        raise ValueError("visitor and child accounts must be different")
    for row in rows:
        if str(row.get("username") or "") == child_username:
            row["parent_username"] = visitor_username
            break
    return rows, {
        "visitor_username": visitor_username,
        "child_username": child_username,
        "parent_username": visitor_username,
        "visitor_role": role,
    }


def _write_backup(path: Path, accounts: list[dict[str, Any]]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(accounts, ensure_ascii=False, sort_keys=True, indent=2)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(payload)
            output.write("\n")
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visitor-alias", default="testA")
    parser.add_argument("--child-alias", default="MaxJJW")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the relationship to the configured account authority",
    )
    parser.add_argument(
        "--backup-file",
        type=Path,
        help="new 0600 JSON backup required with --apply",
    )
    args = parser.parse_args()
    if args.apply and args.backup_file is None:
        parser.error("--apply requires --backup-file")
    accounts = [dict(item) for item in load_accounts()]
    updated, summary = plan_relationship(
        accounts,
        visitor_alias=args.visitor_alias,
        child_alias=args.child_alias,
    )
    changed = updated != accounts
    print(json.dumps({"changed": changed, **summary}, ensure_ascii=False))
    if not args.apply or not changed:
        return 0
    _write_backup(args.backup_file, accounts)
    save_accounts(updated)
    print(json.dumps({"applied": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

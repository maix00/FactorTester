"""Seed one public Manager's central visitor allowlist.

The command is intentionally explicit: it never guesses a server ID and it
does not print passwords, database URLs, or private credentials.
"""

from __future__ import annotations

import argparse
import json
import os

from server.manager.storage.control_db import control_store_from_env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-id", required=True)
    parser.add_argument("--username", action="append", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    store = control_store_from_env(os.environ)
    if store is None:
        raise SystemExit("FACTORTESTER_CONTROL_DATABASE_URL is required")
    existing = store.list_public_visitor_allowlist(
        server_id=args.server_id, include_disabled=True,
    )
    result = {
        "server_id": args.server_id,
        "requested_usernames": list(dict.fromkeys(args.username)),
        "existing_count": len(existing),
        "applied": [],
        "dry_run": not args.apply,
    }
    if args.apply:
        for username in result["requested_usernames"]:
            value = store.add_public_visitor_allowlist(
                server_id=args.server_id,
                username=username,
                created_by=args.actor,
            )
            result["applied"].append({
                "server_id": value.get("server_id"),
                "username": value.get("username"),
                "enabled": value.get("enabled"),
            })
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

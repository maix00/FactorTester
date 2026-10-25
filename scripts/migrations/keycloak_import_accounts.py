#!/usr/bin/env python3
"""Create Keycloak users from the password-free account export."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def import_accounts(accounts: list[dict], adapter, *, dry_run: bool) -> dict:
    created = []
    skipped = []
    for account in accounts:
        username = str(account.get("username") or "").strip()
        if not username:
            skipped.append({"username": "", "reason": "empty"})
            continue
        if dry_run:
            created.append(username)
            continue
        try:
            user_id = adapter.create_user(
                username=username,
                email=str(account.get("email") or ""),
                groups=tuple(account.get("groups") or ()),
                attributes={
                    "legacy_role": (str(account.get("role") or "user"),),
                    "legacy_username": (username,),
                },
            )
        except ValueError as exc:
            skipped.append({"username": username, "reason": str(exc)})
            continue
        created.append({"username": username, "id": user_id})
    return {"created": created, "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    accounts = json.loads(args.input.read_text()).get("accounts") or []
    adapter = None
    if not args.dry_run:
        from server.identity.keycloak import KeycloakAdminAdapter

        adapter = KeycloakAdminAdapter(
            os.environ["TRADERESEARCH_KEYCLOAK_URL"],
            os.environ["TRADERESEARCH_KEYCLOAK_REALM"],
            client_id=os.environ.get("TRADERESEARCH_KEYCLOAK_CLIENT_ID", "admin-cli"),
            client_secret=os.environ.get("TRADERESEARCH_KEYCLOAK_CLIENT_SECRET", ""),
        )
    print(json.dumps(import_accounts(accounts, adapter, dry_run=args.dry_run),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

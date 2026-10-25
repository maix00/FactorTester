#!/usr/bin/env python3
"""Backfill legacy_username/legacy_role on already-imported Keycloak users."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def backfill(accounts: list[dict], adapter) -> list[dict]:
    updated = []
    for account in accounts:
        username = str(account.get("username") or "")
        identity = adapter.user(username)
        if identity is None:
            continue
        adapter.set_user_attributes(
            _user_id(adapter, username),
            {"legacy_username": username, "legacy_role": str(account.get("role") or "user")},
        )
        updated.append(username)
    return updated


def _user_id(adapter, username: str) -> str:
    rows = adapter._get(f"users?username={username}&exact=true")
    if not rows:
        raise ValueError(f"user not found: {username}")
    return str(rows[0]["id"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    accounts = json.loads(args.input.read_text()).get("accounts") or []
    from server.identity.keycloak import KeycloakAdminAdapter

    adapter = KeycloakAdminAdapter(
        os.environ["TRADERESEARCH_KEYCLOAK_URL"],
        os.environ["TRADERESEARCH_KEYCLOAK_REALM"],
        client_id=os.environ.get("TRADERESEARCH_KEYCLOAK_CLIENT_ID", "admin-cli"),
        client_secret=os.environ.get("TRADERESEARCH_KEYCLOAK_CLIENT_SECRET", ""),
    )
    print(json.dumps({"updated": backfill(accounts, adapter)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

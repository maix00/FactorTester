#!/usr/bin/env python3
"""Compare legacy accounts with Keycloak users before login cutover."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def compare_accounts(accounts: list[dict], adapter) -> dict:
    report = {"matched": [], "missing": [], "case_folded": [], "role_mismatch": []}
    for account in accounts:
        username = str(account.get("username") or "")
        identity = adapter.user(username)
        if identity is None:
            report["missing"].append(username)
            continue
        legacy = (getattr(identity, "attributes", {}) or {}).get("legacy_username")
        legacy = legacy[0] if isinstance(legacy, (tuple, list)) else legacy
        if legacy != username:
            report["case_folded"].append({
                "legacy": username, "keycloak": identity.username,
                "legacy_username": legacy or "",
            })
        keycloak_role = ((getattr(identity, "attributes", {}) or {}).get("legacy_role") or [""])[0]
        if keycloak_role and keycloak_role != str(account.get("role") or ""):
            report["role_mismatch"].append({
                "legacy": username, "legacy_role": account.get("role"),
                "keycloak_role": keycloak_role,
            })
        report["matched"].append(username)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    accounts = json.loads(args.input.read_text()).get("accounts") or []
    if args.dry_run:
        print(json.dumps({"dry_run": True, "accounts": len(accounts)}, indent=2))
        return 0
    import os
    from server.identity.keycloak import KeycloakAdminAdapter

    adapter = KeycloakAdminAdapter(
        os.environ["TRADERESEARCH_KEYCLOAK_URL"],
        os.environ["TRADERESEARCH_KEYCLOAK_REALM"],
        client_id=os.environ.get("TRADERESEARCH_KEYCLOAK_CLIENT_ID", "admin-cli"),
        client_secret=os.environ.get("TRADERESEARCH_KEYCLOAK_CLIENT_SECRET", ""),
    )
    print(json.dumps(compare_accounts(accounts, adapter), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

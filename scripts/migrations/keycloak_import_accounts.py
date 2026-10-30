#!/usr/bin/env python3
"""Safely import a reviewed, password-free identity snapshot into Keycloak.

Planning is the default. Applying requires ``--apply`` and a snapshot whose
accounts have stable ``tr_identity_id`` values and an explicit organization.
Credentials are never copied. New users must establish a destination-local
credential through Keycloak's required UPDATE_PASSWORD action.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID


def _account_blockers(accounts: list[dict[str, Any]]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    usernames: dict[str, int] = {}
    identities: dict[str, int] = {}
    for index, account in enumerate(accounts):
        if not isinstance(account, dict):
            blockers.append({"row": str(index), "reason": "account_not_object"})
            continue
        username = str(account.get("username") or "").strip()
        identity_id = str(account.get("tr_identity_id") or "").strip()
        organization_id = str(account.get("organization_id") or "").strip()
        if not username:
            blockers.append({"row": str(index), "reason": "missing_username"})
        if not identity_id:
            blockers.append({"username": username, "reason": "missing_stable_identity"})
        else:
            try:
                if str(UUID(identity_id)) != identity_id.lower():
                    raise ValueError
            except (TypeError, ValueError, AttributeError):
                blockers.append({"username": username, "reason": "invalid_stable_identity"})
        if not organization_id:
            blockers.append({"username": username, "reason": "missing_organization"})
        if "active" in account and type(account["active"]) is not bool:
            blockers.append({"username": username, "reason": "invalid_active_flag"})
        if username:
            key = username.casefold()
            usernames[key] = usernames.get(key, 0) + 1
        if identity_id:
            identities[identity_id] = identities.get(identity_id, 0) + 1
    blockers.extend(
        {"reason": "duplicate_username", "count": str(count)}
        for count in usernames.values() if count > 1
    )
    blockers.extend(
        {"reason": "duplicate_stable_identity", "count": str(count)}
        for count in identities.values() if count > 1
    )
    return blockers


def _attributes_for(account: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    username = str(account["username"]).strip()
    fields = {
        "tr_identity_id": str(account["tr_identity_id"]).strip(),
        "legacy_username": username,
        "organization_id": str(account["organization_id"]).strip(),
        "organization_name": str(account.get("organization_name") or "").strip(),
        "parent_username": str(account.get("parent_username") or "").strip(),
    }
    level_id = str(account.get("level_id") or "").strip()
    if level_id:
        fields["organization_level_id"] = level_id
    return {key: (value,) for key, value in fields.items() if value}


def import_accounts(
    accounts: list[dict[str, Any]], adapter=None, *, dry_run: bool = True,
) -> dict[str, Any]:
    """Plan or idempotently apply accounts, refusing the entire batch on bad input."""
    blockers = _account_blockers(accounts)
    if blockers:
        return {
            "dry_run": dry_run,
            "status": "blocked",
            "planned": 0,
            "created": 0,
            "updated": 0,
            "blockers": blockers,
        }
    if not dry_run and adapter is None:
        raise ValueError("an authenticated Keycloak adapter is required to apply")

    planned = []
    created = []
    updated = []
    conflicts = []
    target_users: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for account in accounts:
        username = str(account["username"]).strip()
        identity_id = str(account["tr_identity_id"]).strip()
        plan_row = {"username": username, "tr_identity_id": identity_id}
        planned.append(plan_row)
        if dry_run:
            continue

        match = adapter.user_by_identity_id(identity_id)
        lookup = getattr(adapter, "user_representation", None)
        named_user = (
            lookup(username) if callable(lookup) else adapter.user(username)
        )
        if match is not None:
            existing_username = str(match.get("username") or "")
            user_id = str(match.get("id") or "")
            if (not user_id or existing_username.casefold() != username.casefold()
                    or (named_user is not None
                        and str(named_user.get("id") or "") != user_id)):
                conflicts.append({"username": username, "reason": "identity_username_conflict"})
        elif named_user is not None:
            # A same-name Keycloak account with another stable identity is a
            # conflict, never an implicit account-linking operation.
            conflicts.append({"username": username, "reason": "username_owned_by_other_identity"})
        target_users.append((account, match))

    # Complete the destination read-only conflict check before the first write.
    # This avoids a bad later row creating a partially migrated directory.
    if conflicts:
        return {
            "dry_run": False,
            "status": "blocked",
            "planned": len(planned),
            "created": 0,
            "updated": 0,
            "created_accounts": [],
            "updated_accounts": [],
            "conflicts": conflicts,
            "blockers": [],
        }

    for account, match in target_users:
        username = str(account["username"]).strip()
        identity_id = str(account["tr_identity_id"]).strip()
        enabled = account.get("active", True) is True
        plan_row = {"username": username, "tr_identity_id": identity_id}
        if match is not None:
            user_id = str(match["id"])
            adapter.update_migrated_user(
                user_id,
                username=username,
                email=str(account.get("email") or ""),
                attributes=_attributes_for(account),
                enabled=enabled,
            )
            updated.append(plan_row)
            continue
        user_id = adapter.create_user(
            username=username,
            email=str(account.get("email") or ""),
            groups=(),
            attributes=_attributes_for(account),
        )
        if not str(user_id or "").strip():
            raise RuntimeError("Keycloak did not return an identity for the created user")
        verified = adapter.user_by_identity_id(identity_id)
        if (not isinstance(verified, dict)
                or str(verified.get("id") or "") != str(user_id)
                or str(verified.get("username") or "").casefold() != username.casefold()):
            raise RuntimeError("Keycloak user creation did not verify by stable identity")
        created.append({**plan_row, "keycloak_user_id": str(user_id)})

    return {
        "dry_run": dry_run,
        "status": "blocked" if conflicts else "planned" if dry_run else "applied",
        "planned": len(planned),
        "created": len(created),
        "updated": len(updated),
        "created_accounts": created,
        "updated_accounts": updated,
        "conflicts": conflicts,
        "blockers": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--apply", action="store_true",
        help="Write to the configured Keycloak realm; default is a read-only plan.",
    )
    args = parser.parse_args(argv)
    source = json.loads(args.input.read_text(encoding="utf-8"))
    accounts = source.get("accounts") or []
    if not isinstance(accounts, list):
        parser.error("input accounts must be a JSON array")

    adapter = None
    if args.apply:
        required = (
            "TRADERESEARCH_KEYCLOAK_URL",
            "TRADERESEARCH_KEYCLOAK_REALM",
            "TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID",
        )
        missing = [key for key in required if not os.environ.get(key, "").strip()]
        secret_file = os.environ.get("TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET_FILE", "").strip()
        if not secret_file and not os.environ.get("TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET", "").strip():
            missing.append("TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET[_FILE]")
        if missing:
            parser.error("missing Keycloak apply configuration: " + ", ".join(missing))
        from server.identity.keycloak import KeycloakAdminAdapter

        secret = (
            Path(secret_file).read_text(encoding="utf-8").strip()
            if secret_file else os.environ["TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET"].strip()
        )
        adapter = KeycloakAdminAdapter(
            os.environ["TRADERESEARCH_KEYCLOAK_URL"].strip(),
            os.environ["TRADERESEARCH_KEYCLOAK_REALM"].strip(),
            client_id=os.environ["TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID"].strip(),
            client_secret=secret,
        )
    result = import_accounts(accounts, adapter, dry_run=not args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"planned", "applied"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

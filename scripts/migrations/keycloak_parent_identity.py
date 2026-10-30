"""Backfill reviewed Keycloak parent references using stable identity IDs.

This is a one-time migration of already imported accounts. It never creates
users, changes credentials or replaces an unexpected parent. The protected
receipt is written before the first mutation for an auditable retry/rollback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from scripts.migrations.keycloak_import_accounts import _account_blockers


def inspect(accounts: list[dict[str, Any]], adapter) -> dict[str, Any]:
    blockers = _account_blockers(accounts)
    if blockers:
        return {"status": "blocked", "blockers": blockers, "users": []}
    identities = {row["username"].strip().casefold(): row["tr_identity_id"].strip()
                  for row in accounts}
    users = []
    for account in accounts:
        legacy = account["username"].strip()
        identity = account["tr_identity_id"].strip()
        parent_name = str(account.get("parent_username") or "").strip()
        expected = identities.get(parent_name.casefold(), "") if parent_name else ""
        raw = adapter.user_by_identity_id(identity)
        if not isinstance(raw, dict) or not raw.get("id"):
            blockers.append({"username": legacy, "reason": "identity_missing_in_keycloak"})
            continue
        attrs = raw.get("attributes") or {}
        if (attrs.get("tr_identity_id") != [identity]
                or attrs.get("legacy_username") != [legacy]
                or (attrs.get("tr_parent_username") or []) != ([parent_name] if parent_name else [])):
            blockers.append({"username": legacy, "reason": "identity_or_legacy_parent_changed"})
            continue
        current = attrs.get("tr_parent_identity_id") or []
        if current not in ([], [expected] if expected else []):
            blockers.append({"username": legacy, "reason": "existing_parent_conflict"})
            continue
        users.append({"subject": str(raw["id"]), "identity": identity,
                      "legacy_username": legacy, "legacy_parent": parent_name,
                      "before": current, "after": [expected] if expected else []})
    return {"status": "blocked" if blockers else "planned", "blockers": blockers,
            "users": users}


def apply(reviewed: dict[str, Any], adapter, *, record) -> int:
    """Apply an already-recorded plan, rechecking each identity before write."""
    if reviewed.get("status") != "planned" or reviewed.get("blockers"):
        raise ValueError("blocked parent identity plan cannot be applied")
    changed = 0
    for item in reviewed["users"]:
        raw = adapter.user_by_identity_id(item["identity"])
        attrs = (raw or {}).get("attributes") or {}
        before = attrs.get("tr_parent_identity_id") or []
        if (not isinstance(raw, dict) or raw.get("id") != item["subject"]
                or attrs.get("tr_identity_id") != [item["identity"]]
                or attrs.get("legacy_username") != [item["legacy_username"]]
                or (attrs.get("tr_parent_username") or []) != ([item["legacy_parent"]] if item["legacy_parent"] else [])
                or before not in (item["before"], item["after"])):
            raise ValueError("Keycloak identity changed after parent review")
        if before != item["after"]:
            if not item["after"]:
                raise ValueError("removing an unexpected parent is not supported")
            adapter.set_user_attributes(item["subject"], {"tr_parent_identity_id": item["after"][0]})
            verified = adapter.user_by_identity_id(item["identity"])
            if (not isinstance(verified, dict) or verified.get("id") != item["subject"]
                    or (verified.get("attributes") or {}).get("tr_parent_identity_id") != item["after"]):
                raise RuntimeError("Keycloak parent update did not verify")
            changed += 1
            record(item["identity"])
    return changed


def main() -> None:
    import argparse
    from server.identity.federation_identity_sync import manager_keycloak_admin_adapter

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-directory", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    accounts = json.loads(Path(args.reviewed_directory).read_text())["accounts"]
    adapter = manager_keycloak_admin_adapter()
    reviewed = inspect(accounts, adapter)
    if reviewed["status"] != "planned":
        print(json.dumps({"status": "blocked", "blockers": len(reviewed["blockers"])}))
        raise SystemExit(2)
    if not args.apply:
        print(json.dumps({"status": "planned", "users": len(reviewed["users"]),
                          "changes": sum(item["before"] != item["after"] for item in reviewed["users"])}))
        return
    receipt = Path(args.receipt).expanduser()
    fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as journal:
        journal.write(json.dumps({"plan": reviewed}, sort_keys=True) + "\n")
        journal.flush()
        os.fsync(journal.fileno())

        def record(identity: str) -> None:
            journal.write(json.dumps({"verified_identity": identity}) + "\n")
            journal.flush()
            os.fsync(journal.fileno())

        changed = apply(reviewed, adapter, record=record)
    print(json.dumps({"status": "applied", "users": len(reviewed["users"]), "changed": changed}))


if __name__ == "__main__":
    main()

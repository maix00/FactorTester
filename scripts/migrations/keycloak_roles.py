#!/usr/bin/env python3
"""Plan or explicitly apply legacy account-role mappings in Keycloak.

The default command is an offline plan. Global roles are assigned only to
exact, existing Keycloak usernames. Scoped organization/level roles are
translated into a reviewable Realm Group + FGAP plan, but are never applied by
this command: group and fine-grained policy provisioning must be verified as a
separate cutover step before those privileges become effective.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

try:  # Support both `python -m scripts.migrations.keycloak_roles` and script use.
    from .keycloak_hierarchy import (
        GROUP_ROOT,
        complete_group_tree,
        hierarchy_group_paths,
        membership_group,
        scoped_admin_mapping,
    )
except ImportError:  # pragma: no cover - exercised by the direct CLI entrypoint
    from keycloak_hierarchy import (  # type: ignore[no-redef]
        GROUP_ROOT,
        complete_group_tree,
        hierarchy_group_paths,
        membership_group,
        scoped_admin_mapping,
    )


LEGACY_ROLE_TO_KEYCLOAK_ROLES = {
    "super_admin": ("admin_console:manage", "admin_console:read"),
    "developer": ("factor:develop",),
}
SCOPED_LEGACY_ROLES = frozenset({"org_admin", "level_admin"})


def role_mappings_for_accounts(
    accounts: list[dict], organizations: list[dict] | None = None,
    levels: list[dict] | None = None,
) -> dict[str, object]:
    """Return an auditable user, group, and role plan without making writes."""
    organizations = organizations or []
    levels = levels or []
    level_paths, hierarchy_errors = hierarchy_group_paths(organizations, levels)
    mappings: list[dict[str, Any]] = []
    scoped_mappings: list[dict[str, Any]] = []
    unsupported: dict[str, int] = {}
    scoped_blocked: dict[str, list[dict[str, str]]] = {}
    pending_authorization: list[dict[str, str]] = []
    invalid_admin_flags: list[str] = []
    invalid_developer_flags: list[str] = []
    unmapped_memberships: list[dict[str, str]] = []
    memberships: dict[str, set[str]] = {}
    skipped = 0

    for account in accounts:
        username = str(account.get("username") or "").strip()
        if not username:
            skipped += 1
            continue

        legacy_role = str(account.get("role") or "user").strip()
        if "is_admin" in account and type(account["is_admin"]) is not bool:
            invalid_admin_flags.append(username)
        elif account.get("is_admin") is True:
            # The old normalizer treats is_admin as a platform-wide override.
            legacy_role = "super_admin"

        developer_flag: bool | None = False
        if "is_developer" in account:
            if type(account["is_developer"]) is not bool:
                invalid_developer_flags.append(username)
                developer_flag = None
            else:
                developer_flag = account["is_developer"]

        mapped_roles = list(LEGACY_ROLE_TO_KEYCLOAK_ROLES.get(legacy_role, ()))
        if developer_flag is True and "factor:develop" not in mapped_roles:
            mapped_roles.append("factor:develop")

        if legacy_role in SCOPED_LEGACY_ROLES:
            scoped, error = scoped_admin_mapping(
                {**account, "username": username, "role": legacy_role},
                organizations, levels, level_paths,
            )
            if error:
                scoped_blocked.setdefault(legacy_role, []).append(error)
            elif scoped:
                scoped_mappings.append(scoped)
                pending_authorization.append({
                    "username": username,
                    "legacy_role": legacy_role,
                    "reason": "realm_group_fgap_policy_not_provisioned_or_verified",
                })
                memberships.setdefault(username, set()).add(
                    str(scoped["administrator_group"]),
                )
        elif not mapped_roles and legacy_role not in {"", "user"}:
            unsupported[legacy_role] = unsupported.get(legacy_role, 0) + 1

        if mapped_roles:
            mappings.append({
                "username": username,
                "legacy_role": legacy_role,
                "client_roles": sorted(set(mapped_roles)),
            })

        group_path = membership_group(account, level_paths)
        if group_path:
            memberships.setdefault(username, set()).add(group_path)
        else:
            unmapped_memberships.append({
                "username": username,
                "organization_id": str(account.get("organization_id") or ""),
                "level_id": str(account.get("level_id") or ""),
                "reason": "no_valid_level_group_path",
            })

    scoped_blocked = {
        role: sorted(values, key=lambda item: item["username"])
        for role, values in sorted(scoped_blocked.items())
    }
    membership_rows = [
        {"username": username, "group_paths": sorted(group_paths)}
        for username, group_paths in sorted(memberships.items())
    ]
    realm_group_paths = set(level_paths.values())
    for item in scoped_mappings:
        realm_group_paths.add(str(item["administrator_group"]))
        realm_group_paths.update(
            str(path) for path in item.get("assignable_administrator_groups", [])
        )

    return {
        "mappings": sorted(mappings, key=lambda item: str(item["username"])),
        "realm_group_plan": {
            "root": GROUP_ROOT,
            "paths": complete_group_tree(realm_group_paths),
            "level_paths": dict(sorted(level_paths.items())),
            "account_memberships": membership_rows,
        },
        "scoped_admin_mappings": sorted(
            scoped_mappings, key=lambda item: (str(item["legacy_role"]), str(item["username"])),
        ),
        "scoped_authorization_pending": sorted(
            pending_authorization, key=lambda item: item["username"],
        ),
        "unsupported_legacy_roles": dict(sorted(unsupported.items())),
        "scoped_legacy_roles_blocked": scoped_blocked,
        "hierarchy_errors": hierarchy_errors,
        "unmapped_account_group_memberships": sorted(
            unmapped_memberships, key=lambda item: item["username"],
        ),
        "invalid_admin_flags": sorted(invalid_admin_flags),
        "invalid_developer_flags": sorted(invalid_developer_flags),
        "skipped_empty_usernames": skipped,
    }


def _apply_blockers(plan: dict[str, object]) -> dict[str, object]:
    return {
        key: plan.get(key) or default
        for key, default in (
            ("unsupported_legacy_roles", {}),
            ("scoped_legacy_roles_blocked", {}),
            ("scoped_authorization_pending", []),
            ("hierarchy_errors", []),
            ("unmapped_account_group_memberships", []),
            ("invalid_admin_flags", []),
            ("invalid_developer_flags", []),
        )
        if plan.get(key)
    }


def apply_role_mappings(
    plan: dict[str, object], adapter, client_id: str,
) -> dict[str, object]:
    """Apply global role assignments only when the entire plan is unblocked."""
    blockers = _apply_blockers(plan)
    if blockers:
        return {"applied": [], "failures": [], "blocked": blockers}
    applied: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    for mapping in plan.get("mappings", []):
        username = str(mapping["username"])
        try:
            assigned = adapter.add_client_roles(
                username, client_id, tuple(mapping["client_roles"]),
            )
        except Exception as exc:
            failures.append({"username": username, "error": type(exc).__name__})
            continue
        applied.append({"username": username, "assigned_roles": assigned})
    return {"applied": applied, "failures": failures, "blocked": {}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--roles-client-id", default=(
        os.environ.get("TR_USER_OIDC_ROLES_CLIENT_ID")
        or os.environ.get("TRADERESEARCH_KEYCLOAK_ROLES_CLIENT_ID") or ""
    ))
    parser.add_argument("--apply", action="store_true",
                        help="Assign planned global client roles (otherwise dry-run).")
    args = parser.parse_args(argv)
    source = json.loads(args.input.read_text())
    plan = role_mappings_for_accounts(
        source.get("accounts") or [],
        source.get("organizations") or [],
        source.get("levels") or [],
    )
    result: dict[str, object] = {"dry_run": not args.apply, **plan}
    if args.apply:
        blockers = _apply_blockers(plan)
        if blockers:
            result["apply_blocked"] = blockers
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        if not args.roles_client_id:
            parser.error("--roles-client-id is required with --apply")
        required_env = (
            "TRADERESEARCH_KEYCLOAK_URL",
            "TRADERESEARCH_KEYCLOAK_REALM",
            "TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID",
            "TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET",
        )
        missing = [name for name in required_env if not os.environ.get(name, "").strip()]
        if missing:
            parser.error("missing Keycloak apply configuration: " + ", ".join(missing))
        from server.identity.keycloak import KeycloakAdminAdapter

        adapter = KeycloakAdminAdapter(
            os.environ["TRADERESEARCH_KEYCLOAK_URL"].strip(),
            os.environ["TRADERESEARCH_KEYCLOAK_REALM"].strip(),
            client_id=os.environ["TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID"].strip(),
            client_secret=os.environ["TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET"].strip(),
            timeout=5.0,
        )
        result.update(apply_role_mappings(plan, adapter, args.roles_client_id))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if args.apply and (result.get("failures") or result.get("blocked")) else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Compare two legacy Manager directory snapshots without printing identities.

Inputs may be `keycloak_accounts.py` exports or Manager
`/api/admin/account-directory` responses. The report contains row counts,
field-difference counts, and set-equality flags only; it never emits user,
organization, level, password, or credential values.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from .keycloak_hierarchy import hierarchy_group_paths
    from .keycloak_roles import role_mappings_for_accounts
except ImportError:  # pragma: no cover - direct script entrypoint
    from keycloak_hierarchy import hierarchy_group_paths  # type: ignore[no-redef]
    from keycloak_roles import role_mappings_for_accounts  # type: ignore[no-redef]


ACCOUNT_FIELDS = (
    "alias", "role", "is_admin", "is_developer", "active",
    "organization_id", "organization_name", "level_id", "parent_username",
)
ORGANIZATION_FIELDS = ("name", "description")
LEVEL_FIELDS = ("organization_id", "name", "parent_level_id", "manager_username")


def _rows(snapshot: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = snapshot.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _account(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": str(row.get("username") or "").strip(),
        "alias": str(row.get("alias") or ""),
        "role": str(row.get("role") or "user").strip(),
        "is_admin": row.get("is_admin"),
        "is_developer": row.get("is_developer"),
        # A missing legacy column has the same behavior as the old session
        # verifier: accounts are active unless explicitly deactivated.
        "active": row.get("active", True),
        "organization_id": str(row.get("organization_id") or "default").strip(),
        "organization_name": str(
            row.get("organization_name") or row.get("organization") or ""
        ),
        "level_id": str(row.get("level_id") or "").strip(),
        "parent_username": str(row.get("parent_username") or "").strip(),
    }


def _reference_rows(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("id") or "").strip()
        if key and key not in result:
            result[key] = {field: str(row.get(field) or "") for field in fields}
    return result


def _compare_users(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [[_account(row) for row in side] for side in (left, right)]
    indexes: list[dict[str, dict[str, Any]]] = []
    collisions = []
    for rows in normalized:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            username = row["username"]
            if username:
                buckets.setdefault(username.casefold(), []).append(row)
        collisions.append(sum(len(items) > 1 for items in buckets.values()))
        indexes.append({key: items[0] for key, items in buckets.items() if len(items) == 1})

    left_index, right_index = indexes
    left_keys, right_keys = set(left_index), set(right_index)
    shared = left_keys & right_keys
    changed = Counter()
    case_different = 0
    for key in shared:
        lrow, rrow = left_index[key], right_index[key]
        case_different += lrow["username"] != rrow["username"]
        for field in ACCOUNT_FIELDS:
            if lrow[field] != rrow[field]:
                changed[field] += 1
    empty_usernames = [
        sum(not row["username"] for row in side) for side in normalized
    ]
    exact_set_match = (
        collisions == [0, 0]
        and empty_usernames == [0, 0]
        and {row["username"] for row in normalized[0] if row["username"]}
        == {row["username"] for row in normalized[1] if row["username"]}
    )
    return {
        "left_count": len(left),
        "right_count": len(right),
        "casefold_matched_count": len(shared),
        "left_only_count": len(left_keys - right_keys),
        "right_only_count": len(right_keys - left_keys),
        "username_case_difference_count": case_different,
        "empty_username_rows": empty_usernames,
        "casefold_collision_groups": collisions,
        "exact_identity_set_match": exact_set_match,
        "account_field_differences": dict(sorted(changed.items())),
        "credential_material_exported": False,
    }


def _compare_references(
    left: list[dict[str, Any]], right: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    left_index = _reference_rows(left, fields)
    right_index = _reference_rows(right, fields)
    left_ids, right_ids = set(left_index), set(right_index)
    common = left_ids & right_ids
    changed = Counter()
    for identifier in common:
        for field in fields:
            if left_index[identifier][field] != right_index[identifier][field]:
                changed[field] += 1
    return {
        "left_count": len(left),
        "right_count": len(right),
        "shared_id_count": len(common),
        "left_only_count": len(left_ids - right_ids),
        "right_only_count": len(right_ids - left_ids),
        "duplicate_id_count": (len(left) - len(left_index)) + (len(right) - len(right_index)),
        "exact_id_set_match": left_ids == right_ids and len(left) == len(left_index)
        and len(right) == len(right_index),
        "field_differences": dict(sorted(changed.items())),
    }


def _integrity(snapshot: dict[str, Any]) -> dict[str, Any]:
    accounts = [_account(row) for row in _rows(snapshot, "users", "accounts")]
    organizations = _rows(snapshot, "organizations")
    levels = _rows(snapshot, "levels")
    organization_ids = {
        str(row.get("id") or "").strip()
        for row in organizations if str(row.get("id") or "").strip()
    }
    levels_by_id = {
        str(row.get("id") or "").strip(): row
        for row in levels if str(row.get("id") or "").strip()
    }
    _, hierarchy_errors = hierarchy_group_paths(organizations, levels)
    missing_organizations = 0
    missing_levels = 0
    level_organization_mismatches = 0
    for account in accounts:
        if not account["username"]:
            continue
        org_id = account["organization_id"]
        level_id = account["level_id"] or f"{org_id}__ROOT"
        if org_id not in organization_ids:
            missing_organizations += 1
            continue
        level = levels_by_id.get(level_id)
        if level is None:
            missing_levels += 1
        elif str(level.get("organization_id") or "").strip() != org_id:
            level_organization_mismatches += 1
    return {
        "empty_username_rows": sum(not row["username"] for row in accounts),
        "missing_account_organizations": missing_organizations,
        "missing_account_levels": missing_levels,
        "account_level_organization_mismatches": level_organization_mismatches,
        "invalid_hierarchy_rows": len(hierarchy_errors),
    }


def _role_readiness(snapshot: dict[str, Any]) -> dict[str, Any]:
    plan = role_mappings_for_accounts(
        _rows(snapshot, "users", "accounts"),
        _rows(snapshot, "organizations"),
        _rows(snapshot, "levels"),
    )
    scoped_blocked = sum(
        len(rows) for rows in (plan.get("scoped_legacy_roles_blocked") or {}).values()
    )
    unsupported = sum((plan.get("unsupported_legacy_roles") or {}).values())
    pending_scopes = len(plan.get("scoped_authorization_pending") or [])
    unmapped = len(plan.get("unmapped_account_group_memberships") or [])
    invalid_flags = len(plan.get("invalid_admin_flags") or []) + len(
        plan.get("invalid_developer_flags") or []
    )
    return {
        "unsupported_role_rows": unsupported,
        "invalid_scoped_admin_rows": scoped_blocked,
        "scoped_authorization_not_provisioned_rows": pending_scopes,
        "unmapped_group_memberships": unmapped,
        "invalid_legacy_flag_rows": invalid_flags,
        "source_plan_unblocked": not any((
            unsupported, scoped_blocked, pending_scopes, unmapped, invalid_flags,
        )),
    }


def compare_directories(left_snapshot: dict[str, Any], right_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a PII-free aggregate comparison suitable for cutover gates."""
    left_users = _rows(left_snapshot, "users", "accounts")
    right_users = _rows(right_snapshot, "users", "accounts")
    left_organizations = _rows(left_snapshot, "organizations")
    right_organizations = _rows(right_snapshot, "organizations")
    left_levels = _rows(left_snapshot, "levels")
    right_levels = _rows(right_snapshot, "levels")
    users = _compare_users(left_users, right_users)
    organizations = _compare_references(
            left_organizations, right_organizations, ORGANIZATION_FIELDS,
        )
    levels = _compare_references(left_levels, right_levels, LEVEL_FIELDS)
    left_integrity = _integrity(left_snapshot)
    right_integrity = _integrity(right_snapshot)
    left_roles = _role_readiness(left_snapshot)
    right_roles = _role_readiness(right_snapshot)
    return {
        "users": users,
        "organizations": organizations,
        "levels": levels,
        "directory_integrity": {"left": left_integrity, "right": right_integrity},
        "legacy_role_mapping_plan": {"left": left_roles, "right": right_roles},
        "legacy_directory_preflight_passes": bool(
            users["exact_identity_set_match"]
            and not users["account_field_differences"]
            and not users["username_case_difference_count"]
            and organizations["exact_id_set_match"]
            and not organizations["field_differences"]
            and levels["exact_id_set_match"]
            and not levels["field_differences"]
            and not any(left_integrity.values())
            and not any(right_integrity.values())
            and left_roles["source_plan_unblocked"]
            and right_roles["source_plan_unblocked"]
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    args = parser.parse_args(argv)
    left = json.loads(args.left.read_text())
    right = json.loads(args.right.read_text())
    if not isinstance(left, dict) or not isinstance(right, dict):
        parser.error("both snapshots must contain JSON objects")
    report = compare_directories(left, right)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["legacy_directory_preflight_passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

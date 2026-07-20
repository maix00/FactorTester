#!/usr/bin/env python3
"""One-time import of legacy user account data from data/users into SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.data_dir import DATA_DIR
from tools.data.account_manage import (
    load_accounts,
    load_levels,
    load_organizations,
    load_product_groups,
    save_accounts,
    save_levels,
    save_organizations,
)
from tools.data.account_manage import list_factor_param_config_scopes
from tools.data.sqlite.account_manager import (
    ensure_scope_exists,
    load_factor_param_config,
    save_factor_param_config_payload,
)
from tools.data.account_manage import save_product_groups


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _normalize_account_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "username": row.get("username"),
                "alias": row.get("alias"),
                "salt": row.get("salt"),
                "hash": row.get("hash"),
                "role": row.get("role"),
                "is_admin": bool(row.get("is_admin")),
                "organization_id": row.get("organization_id"),
                "organization_name": row.get("organization_name"),
                "level_id": row.get("level_id"),
                "parent_username": row.get("parent_username"),
            }
            for row in rows
            if isinstance(row, dict)
        ],
        key=lambda row: str(row.get("username") or ""),
    )


def _normalize_organization_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "description": row.get("description"),
            }
            for row in rows
            if isinstance(row, dict)
        ],
        key=lambda row: str(row.get("id") or ""),
    )


def _normalize_level_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "id": row.get("id"),
                "organization_id": row.get("organization_id"),
                "name": row.get("name"),
                "parent_level_id": row.get("parent_level_id"),
                "manager_username": row.get("manager_username"),
            }
            for row in rows
            if isinstance(row, dict)
        ],
        key=lambda row: (str(row.get("organization_id") or ""), str(row.get("id") or "")),
    )


def _import_product_groups(username: str, user_dir: str) -> int:
    path = os.path.join(user_dir, "product_groups.json")
    if not os.path.isfile(path):
        return 0
    payload = _load_json(path)
    if not isinstance(payload, list):
        return 0
    groups = [item for item in payload if isinstance(item, dict)]
    save_product_groups(username, groups)
    return len(groups)


def _iter_factor_param_configs(user_dir: str) -> list[tuple[str, str, dict[str, Any]]]:
    root = os.path.join(user_dir, "factor_library_param_configs")
    if not os.path.isdir(root):
        return []
    items: list[tuple[str, str, dict[str, Any]]] = []
    for entry in sorted(os.listdir(root)):
        entry_path = os.path.join(root, entry)
        if os.path.isdir(entry_path):
            scope_key = entry
            for filename in sorted(os.listdir(entry_path)):
                if not filename.endswith(".json"):
                    continue
                file_path = os.path.join(entry_path, filename)
                payload = _load_json(file_path)
                if isinstance(payload, dict):
                    items.append((scope_key, filename[:-5], payload))
            continue
        if entry.endswith(".json"):
            payload = _load_json(entry_path)
            if isinstance(payload, dict):
                items.append(("default", entry[:-5], payload))
    return items


def _import_factor_param_configs(username: str, user_dir: str) -> tuple[int, int]:
    items = _iter_factor_param_configs(user_dir)
    scopes = set()
    for scope_key, ff_alias, payload in items:
        ensure_scope_exists(username, scope_key)
        save_factor_param_config_payload(username, ff_alias, payload, scope_key)
        scopes.add(scope_key)
    return len(scopes), len(items)


def import_user_account_data_once(source_root: str | None = None) -> dict[str, Any]:
    root = os.path.abspath(os.path.expanduser(source_root or os.path.join(DATA_DIR, "users")))
    result = {
        "source_root": root,
        "accounts": 0,
        "organizations": 0,
        "levels": 0,
        "users": 0,
        "product_groups": 0,
        "param_scopes": 0,
        "param_configs": 0,
        "skipped": 0,
    }
    if not os.path.isdir(root):
        return result
    accounts_path = os.path.join(root, "accounts.json")
    if os.path.isfile(accounts_path):
        payload = _load_json(accounts_path)
        if isinstance(payload, list):
            rows = [item for item in payload if isinstance(item, dict)]
            save_accounts(rows)
            result["accounts"] = len(rows)
    organizations_path = os.path.join(root, "organizations.json")
    if os.path.isfile(organizations_path):
        payload = _load_json(organizations_path)
        if isinstance(payload, list):
            rows = [item for item in payload if isinstance(item, dict)]
            save_organizations(rows)
            result["organizations"] = len(rows)
    levels_path = os.path.join(root, "levels.json")
    if os.path.isfile(levels_path):
        payload = _load_json(levels_path)
        if isinstance(payload, list):
            rows = [item for item in payload if isinstance(item, dict)]
            save_levels(rows)
            result["levels"] = len(rows)
    for username in sorted(os.listdir(root)):
        if username.startswith(".") or username.startswith("_"):
            continue
        user_dir = os.path.join(root, username)
        if not os.path.isdir(user_dir):
            continue
        result["users"] += 1
        try:
            result["product_groups"] += _import_product_groups(username, user_dir)
            scope_count, config_count = _import_factor_param_configs(username, user_dir)
            result["param_scopes"] += scope_count
            result["param_configs"] += config_count
        except Exception:
            result["skipped"] += 1
    return result


def verify_user_account_data_import(source_root: str | None = None) -> dict[str, Any]:
    root = os.path.abspath(os.path.expanduser(source_root or os.path.join(DATA_DIR, "users")))
    mismatches: list[str] = []
    if not os.path.isdir(root):
        return {"source_root": root, "mismatches": ["source root missing"]}
    accounts_path = os.path.join(root, "accounts.json")
    if os.path.isfile(accounts_path):
        expected = [item for item in _load_json(accounts_path) if isinstance(item, dict)]
        if _normalize_account_rows(load_accounts()) != _normalize_account_rows(expected):
            mismatches.append("root:accounts")
    organizations_path = os.path.join(root, "organizations.json")
    if os.path.isfile(organizations_path):
        expected = [item for item in _load_json(organizations_path) if isinstance(item, dict)]
        if _normalize_organization_rows(load_organizations()) != _normalize_organization_rows(expected):
            mismatches.append("root:organizations")
    levels_path = os.path.join(root, "levels.json")
    if os.path.isfile(levels_path):
        expected = [item for item in _load_json(levels_path) if isinstance(item, dict)]
        if _normalize_level_rows(load_levels()) != _normalize_level_rows(expected):
            mismatches.append("root:levels")
    for username in sorted(os.listdir(root)):
        if username.startswith(".") or username.startswith("_"):
            continue
        user_dir = os.path.join(root, username)
        if not os.path.isdir(user_dir):
            continue
        if os.path.isfile(os.path.join(user_dir, "product_groups.json")):
            source_groups = [item for item in _load_json(os.path.join(user_dir, "product_groups.json")) if isinstance(item, dict)]
            if load_product_groups(username) != source_groups:
                mismatches.append(f"{username}:product_groups")
        source_configs = _iter_factor_param_configs(user_dir)
        seen_scopes = {scope_key for scope_key, _, _ in source_configs}
        for scope_key, ff_alias, payload in source_configs:
            if load_factor_param_config(username, ff_alias, scope_key) != payload:
                mismatches.append(f"{username}:param:{scope_key}:{ff_alias}")
        actual_scopes = set(list_factor_param_config_scopes(username))
        if seen_scopes and actual_scopes.intersection(seen_scopes) != seen_scopes:
            missing = ",".join(sorted(seen_scopes - actual_scopes))
            mismatches.append(f"{username}:param_scopes:{missing}")
    return {"source_root": root, "mismatches": mismatches}


def main() -> int:
    parser = argparse.ArgumentParser(description="Import legacy user account data from data/users into SQLite once.")
    parser.add_argument("--source-root", default=None, help="Legacy users root. Defaults to DATA_DIR/users.")
    parser.add_argument("--verify-only", action="store_true", help="Only verify the imported data.")
    args = parser.parse_args()
    if args.verify_only:
        print(verify_user_account_data_import(args.source_root))
    else:
        print(import_user_account_data_once(args.source_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

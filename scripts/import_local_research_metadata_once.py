#!/usr/bin/env python3
"""Import legacy per-principal research metadata without importing identities.

The old ``data/users`` directory may still contain product groups and factor
parameter presets. User credentials, organizations, hierarchy, roles, and
permissions are owned by Keycloak and are deliberately ignored here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.data_dir import DATA_DIR
from tools.data.account_manage import (
    list_factor_param_config_scopes,
    load_factor_param_config,
    load_product_groups,
    save_product_groups,
)
from tools.data.sqlite.account_manager import (
    ensure_scope_exists,
    save_factor_param_config_payload,
)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _principal_directories(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        path for path in sorted(root.iterdir())
        if path.is_dir() and not path.name.startswith((".", "_"))
    ]


def _iter_factor_param_configs(
    principal_dir: Path,
) -> list[tuple[str, str, dict[str, Any]]]:
    root = principal_dir / "factor_library_param_configs"
    if not root.is_dir():
        return []
    items: list[tuple[str, str, dict[str, Any]]] = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            for path in sorted(entry.glob("*.json")):
                payload = _load_json(path)
                if isinstance(payload, dict):
                    items.append((entry.name, path.stem, payload))
        elif entry.suffix == ".json":
            payload = _load_json(entry)
            if isinstance(payload, dict):
                items.append(("default", entry.stem, payload))
    return items


def import_local_research_metadata_once(
    source_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(source_root or (Path(DATA_DIR) / "users")).expanduser().resolve()
    result = {
        "source_root": str(root),
        "principals": 0,
        "product_groups": 0,
        "param_scopes": 0,
        "param_configs": 0,
        "skipped": 0,
        "identity_records_imported": 0,
    }
    for principal_dir in _principal_directories(root):
        result["principals"] += 1
        principal = principal_dir.name
        try:
            groups_path = principal_dir / "product_groups.json"
            if groups_path.is_file():
                payload = _load_json(groups_path)
                if isinstance(payload, list):
                    groups = [item for item in payload if isinstance(item, dict)]
                    save_product_groups(principal, groups)
                    result["product_groups"] += len(groups)
            configs = _iter_factor_param_configs(principal_dir)
            scopes: set[str] = set()
            for scope_key, family_alias, payload in configs:
                ensure_scope_exists(principal, scope_key)
                save_factor_param_config_payload(
                    principal, family_alias, payload, scope_key,
                )
                scopes.add(scope_key)
            result["param_scopes"] += len(scopes)
            result["param_configs"] += len(configs)
        except Exception:
            result["skipped"] += 1
    return result


def verify_local_research_metadata_import(
    source_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(source_root or (Path(DATA_DIR) / "users")).expanduser().resolve()
    mismatches: list[str] = []
    if not root.is_dir():
        return {"source_root": str(root), "mismatches": ["source root missing"]}
    for principal_dir in _principal_directories(root):
        principal = principal_dir.name
        groups_path = principal_dir / "product_groups.json"
        if groups_path.is_file():
            expected = [
                item for item in (_load_json(groups_path) or [])
                if isinstance(item, dict)
            ]
            actual = load_product_groups(principal)
            # Storage adds stable IDs/revision references to legacy groups.
            # Compare every authored field and cardinality; never ignore a
            # changed selection or silently accept a missing group.
            if len(actual) != len(expected) or any(
                any(row.get(key) != value for key, value in source.items())
                or set(row) - set(source) - {"id", "current_revision_ref"}
                for source, row in zip(expected, actual)
            ):
                mismatches.append(f"{principal}:product_groups")
        configs = _iter_factor_param_configs(principal_dir)
        expected_scopes = {scope for scope, _, _ in configs}
        actual_scopes = set(list_factor_param_config_scopes(principal))
        if not expected_scopes.issubset(actual_scopes):
            mismatches.append(f"{principal}:param_scopes")
        for scope_key, family_alias, payload in configs:
            if load_factor_param_config(principal, family_alias, scope_key) != payload:
                mismatches.append(f"{principal}:param:{scope_key}:{family_alias}")
    return {"source_root": str(root), "mismatches": mismatches}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=None)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    result = (
        verify_local_research_metadata_import(args.source_root)
        if args.verify_only else import_local_research_metadata_once(args.source_root)
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if not result.get("mismatches") else 1


if __name__ == "__main__":
    raise SystemExit(main())

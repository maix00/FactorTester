"""Verify approved implementation sources without loading skill documents."""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import os
from pathlib import Path
from typing import Any


def candidate_source_states(
    *,
    capability_ids: list[str],
    contracts: dict[str, dict[str, Any]],
    catalog: dict[str, Any],
    product_group: str,
) -> dict[str, dict[str, Any]]:
    """Probe only approved candidates needed by the current local graph context."""
    states: dict[str, dict[str, Any]] = {}
    for capability_id in sorted(set(capability_ids)):
        contract = contracts.get(capability_id) or {}
        for implementation in contract.get("implementations") or []:
            if implementation.get("approval_status") != "approved":
                continue
            scopes = implementation.get("product_scopes") or []
            if product_group not in scopes and "all" not in scopes:
                continue
            implementation_id = str(implementation["implementation_id"])
            states[implementation_id] = _implementation_source_state(
                catalog,
                implementation,
            )
    return states


def _implementation_source_state(
    catalog: dict[str, Any],
    implementation: dict[str, Any],
) -> dict[str, Any]:
    """Probe a selected source; never load the skill body into model context."""
    source_path = implementation.get("source_path")
    source_lock = _source_lock(catalog, implementation)
    if (
        not source_path
        and source_lock is None
    ):
        return {"status": "internal"}
    implementation_id = str(implementation.get("implementation_id") or "")
    if source_lock is None:
        return {
            "status": "unapproved",
            "implementation_id": implementation_id,
        }
    source_paths = source_lock.get("source_paths")
    if source_paths is not None:
        if not isinstance(source_paths, list) or not all(
            isinstance(item, str) and item for item in source_paths
        ):
            return {
                "status": "unapproved",
                "implementation_id": implementation_id,
            }
        root = _resolve_source_root(catalog, implementation, source_lock)
        if root is None or not all(
            (root / item).is_file() for item in source_paths
        ):
            return {
                "status": "unavailable",
                "implementation_id": implementation_id,
                "expected_sha256": str(source_lock["sha256"]),
            }
        observed = source_manifest_sha256(root, source_paths)
    else:
        path = _resolve_source_path(catalog, implementation, source_lock)
        if path is None or not path.is_file():
            return {
                "status": "unavailable",
                "implementation_id": implementation_id,
                "expected_sha256": str(source_lock["sha256"]),
            }
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
    expected = str(source_lock["sha256"])
    return {
        "status": "verified" if observed == expected else "mismatch",
        "implementation_id": implementation_id,
        "expected_sha256": expected,
        "observed_sha256": observed,
    }


def source_manifest_sha256(root: Path, source_paths: list[str]) -> str:
    """Hash every progressively loaded Skill file into one approval identity."""
    manifest = {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
        for path in sorted(source_paths)
    }
    payload = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _resolve_source_root(
    catalog: dict[str, Any],
    implementation: dict[str, Any],
    source_lock: dict[str, Any],
) -> Path | None:
    provider_id = str(implementation.get("provider") or "")
    provider = (
        (catalog.get("provider_lock") or {}).get("providers") or {}
    ).get(provider_id) or {}
    root_package = str(
        source_lock.get("root_package")
        or provider.get("root_package")
        or ""
    ).strip()
    if root_package:
        try:
            return Path(str(importlib.resources.files(root_package)))
        except (ModuleNotFoundError, TypeError):
            return None
    root_env = str(
        source_lock.get("root_env")
        or provider.get("root_env")
        or ""
    ).strip()
    root_value = os.environ.get(root_env) if root_env else None
    root = (
        root_value
        or source_lock.get("root_hint")
        or provider.get("root_hint")
    )
    return Path(str(root)).expanduser() if root else None


def _source_lock(
    catalog: dict[str, Any],
    implementation: dict[str, Any],
) -> dict[str, Any] | None:
    inline_hash = implementation.get("approved_source_sha256")
    if inline_hash:
        return {
            "source_path": implementation.get("source_path"),
            "sha256": inline_hash,
        }
    provider_lock = catalog.get("provider_lock") or {}
    value = (provider_lock.get("implementations") or {}).get(
        str(implementation.get("implementation_id") or "")
    )
    return value if isinstance(value, dict) else None


def _resolve_source_path(
    catalog: dict[str, Any],
    implementation: dict[str, Any],
    source_lock: dict[str, Any],
) -> Path | None:
    source_path = str(
        source_lock.get("source_path")
        or implementation.get("source_path")
        or ""
    ).strip()
    if not source_path:
        return None
    path = Path(source_path).expanduser()
    if path.is_absolute():
        return path
    root = _resolve_source_root(catalog, implementation, source_lock)
    if not root:
        return None
    return root / path

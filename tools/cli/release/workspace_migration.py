"""Plan, apply, verify, and roll back profile workspace migrations."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from .local_profile import LocalProfileStore
from .local_profile_contracts import validate_local_identifier
from .storage import read_json, write_json
from .workspace_inventory import available_bytes, inventory_workspace


def default_profile_workspace_root(profile_id: str) -> Path:
    validate_local_identifier(profile_id, "profile_id")
    return (
        Path.home()
        / "Documents"
        / "FactorTester"
        / "profiles"
        / profile_id
    )


def plan_workspace_migration(
    profile_id: str,
    target_root: Path,
    workspace_specs: list[dict[str, str]],
) -> dict[str, Any]:
    root = target_root.expanduser().resolve()
    if root.exists():
        raise ValueError(f"profile workspace target already exists: {root}")
    workspaces = []
    required = 0
    seen: set[str] = set()
    for spec in workspace_specs:
        workspace_id = validate_local_identifier(
            spec.get("workspace_id"), "workspace_id"
        )
        if workspace_id in seen:
            raise ValueError(f"duplicate workspace_id: {workspace_id}")
        seen.add(workspace_id)
        inventory = inventory_workspace(Path(spec["source"]))
        required += int(inventory["bytes"])
        workspaces.append({
            "workspace_id": workspace_id,
            "target": str(root / "workspaces" / workspace_id),
            "access_mode": spec["access_mode"],
            "server_workspace_ref": spec.get(
                "server_workspace_ref", ""
            ),
            "inventory": inventory,
        })
    free = available_bytes(root)
    plan = {
        "schema_version": 1,
        "profile_id": profile_id,
        "target_root": str(root),
        "required_bytes": required,
        "available_bytes": free,
        "capacity_ok": free >= required,
        "workspaces": workspaces,
    }
    plan["plan_sha256"] = _digest(plan)
    return plan


def apply_workspace_migration(
    client_root: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    _validate_plan(plan)
    if not plan["capacity_ok"]:
        raise ValueError("workspace migration has insufficient capacity")
    target_root = Path(plan["target_root"])
    if target_root.exists():
        raise ValueError(f"profile workspace target exists: {target_root}")
    store = LocalProfileStore(client_root)
    profile = store.load(plan["profile_id"])
    migration_id = uuid4().hex
    staging = target_root.parent / f".{target_root.name}.{migration_id}.staging"
    receipt_path = _receipt_path(
        store.root, plan["profile_id"], migration_id
    )
    receipt = {
        "schema_version": 1,
        "migration_id": migration_id,
        "profile_id": plan["profile_id"],
        "plan_sha256": plan["plan_sha256"],
        "old_workspace_root": profile["workspace_root"],
        "new_workspace_root": str(target_root),
        "status": "staging",
        "workspace_ids": [
            item["workspace_id"] for item in plan["workspaces"]
        ],
    }
    write_json(receipt_path, receipt)
    receipt_path.chmod(0o600)
    try:
        _stage(plan, staging)
        target_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target_root)
        for item in plan["workspaces"]:
            inventory = item["inventory"]
            store.upsert_workspace(
                plan["profile_id"],
                {
                    "workspace_id": item["workspace_id"],
                    "path": item["target"],
                    "access_mode": item["access_mode"],
                    "owner_ref": inventory["owner_ref"],
                    "server_workspace_ref": item["server_workspace_ref"],
                },
                workspace_root=target_root,
            )
        receipt["status"] = "applied"
        write_json(receipt_path, receipt)
        receipt_path.chmod(0o600)
        return receipt
    except Exception:
        receipt["status"] = "failed"
        write_json(receipt_path, receipt)
        receipt_path.chmod(0o600)
        if staging.exists():
            shutil.rmtree(staging)
        raise


def verify_workspace_migration(
    client_root: Path,
    profile_id: str,
) -> dict[str, Any]:
    profile = LocalProfileStore(client_root).load(profile_id)
    results = []
    for workspace in profile["workspaces"]:
        path = Path(workspace["path"])
        inventory = inventory_workspace(path)
        results.append({
            "workspace_id": workspace["workspace_id"],
            "path": str(path),
            "owner_matches": (
                inventory["owner_ref"] == workspace["owner_ref"]
            ),
            "git_preserved": inventory["has_git"],
            "vscode_preserved": inventory["has_vscode"],
            "pylance_ready": inventory["has_pyright_config"],
        })
    valid = bool(results) and all(
        item["owner_matches"]
        and item["git_preserved"]
        and item["vscode_preserved"]
        and item["pylance_ready"]
        for item in results
    )
    return {
        "profile_id": profile_id,
        "workspace_root": profile["workspace_root"],
        "valid": valid,
        "workspaces": results,
    }


def rollback_workspace_migration(
    client_root: Path,
    profile_id: str,
    migration_id: str,
) -> dict[str, Any]:
    store = LocalProfileStore(client_root)
    path = _receipt_path(store.root, profile_id, migration_id)
    receipt = read_json(path)
    if not receipt or receipt.get("status") != "applied":
        raise ValueError("applied workspace migration receipt not found")
    profile = store.load(profile_id)
    profile["workspace_root"] = receipt["old_workspace_root"]
    reverted = set(receipt["workspace_ids"])
    profile["workspaces"] = [
        item for item in profile["workspaces"]
        if item["workspace_id"] not in reverted
    ]
    store.save(profile)
    receipt["status"] = "rolled_back"
    receipt["preserved_workspace_root"] = receipt["new_workspace_root"]
    write_json(path, receipt)
    path.chmod(0o600)
    return receipt


def _stage(plan: dict[str, Any], staging: Path) -> None:
    (staging / "workspaces").mkdir(parents=True)
    (staging / "local-data").mkdir()
    (staging / "adapters").mkdir()
    for item in plan["workspaces"]:
        target = staging / "workspaces" / item["workspace_id"]
        shutil.copytree(
            item["inventory"]["source"],
            target,
            symlinks=True,
        )
        (target / "research").mkdir(exist_ok=True)


def _validate_plan(plan: dict[str, Any]) -> None:
    expected = str(plan.get("plan_sha256") or "")
    unsigned = {key: value for key, value in plan.items()
                if key != "plan_sha256"}
    if not expected or _digest(unsigned) != expected:
        raise ValueError("workspace migration plan hash mismatch")


def _digest(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _receipt_path(
    profiles_root: Path,
    profile_id: str,
    migration_id: str,
) -> Path:
    validate_local_identifier(migration_id, "migration_id")
    return (
        profiles_root
        / "receipts"
        / profile_id
        / f"{migration_id}.json"
    )

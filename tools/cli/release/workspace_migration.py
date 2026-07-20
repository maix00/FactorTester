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
        if inventory["unsafe_symlinks"]:
            raise ValueError(
                "workspace contains symlinks outside its root: "
                + ", ".join(inventory["unsafe_symlinks"])
            )
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
        "workspaces": [],
    }
    write_json(receipt_path, receipt)
    receipt_path.chmod(0o600)
    try:
        _assert_sources_unchanged(plan)
        staged = _stage(plan, staging)
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
        receipt["workspaces"] = staged
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
        manifest = _manifest(path)
        hooks = _active_hooks(path)
        results.append({
            "workspace_id": workspace["workspace_id"],
            "path": str(path),
            "owner_matches": (
                inventory["owner_ref"] == workspace["owner_ref"]
            ),
            "git_preserved": inventory["has_git"],
            "vscode_preserved": inventory["has_vscode"],
            "pylance_ready": inventory["has_pyright_config"],
            "manifest_paths_relocated": _manifest_paths_within(
                manifest, path
            ),
            "machine_metadata_relocated": (
                _machine_metadata_paths_within(path)
            ),
            "legacy_hooks_removed": not hooks,
            "unsafe_symlinks": inventory["unsafe_symlinks"],
        })
    valid = bool(results) and all(
        item["owner_matches"]
        and item["git_preserved"]
        and item["vscode_preserved"]
        and item["pylance_ready"]
        and item["manifest_paths_relocated"]
        and item["machine_metadata_relocated"]
        and item["legacy_hooks_removed"]
        and not item["unsafe_symlinks"]
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
    if profile["workspace_root"] != receipt["new_workspace_root"]:
        raise ValueError(
            "profile no longer points at this migration; rollback refused"
        )
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


def plan_workspace_repair(
    client_root: Path,
    profile_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    """Describe an in-place repair without mutating the legacy workspace."""
    store = LocalProfileStore(client_root)
    profile = store.load(profile_id)
    workspace = next(
        (
            item for item in profile["workspaces"]
            if item["workspace_id"] == workspace_id
        ),
        None,
    )
    if workspace is None:
        raise ValueError(f"local workspace not found: {workspace_id}")
    root = Path(workspace["path"]).expanduser().resolve()
    inventory = inventory_workspace(root)
    manifest = _manifest(root)
    active_hooks = _active_hooks(root)
    issues = []
    if not _manifest_paths_within(manifest, root):
        issues.append("manifest_paths_outside_workspace")
    if not _machine_metadata_paths_within(root):
        issues.append("machine_metadata_paths_outside_workspace")
    if active_hooks:
        issues.append("active_private_hooks")
    if inventory["unsafe_symlinks"]:
        issues.append("unsafe_symlinks")
    plan = {
        "schema_version": 1,
        "operation": "repair_existing_workspace",
        "profile_id": profile_id,
        "workspace_id": workspace_id,
        "workspace_path": str(root),
        "owner_ref": inventory["owner_ref"],
        "inventory": inventory,
        "active_hooks": [path.name for path in active_hooks],
        "research_refs": _research_refs(root),
        "issues": issues,
        "repairable": (
            bool(issues)
            and not inventory["unsafe_symlinks"]
        ),
    }
    plan["plan_sha256"] = _digest(plan)
    return plan


def apply_workspace_repair(
    client_root: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    _validate_plan(plan)
    if plan.get("operation") != "repair_existing_workspace":
        raise ValueError("workspace repair operation is invalid")
    if not plan.get("repairable"):
        raise ValueError("workspace repair plan has no safe repair")
    store = LocalProfileStore(client_root)
    profile = store.load(str(plan["profile_id"]))
    workspace = next(
        (
            item for item in profile["workspaces"]
            if item["workspace_id"] == plan["workspace_id"]
        ),
        None,
    )
    if workspace is None or workspace["path"] != plan["workspace_path"]:
        raise ValueError("profile workspace pointer changed after repair plan")
    root = Path(plan["workspace_path"])
    observed = plan_workspace_repair(
        client_root,
        str(plan["profile_id"]),
        str(plan["workspace_id"]),
    )
    if observed["plan_sha256"] != plan["plan_sha256"]:
        raise ValueError("workspace changed after repair plan")
    repair_id = uuid4().hex
    staging = root.parent / f".{root.name}.{repair_id}.repair-staging"
    backup = root.parent / f".{root.name}.{repair_id}.unsafe-backup"
    metadata_backup = (
        store.root
        / "repair-backups"
        / str(plan["profile_id"])
        / repair_id
    )
    receipt_path = _repair_receipt_path(
        store.root, str(plan["profile_id"]), repair_id
    )
    receipt = {
        "schema_version": 1,
        "operation": "repair_existing_workspace",
        "repair_id": repair_id,
        "profile_id": plan["profile_id"],
        "workspace_id": plan["workspace_id"],
        "plan_sha256": plan["plan_sha256"],
        "workspace_path": str(root),
        "unsafe_backup_path": str(backup),
        "metadata_backup_path": str(metadata_backup),
        "before": {
            "inventory": plan["inventory"],
            "active_hooks": plan["active_hooks"],
            "research_refs": plan["research_refs"],
        },
        "status": "staging",
    }
    write_json(receipt_path, receipt)
    receipt_path.chmod(0o600)
    try:
        shutil.copytree(root, staging, symlinks=True)
        _remove_active_hooks(staging)
        _relocate_machine_metadata(staging, root)
        (metadata_backup / "receipts").mkdir(parents=True)
        legacy_receipts = (
            store.root / "receipts" / str(plan["profile_id"])
        )
        if legacy_receipts.is_dir():
            shutil.copytree(
                legacy_receipts,
                metadata_backup / "receipts",
                dirs_exist_ok=True,
            )
        os.replace(root, backup)
        try:
            os.replace(staging, root)
        except Exception:
            os.replace(backup, root)
            raise
        after = inventory_workspace(root)
        verification = verify_workspace_repair(
            client_root, str(plan["profile_id"]), repair_id,
            receipt_override=receipt,
        )
        if not verification["valid"]:
            repaired = root.parent / f".{root.name}.{repair_id}.failed-repair"
            os.replace(root, repaired)
            os.replace(backup, root)
            raise ValueError("workspace repair verification failed")
        receipt["after"] = {
            "inventory": after,
            "active_hooks": [],
            "research_refs": _research_refs(root),
        }
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


def verify_workspace_repair(
    client_root: Path,
    profile_id: str,
    repair_id: str,
    *,
    receipt_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store = LocalProfileStore(client_root)
    receipt = receipt_override or read_json(
        _repair_receipt_path(store.root, profile_id, repair_id)
    )
    if not isinstance(receipt, dict):
        raise ValueError("workspace repair receipt not found")
    root = Path(str(receipt["workspace_path"]))
    inventory = inventory_workspace(root)
    refs = _research_refs(root)
    before = receipt["before"]
    checks = {
        "owner_preserved": (
            inventory["owner_ref"]
            == before["inventory"]["owner_ref"]
        ),
        "git_head_preserved": (
            inventory["git_head"]
            == before["inventory"]["git_head"]
        ),
        "git_refs_preserved": (
            inventory["git_refs_sha256"]
            == before["inventory"]["git_refs_sha256"]
        ),
        "manifest_relocated": _manifest_paths_within(
            _manifest(root), root
        ),
        "machine_metadata_relocated": _machine_metadata_paths_within(root),
        "private_hooks_removed": not _active_hooks(root),
        "research_refs_preserved": refs == before["research_refs"],
        "pylance_ready": inventory["has_pyright_config"],
        "unsafe_symlinks_absent": not inventory["unsafe_symlinks"],
    }
    return {
        "schema_version": 1,
        "repair_id": repair_id,
        "profile_id": profile_id,
        "workspace_id": receipt["workspace_id"],
        "valid": all(checks.values()),
        "checks": checks,
    }


def rollback_workspace_repair(
    client_root: Path,
    profile_id: str,
    repair_id: str,
) -> dict[str, Any]:
    store = LocalProfileStore(client_root)
    path = _repair_receipt_path(store.root, profile_id, repair_id)
    receipt = read_json(path)
    if not isinstance(receipt, dict) or receipt.get("status") != "applied":
        raise ValueError("applied workspace repair receipt not found")
    root = Path(str(receipt["workspace_path"]))
    backup = Path(str(receipt["unsafe_backup_path"]))
    if not root.is_dir() or not backup.is_dir():
        raise ValueError("workspace repair rollback inputs are missing")
    current = inventory_workspace(root)
    if current != receipt["after"]["inventory"]:
        raise ValueError("repaired workspace changed; rollback refused")
    preserved = root.parent / f".{root.name}.{repair_id}.repaired"
    os.replace(root, preserved)
    try:
        os.replace(backup, root)
    except Exception:
        os.replace(preserved, root)
        raise
    receipt["status"] = "rolled_back"
    receipt["preserved_repaired_path"] = str(preserved)
    write_json(path, receipt)
    path.chmod(0o600)
    return receipt


def _stage(plan: dict[str, Any], staging: Path) -> list[dict[str, Any]]:
    (staging / "workspaces").mkdir(parents=True)
    (staging / "local-data").mkdir()
    (staging / "adapters").mkdir()
    staged = []
    for item in plan["workspaces"]:
        target = staging / "workspaces" / item["workspace_id"]
        shutil.copytree(
            item["inventory"]["source"],
            target,
            symlinks=True,
        )
        removed_hooks = _remove_active_hooks(target)
        logical_target = Path(item["target"])
        _relocate_machine_metadata(target, logical_target)
        (target / "research").mkdir(exist_ok=True)
        after = inventory_workspace(target)
        staged.append({
            "workspace_id": item["workspace_id"],
            "owner_ref": after["owner_ref"],
            "source_tree_sha256": item["inventory"]["tree_sha256"],
            "target_tree_sha256": after["tree_sha256"],
            "git_head": after["git_head"],
            "git_branch": after["git_branch"],
            "git_refs_sha256": after["git_refs_sha256"],
            "removed_hooks": removed_hooks,
            "manifest_relocated": _manifest_paths_within(
                _manifest(target), logical_target
            ),
            "machine_metadata_relocated": (
                _machine_metadata_paths_within_for(target, logical_target)
            ),
            "pylance_ready": after["has_pyright_config"],
        })
    return staged


def _assert_sources_unchanged(plan: dict[str, Any]) -> None:
    bound = (
        "owner_ref", "manifest_sha256", "git_head", "git_branch",
        "git_refs_sha256", "tree_sha256", "file_count", "bytes",
    )
    for item in plan["workspaces"]:
        expected = item["inventory"]
        observed = inventory_workspace(Path(expected["source"]))
        if any(observed.get(key) != expected.get(key) for key in bound):
            raise ValueError(
                f"workspace changed after plan: {item['workspace_id']}"
            )
        if observed["unsafe_symlinks"]:
            raise ValueError(
                f"workspace symlink escaped after plan: {item['workspace_id']}"
            )


def _manifest(root: Path) -> dict[str, Any]:
    return json.loads(
        (root / ".factor_workspace" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )


def _relocate_manifest(root: Path, logical_root: Path | None = None) -> None:
    path = root / ".factor_workspace" / "manifest.json"
    manifest = _manifest(root)
    destination = logical_root or root
    replacements = {
        "workspace_root": destination,
        "custom_factor_dir": destination / "custom_factors",
        "public_factor_dir": destination / "public_factors",
    }
    for key, value in replacements.items():
        if key in manifest:
            manifest[key] = str(value)
    git = manifest.get("git")
    if isinstance(git, dict):
        for key in ("workspace_root", "git_repo_root"):
            if key in git:
                git[key] = str(destination)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _relocate_machine_metadata(
    root: Path,
    logical_root: Path | None = None,
) -> None:
    destination = logical_root or root
    _relocate_manifest(root, destination)
    path = root / "tools_index.json"
    if not path.is_file():
        return
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("tools_index.json must be an object")
    value["workspace_root"] = str(destination)
    value["tools_dir"] = str(destination / "tools")
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _machine_metadata_paths_within(root: Path) -> bool:
    return _machine_metadata_paths_within_for(root, root)


def _machine_metadata_paths_within_for(
    root: Path,
    logical_root: Path,
) -> bool:
    if not _manifest_paths_within(_manifest(root), logical_root):
        return False
    path = root / "tools_index.json"
    if not path.is_file():
        return True
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        for key in ("workspace_root", "tools_dir"):
            Path(str(value[key])).resolve().relative_to(
                logical_root.resolve()
            )
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return True


def _manifest_paths_within(manifest: dict[str, Any], root: Path) -> bool:
    values = [
        manifest.get("workspace_root"),
        manifest.get("custom_factor_dir"),
        manifest.get("public_factor_dir"),
    ]
    git = manifest.get("git")
    if isinstance(git, dict):
        values.extend([git.get("workspace_root"), git.get("git_repo_root")])
    for value in (item for item in values if item):
        try:
            Path(str(value)).resolve().relative_to(root.resolve())
        except ValueError:
            return False
    return True


def _active_hooks(root: Path) -> list[Path]:
    hooks = root / ".git" / "hooks"
    if not hooks.is_dir():
        return []
    return sorted(
        path for path in hooks.iterdir()
        if path.is_file() and not path.name.endswith(".sample")
    )


def _remove_active_hooks(root: Path) -> list[str]:
    removed = []
    for path in _active_hooks(root):
        removed.append(path.name)
        path.unlink()
    return removed


def _research_refs(root: Path) -> dict[str, list[str]]:
    """Inventory stable research identifiers without copying report contents."""
    keys = {
        "workspace_id", "run_id", "branch_id", "checkpoint_ref",
        "evidence_ref", "report_ref", "artifact_ref",
        "factor_family_version", "provenance_ref",
    }
    found = {key: set() for key in keys}
    candidates = [
        root / "research",
        root / "research_reports",
        root / ".factor_workspace",
    ]
    for directory in candidates:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.json"):
            if path.stat().st_size > 2 * 1024 * 1024:
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            _collect_research_refs(value, keys, found)
    return {
        key: sorted(values)
        for key, values in sorted(found.items())
        if values
    }


def _collect_research_refs(
    value: Any,
    keys: set[str],
    found: dict[str, set[str]],
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, (str, int)):
                text = str(item).strip()
                if text:
                    found[key].add(text)
            _collect_research_refs(item, keys, found)
    elif isinstance(value, list):
        for item in value:
            _collect_research_refs(item, keys, found)


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


def _repair_receipt_path(
    profiles_root: Path,
    profile_id: str,
    repair_id: str,
) -> Path:
    validate_local_identifier(repair_id, "repair_id")
    return (
        profiles_root
        / "repair-receipts"
        / profile_id
        / f"{repair_id}.json"
    )

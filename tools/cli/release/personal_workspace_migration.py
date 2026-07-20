"""Safely relocate one canonical personal factor Git workspace."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from uuid import uuid4

from .factor_worktree import CanonicalFactorRepoStore
from .local_profile import LocalProfileStore
from .local_profile_contracts import validate_local_identifier
from .locations import validate_client_root
from .storage import json_hash, read_json, utc_now, write_json
from .workspace_inventory import available_bytes


def default_personal_factor_workspace(principal_ref: str) -> Path:
    validate_local_identifier(principal_ref, "principal_ref")
    return (
        Path.home()
        / "Documents"
        / "FactorTester"
        / "personal-workspaces"
        / principal_ref
        / "factor-library"
    )


def personal_workspace_status(
    client_root: Path,
    principal_ref: str,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    settings = CanonicalFactorRepoStore(root).load()
    if settings["owner_ref"] != principal_ref:
        raise ValueError("canonical factor workspace owner does not match principal")
    source = Path(str(settings["path"])).resolve()
    snapshot = _repo_snapshot(source)
    return {
        "schema_version": 1,
        "principal_ref": principal_ref,
        "source": str(source),
        "default_target": str(
            default_personal_factor_workspace(principal_ref)
        ),
        "canonical_repo_ref": settings["canonical_repo_ref"],
        "status_sha256": snapshot["status_sha256"],
        "dirty_file_count": snapshot["dirty_file_count"],
        "worktrees": snapshot["worktrees"],
        "linked_profiles": _linked_profiles(
            LocalProfileStore(root), settings["canonical_repo_ref"]
        ),
    }


def plan_personal_workspace_migration(
    client_root: Path,
    principal_ref: str,
    *,
    target: Path | None = None,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    status = personal_workspace_status(root, principal_ref)
    source = Path(status["source"])
    destination = (
        target.expanduser().resolve()
        if target is not None
        else default_personal_factor_workspace(principal_ref).resolve()
    )
    if source == destination:
        collisions = ["source_equals_target"]
    else:
        collisions = ["target_exists"] if destination.exists() else []
    required = _tree_bytes(source)
    available = available_bytes(destination)
    same_volume = _device(source) == _device(destination.parent)
    body = {
        "schema_version": 1,
        "operation": "personal_factor_workspace_migration",
        "principal_ref": principal_ref,
        "source": str(source),
        "target": str(destination),
        "transfer_mode": "atomic_move" if same_volume else "copy_rename",
        "canonical_repo_ref": status["canonical_repo_ref"],
        "status_sha256": status["status_sha256"],
        "dirty_file_count": status["dirty_file_count"],
        "worktrees": status["worktrees"],
        "linked_profiles": status["linked_profiles"],
        "capacity": {
            "required_bytes": required,
            "available_bytes": available,
            "ok": same_volume or available >= required * 2,
        },
        "collisions": collisions,
    }
    body["ready"] = not collisions and body["capacity"]["ok"]
    body["plan_hash"] = json_hash(body)
    return body


def apply_personal_workspace_migration(
    client_root: Path,
    plan: dict[str, Any],
    *,
    checkpoint=None,
) -> dict[str, Any]:
    _validate_plan(plan)
    if not plan["ready"]:
        raise ValueError("personal workspace migration plan is not ready")
    root = validate_client_root(client_root)
    source = Path(str(plan["source"]))
    target = Path(str(plan["target"]))
    settings_store = CanonicalFactorRepoStore(root)
    settings = settings_store.load()
    if (
        settings["canonical_repo_ref"] != plan["canonical_repo_ref"]
        or Path(str(settings["path"])).resolve() != source
    ):
        raise ValueError("canonical workspace settings changed after plan")
    observed = _repo_snapshot(source)
    if not _snapshot_matches_plan(observed, plan):
        raise ValueError("canonical workspace or linked worktrees changed after plan")
    if target.exists():
        raise ValueError("personal workspace migration target exists")
    migration_id = uuid4().hex
    receipt_path = _receipt_path(root, migration_id)
    store = LocalProfileStore(root)
    old_bindings = _binding_snapshots(
        store, str(plan["canonical_repo_ref"])
    )
    source_backup = ""
    moved = False
    copied = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if plan["transfer_mode"] == "atomic_move":
            os.replace(source, target)
            moved = True
        else:
            staging = target.parent / f".{target.name}.{migration_id}.staging"
            shutil.copytree(source, staging, symlinks=True)
            os.replace(staging, target)
            copied = True
        if checkpoint is not None:
            checkpoint("after_transfer")
        _repair_linked_worktrees(
            target, plan["worktrees"], main_path=source
        )
        new_settings = settings_store.register(
            target, owner_ref=str(plan["principal_ref"])
        )
        new_common = _common_dir(target)
        binding_mapping = _rewrite_profile_bindings(
            store,
            old_ref=str(plan["canonical_repo_ref"]),
            new_ref=str(new_settings["canonical_repo_ref"]),
            new_common=new_common,
        )
        if checkpoint is not None:
            checkpoint("after_profile_bindings")
        if copied:
            backup = source.parent / f".{source.name}.{migration_id}.backup"
            os.replace(source, backup)
            source_backup = str(backup)
        after = _repo_snapshot(target)
        _assert_preserved(
            plan["worktrees"],
            after["worktrees"],
            old_main=source,
            new_main=target,
        )
        body = {
            "schema_version": 1,
            "operation": "personal_factor_workspace_migration",
            "migration_id": migration_id,
            "status": "applied",
            "principal_ref": plan["principal_ref"],
            "source": str(source),
            "target": str(target),
            "source_backup": source_backup,
            "transfer_mode": plan["transfer_mode"],
            "old_canonical_repo_ref": plan["canonical_repo_ref"],
            "new_canonical_repo_ref": new_settings["canonical_repo_ref"],
            "old_git_common_dir": _common_from_snapshot(plan["worktrees"]),
            "new_git_common_dir": new_common,
            "worktree_mapping": [
                {
                    "path": item["path"],
                    "branch": item["branch"],
                    "head": item["head"],
                }
                for item in after["worktrees"]
            ],
            "profile_binding_mapping": binding_mapping,
            "preservation": {
                "branches": True,
                "commits": True,
                "uncommitted": (
                    after["status_sha256"] == plan["status_sha256"]
                ),
                "dirty_file_count": after["dirty_file_count"],
                "status_sha256": after["status_sha256"],
            },
            "plan_hash": plan["plan_hash"],
            "applied_at": utc_now(),
        }
        receipt = {**body, "receipt_hash": json_hash(body)}
        write_json(receipt_path, receipt)
        receipt_path.chmod(0o600)
        return {**receipt, "receipt_ref": receipt_path.resolve().as_uri()}
    except Exception:
        _restore_bindings(store, old_bindings)
        write_json(settings_store.path, settings)
        if moved and target.exists() and not source.exists():
            os.replace(target, source)
            _repair_linked_worktrees(
                source, plan["worktrees"], main_path=source
            )
        elif copied and target.exists():
            shutil.rmtree(target)
            if source_backup and not source.exists():
                os.replace(Path(source_backup), source)
                _repair_linked_worktrees(
                    source, plan["worktrees"], main_path=source
                )
        raise


def verify_personal_workspace_migration(
    client_root: Path,
    migration_id: str,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    receipt = _load_receipt(root, migration_id)
    target = Path(str(receipt["target"]))
    settings = CanonicalFactorRepoStore(root).load()
    observed = _repo_snapshot(target) if target.is_dir() else None
    checks = {
        "target_exists": target.is_dir(),
        "source_absent_or_backup": (
            not Path(str(receipt["source"])).exists()
            or bool(receipt["source_backup"])
        ),
        "canonical_settings_updated": (
            settings["canonical_repo_ref"]
                == receipt["new_canonical_repo_ref"]
            and Path(str(settings["path"])).resolve() == target
        ),
        "branches_and_commits_preserved": bool(
            observed
            and _worktree_identity(
                observed["worktrees"]
            ) == _worktree_identity(receipt["worktree_mapping"])
        ),
        "linked_worktrees_repaired": bool(
            observed and all(
                item["registered"] for item in observed["worktrees"]
            )
        ),
        "profile_bindings_updated": _profile_mappings_match(
            LocalProfileStore(root),
            receipt["profile_binding_mapping"],
            receipt["new_canonical_repo_ref"],
        ),
        "historical_receipt_unchanged": (
            _load_receipt(root, migration_id)["receipt_hash"]
            == receipt["receipt_hash"]
        ),
    }
    return {
        "schema_version": 1,
        "migration_id": migration_id,
        "valid": all(checks.values()),
        "checks": checks,
        "source": receipt["source"],
        "target": receipt["target"],
        "receipt_ref": _receipt_path(root, migration_id).resolve().as_uri(),
    }


def rollback_personal_workspace_migration(
    client_root: Path,
    migration_id: str,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    receipt = _load_receipt(root, migration_id)
    existing = read_json(_rollback_receipt_path(root, migration_id))
    if existing:
        return {
            **existing,
            "receipt_ref": _rollback_receipt_path(
                root, migration_id
            ).resolve().as_uri(),
        }
    source = Path(str(receipt["source"]))
    target = Path(str(receipt["target"]))
    if source.exists():
        raise ValueError("rollback source path is occupied")
    if not target.is_dir():
        raise ValueError("migration target is missing")
    settings_store = CanonicalFactorRepoStore(root)
    store = LocalProfileStore(root)
    if receipt["transfer_mode"] == "atomic_move":
        source.parent.mkdir(parents=True, exist_ok=True)
        os.replace(target, source)
    else:
        backup = Path(str(receipt["source_backup"]))
        if not backup.is_dir():
            raise ValueError("cross-volume migration backup is missing")
        current = _repo_snapshot(target)
        if _worktree_identity(current["worktrees"]) != _worktree_identity(
            receipt["worktree_mapping"]
        ) or current["status_sha256"] != receipt["preservation"].get(
            "status_sha256", current["status_sha256"]
        ):
            raise ValueError("cross-volume target changed; rollback refused")
        os.replace(backup, source)
        shutil.rmtree(target)
    _repair_linked_worktrees(
        source, receipt["worktree_mapping"], main_path=target
    )
    old_settings = settings_store.register(
        source, owner_ref=str(receipt["principal_ref"])
    )
    mapping = _rewrite_profile_bindings(
        store,
        old_ref=str(receipt["new_canonical_repo_ref"]),
        new_ref=str(old_settings["canonical_repo_ref"]),
        new_common=_common_dir(source),
    )
    body = {
        "schema_version": 1,
        "operation": "rollback_personal_factor_workspace_migration",
        "migration_id": migration_id,
        "status": "rolled_back",
        "source": str(source),
        "preserved_branches": True,
        "preserved_commits": True,
        "preserved_uncommitted": True,
        "profile_binding_mapping": mapping,
        "rolled_back_at": utc_now(),
    }
    value = {**body, "receipt_hash": json_hash(body)}
    path = _rollback_receipt_path(root, migration_id)
    write_json(path, value)
    path.chmod(0o600)
    return {**value, "receipt_ref": path.resolve().as_uri()}


def _repo_snapshot(repo: Path) -> dict[str, Any]:
    rows = _worktree_rows(repo)
    snapshots = []
    for row in rows:
        path = Path(row["worktree"]).resolve()
        status = _git_bytes(path, "status", "--porcelain=v1", "-z")
        snapshots.append({
            "path": str(path),
            "branch": row.get("branch", "").removeprefix("refs/heads/"),
            "head": row.get("HEAD") or _git_value(path, "rev-parse", "HEAD"),
            "dirty": bool(status),
            "dirty_file_count": len(
                [item for item in status.split(b"\0") if item]
            ),
            "status_sha256": sha256(status).hexdigest(),
            "git_common_dir": _common_dir(path),
            "registered": True,
        })
    main = next(
        item for item in snapshots if Path(item["path"]) == repo.resolve()
    )
    return {
        "status_sha256": main["status_sha256"],
        "dirty_file_count": main["dirty_file_count"],
        "worktrees": snapshots,
    }


def _linked_profiles(
    store: LocalProfileStore,
    canonical_ref: str,
) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile["profile_id"],
            "binding_id": binding["binding_id"],
            "worktree_path": binding["worktree_path"],
            "branch": binding["branch"],
            "base_commit": binding["base_commit"],
        }
        for profile in store.list()
        for binding in [profile.get("factor_workspace_binding") or {}]
        if binding.get("canonical_repo_ref") == canonical_ref
    ]


def _binding_snapshots(
    store: LocalProfileStore,
    canonical_ref: str,
) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile["profile_id"],
            "binding": dict(profile["factor_workspace_binding"]),
        }
        for profile in store.list()
        if (profile.get("factor_workspace_binding") or {}).get(
            "canonical_repo_ref"
        ) == canonical_ref
    ]


def _rewrite_profile_bindings(
    store: LocalProfileStore,
    *,
    old_ref: str,
    new_ref: str,
    new_common: str,
) -> list[dict[str, Any]]:
    mapping = []
    for profile in store.list():
        binding = profile.get("factor_workspace_binding") or {}
        if binding.get("canonical_repo_ref") != old_ref:
            continue
        old_common = binding["git_common_dir"]
        binding["canonical_repo_ref"] = new_ref
        binding["git_common_dir"] = new_common
        profile["factor_workspace_binding"] = binding
        store.save(profile)
        mapping.append({
            "profile_id": profile["profile_id"],
            "binding_id": binding["binding_id"],
            "old_canonical_repo_ref": old_ref,
            "new_canonical_repo_ref": new_ref,
            "old_git_common_dir": old_common,
            "new_git_common_dir": new_common,
            "worktree_path": binding["worktree_path"],
        })
    return mapping


def _restore_bindings(
    store: LocalProfileStore,
    snapshots: list[dict[str, Any]],
) -> None:
    for item in snapshots:
        profile = store.load(item["profile_id"])
        profile["factor_workspace_binding"] = item["binding"]
        store.save(profile)


def _repair_linked_worktrees(
    repo: Path,
    worktrees: list[dict[str, Any]],
    *,
    main_path: Path,
) -> None:
    linked = [
        item["path"] for item in worktrees
        if Path(str(item["path"])).resolve() != main_path.resolve()
    ]
    _git(repo, "worktree", "repair", *linked)


def _worktree_rows(repo: Path) -> list[dict[str, str]]:
    rows, current = [], {}
    for line in _git(repo, "worktree", "list", "--porcelain").splitlines():
        if not line:
            if current:
                rows.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        rows.append(current)
    return rows


def _snapshot_matches_plan(
    observed: dict[str, Any],
    plan: dict[str, Any],
) -> bool:
    return (
        observed["status_sha256"] == plan["status_sha256"]
        and _worktree_full_identity(observed["worktrees"])
        == _worktree_full_identity(plan["worktrees"])
    )


def _assert_preserved(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    *,
    old_main: Path,
    new_main: Path,
) -> None:
    normalized = []
    for item in before:
        value = dict(item)
        if Path(str(value["path"])).resolve() == old_main.resolve():
            value["path"] = str(new_main.resolve())
        normalized.append(value)
    if _worktree_full_identity(normalized) != _worktree_full_identity(after):
        raise ValueError("worktree branch, commit, or dirty state was not preserved")


def _worktree_identity(items: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return sorted(
        (str(item["path"]), str(item["branch"]), str(item["head"]))
        for item in items
    )


def _worktree_full_identity(
    items: list[dict[str, Any]],
) -> list[tuple[str, str, str, str]]:
    return sorted(
        (
            str(item["path"]), str(item["branch"]), str(item["head"]),
            str(item["status_sha256"]),
        )
        for item in items
    )


def _profile_mappings_match(
    store: LocalProfileStore,
    mappings: list[dict[str, Any]],
    expected_ref: str,
) -> bool:
    for item in mappings:
        binding = store.load(item["profile_id"]).get(
            "factor_workspace_binding"
        ) or {}
        if (
            binding.get("binding_id") != item["binding_id"]
            or binding.get("canonical_repo_ref") != expected_ref
            or binding.get("git_common_dir") != item["new_git_common_dir"]
        ):
            return False
    return True


def _validate_plan(plan: dict[str, Any]) -> None:
    declared = str(plan.get("plan_hash") or "")
    body = dict(plan)
    body.pop("plan_hash", None)
    if (
        plan.get("schema_version") != 1
        or plan.get("operation") != "personal_factor_workspace_migration"
        or declared != json_hash(body)
    ):
        raise ValueError("personal workspace migration plan is invalid")


def _load_receipt(root: Path, migration_id: str) -> dict[str, Any]:
    validate_local_identifier(migration_id, "migration_id")
    value = read_json(_receipt_path(root, migration_id))
    if not value:
        raise ValueError("personal workspace migration receipt not found")
    body = dict(value)
    declared = str(body.pop("receipt_hash", ""))
    if declared != json_hash(body):
        raise ValueError("personal workspace migration receipt is corrupt")
    return value


def _receipt_path(root: Path, migration_id: str) -> Path:
    return (
        validate_client_root(root)
        / "profiles"
        / "personal-workspace-migrations"
        / f"{migration_id}.json"
    )


def _rollback_receipt_path(root: Path, migration_id: str) -> Path:
    return (
        validate_client_root(root)
        / "profiles"
        / "personal-workspace-migrations"
        / f"{migration_id}.rollback.json"
    )


def _common_from_snapshot(items: list[dict[str, Any]]) -> str:
    return str(items[0]["git_common_dir"]) if items else ""


def _common_dir(repo: Path) -> str:
    raw = _git_value(repo, "rev-parse", "--git-common-dir")
    path = Path(raw)
    return str((repo / path).resolve() if not path.is_absolute() else path.resolve())


def _tree_bytes(root: Path) -> int:
    return sum(
        path.lstat().st_size
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _device(path: Path) -> int:
    candidate = path
    while not candidate.exists():
        candidate = candidate.parent
    return candidate.stat().st_dev


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        env={
            **os.environ,
            "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            f"git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout


def _git_value(repo: Path, *args: str) -> str:
    return _git(repo, *args).strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        env={
            **os.environ,
            "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            f"git {' '.join(args)} failed: "
            + result.stderr.decode(errors="replace").strip()
        )
    return result.stdout

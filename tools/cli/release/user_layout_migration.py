"""One-principal FactorTester user-tree layout migration."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from uuid import uuid4

from .factor_worktree import (
    CanonicalFactorRepoStore,
    repair_factor_worktree_binding,
    verify_factor_worktree_binding,
)
from .local_profile import LocalProfileStore
from .local_profile_contracts import validate_local_identifier
from .locations import validate_client_root
from .storage import json_hash, read_json, utc_now, write_json
from .workspace_inventory import available_bytes


def default_user_root(principal_ref: str) -> Path:
    validate_local_identifier(principal_ref, "principal_ref")
    return (
        Path.home() / "Documents" / "FactorTester" / "users"
        / principal_ref
    )


def default_user_factor_library(principal_ref: str) -> Path:
    return (
        default_user_root(principal_ref)
        / "personal-workspace"
        / "factor-library"
    )


def default_user_profile_root(
    principal_ref: str,
    profile_id: str,
) -> Path:
    validate_local_identifier(profile_id, "profile_id")
    return default_user_root(principal_ref) / "profiles" / profile_id


def user_layout_status(
    client_root: Path,
    principal_ref: str,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    settings = CanonicalFactorRepoStore(root).load()
    if settings["owner_ref"] != principal_ref:
        raise ValueError("canonical workspace owner does not match principal")
    canonical = Path(str(settings["path"])).resolve()
    snapshot = _repo_snapshot(canonical)
    owned = _owned_profiles(
        LocalProfileStore(root),
        principal_ref,
        str(settings["canonical_repo_ref"]),
    )
    profiles = [_compact_profile(item) for item in owned]
    target_user = default_user_root(principal_ref).resolve()
    return {
        "schema_version": 1,
        "principal_ref": principal_ref,
        "source_layout": {
            "canonical": str(canonical),
            "profile_roots": {
                item["profile_id"]: item["workspace_root"]
                for item in profiles
            },
        },
        "target_layout": {
            "user_root": str(target_user),
            "personal_workspace": str(
                target_user / "personal-workspace"
            ),
            "factor_library": str(
                target_user / "personal-workspace/factor-library"
            ),
            "profiles_root": str(target_user / "profiles"),
            "legacy_quarantine": str(
                target_user / "legacy-quarantine"
            ),
        },
        "canonical": {
            "source": str(canonical),
            "target": str(
                target_user / "personal-workspace/factor-library"
            ),
            "branch": snapshot["main"]["branch"],
            "head": snapshot["main"]["head"],
            "status_sha256": snapshot["main"]["status_sha256"],
            "dirty_file_count": snapshot["main"]["dirty_file_count"],
            "canonical_repo_ref": settings["canonical_repo_ref"],
        },
        "profiles": profiles,
        "worktrees": snapshot["worktrees"],
    }


def plan_user_layout_migration(
    client_root: Path,
    principal_ref: str,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    status = user_layout_status(root, principal_ref)
    target = status["target_layout"]
    canonical = dict(status["canonical"])
    profiles = []
    worktree_targets: dict[str, str] = {}
    legacy = []
    collisions = []
    move_sources = [Path(canonical["source"])]
    move_targets = [Path(canonical["target"])]
    for profile in status["profiles"]:
        profile_id = str(profile["profile_id"])
        source_root = Path(str(profile["workspace_root"])).resolve()
        target_root = Path(target["profiles_root"]) / profile_id
        binding = profile.get("factor_workspace_binding") or {}
        source_worktree = str(binding.get("worktree_path") or "")
        target_worktree = str(target_root / "factor-worktree") if binding else ""
        item = {
            "profile_id": profile_id,
            "source_root": str(source_root),
            "target_root": str(target_root),
            "source_worktree": source_worktree,
            "target_worktree": target_worktree,
            "source_research": str(
                Path(str(binding.get("research_root") or source_root / "research"))
            ),
            "target_research": str(target_root / "research"),
            "source_local_data": str(source_root / "local-data"),
            "target_local_data": str(target_root / "local-data"),
            "research_present": (source_root / "research").exists(),
            "local_data_present": (source_root / "local-data").exists(),
            "agent_ids": [
                str(agent_id) for agent_id in profile["agent_ids"]
            ],
        }
        profiles.append(item)
        move_sources.append(source_root)
        move_targets.append(target_root)
        if source_worktree:
            worktree_targets[str(Path(source_worktree).resolve())] = (
                target_worktree
            )
        legacy.extend(_legacy_entries(
            profile,
            source_root=source_root,
            target_quarantine=(
                Path(target["legacy_quarantine"]) / profile_id
            ),
            active_worktree=(
                Path(source_worktree).resolve()
                if source_worktree else None
            ),
        ))
    worktrees = []
    for item in status["worktrees"]:
        old_path = str(Path(item["path"]).resolve())
        new_path = (
            canonical["target"]
            if old_path == canonical["source"]
            else worktree_targets.get(old_path, old_path)
        )
        worktrees.append({
            "old_path": old_path,
            "new_path": new_path,
            "branch": item["branch"],
            "head": item["head"],
            "status_sha256": item["status_sha256"],
            "dirty_file_count": item["dirty_file_count"],
        })
    for destination in [*move_targets, *(
        Path(item["target"]) for item in legacy
    )]:
        if destination.exists() and destination not in move_sources:
            collisions.append(str(destination))
    all_sources = [*move_sources, *(
        Path(item["source"]) for item in legacy
    )]
    devices = {_device(path) for path in all_sources}
    devices.add(_device(Path(target["user_root"]).parent))
    required = sum(_tree_bytes(path) for path in all_sources)
    capacity = {
        "required_bytes": required,
        "available_bytes": available_bytes(Path(target["user_root"])),
        "same_volume": len(devices) == 1,
        "ok": len(devices) == 1,
    }
    body = {
        "schema_version": 1,
        "operation": "principal_user_layout_migration",
        "principal_ref": principal_ref,
        "source_layout": status["source_layout"],
        "target_layout": target,
        "canonical": canonical,
        "profiles": profiles,
        "worktrees": worktrees,
        "legacy_quarantine": legacy,
        "historical_receipts_sha256": _historical_receipts_hash(root),
        "capacity": capacity,
        "collisions": sorted(collisions),
    }
    body["ready"] = not collisions and capacity["ok"]
    body["plan_hash"] = json_hash(body)
    return body


def apply_user_layout_migration(
    client_root: Path,
    plan: dict[str, Any],
    *,
    checkpoint=None,
) -> dict[str, Any]:
    _validate_plan(plan)
    if not plan["ready"]:
        raise ValueError("user layout migration plan is not ready")
    root = validate_client_root(client_root)
    current = plan_user_layout_migration(root, str(plan["principal_ref"]))
    if _plan_state_hash(current) != _plan_state_hash(plan):
        raise ValueError("user layout changed after migration plan")
    migration_id = uuid4().hex
    backup_root = (
        root / "profiles" / "user-layout-migration-backups"
        / migration_id
    )
    receipt_path = _receipt_path(root, migration_id)
    store = LocalProfileStore(root)
    settings_store = CanonicalFactorRepoStore(root)
    _backup_metadata(root, backup_root, plan["profiles"])
    completed: list[tuple[Path, Path]] = []
    try:
        for item in plan["legacy_quarantine"]:
            _move(Path(item["source"]), Path(item["target"]))
            completed.append((Path(item["source"]), Path(item["target"])))
        _checkpoint(checkpoint, "after_legacy_quarantine")
        for item in plan["profiles"]:
            source_root = Path(item["source_root"])
            target_root = Path(item["target_root"])
            _move(source_root, target_root)
            completed.append((source_root, target_root))
            if item["source_worktree"]:
                relocated = target_root / Path(
                    item["source_worktree"]
                ).relative_to(source_root)
                fixed = Path(item["target_worktree"])
                fixed.parent.mkdir(parents=True, exist_ok=True)
                if relocated != fixed:
                    _move(relocated, fixed)
                    completed.append((relocated, fixed))
                    _remove_empty_parents(relocated.parent, target_root)
        _checkpoint(checkpoint, "after_profiles")
        canonical_source = Path(plan["canonical"]["source"])
        canonical_target = Path(plan["canonical"]["target"])
        _move(canonical_source, canonical_target)
        completed.append((canonical_source, canonical_target))
        _checkpoint(checkpoint, "after_canonical")
        _repair_worktrees(
            canonical_target,
            [Path(item["new_path"]) for item in plan["worktrees"][1:]],
        )
        new_settings = settings_store.register(
            canonical_target,
            owner_ref=str(plan["principal_ref"]),
        )
        new_common = _common_dir(canonical_target)
        profile_mapping, claim_mapping = _update_profiles(
            store,
            plan,
            new_ref=str(new_settings["canonical_repo_ref"]),
            new_common=new_common,
        )
        _checkpoint(checkpoint, "after_metadata")
        after = _repo_snapshot(canonical_target)
        _assert_worktrees_preserved(plan["worktrees"], after["worktrees"])
        if _historical_receipts_hash(root) != plan[
            "historical_receipts_sha256"
        ]:
            raise ValueError("historical receipts changed during migration")
        body = {
            "schema_version": 1,
            "operation": "principal_user_layout_migration",
            "migration_id": migration_id,
            "status": "applied",
            "principal_ref": plan["principal_ref"],
            "source_layout": plan["source_layout"],
            "target_layout": plan["target_layout"],
            "canonical_mapping": {
                "old_path": plan["canonical"]["source"],
                "new_path": plan["canonical"]["target"],
                "old_ref": plan["canonical"]["canonical_repo_ref"],
                "new_ref": new_settings["canonical_repo_ref"],
                "new_git_common_dir": new_common,
            },
            "profile_mapping": profile_mapping,
            "worktree_mapping": plan["worktrees"],
            "legacy_quarantine": plan["legacy_quarantine"],
            "claim_receipt_mapping": claim_mapping,
            "metadata_backup_ref": backup_root.resolve().as_uri(),
            "historical_receipts_sha256": plan[
                "historical_receipts_sha256"
            ],
            "preservation": {
                "branches": True,
                "commits": True,
                "uncommitted": True,
                "research": all(
                    not item["research_present"]
                    or Path(item["target_research"]).exists()
                    for item in plan["profiles"]
                ),
                "local_data": all(
                    not item["local_data_present"]
                    or Path(item["target_local_data"]).exists()
                    for item in plan["profiles"]
                ),
                "legacy_quarantined_not_deleted": True,
            },
            "plan_hash": plan["plan_hash"],
            "applied_at": utc_now(),
        }
        receipt = {**body, "receipt_hash": json_hash(body)}
        write_json(receipt_path, receipt)
        receipt_path.chmod(0o600)
        return {**receipt, "receipt_ref": receipt_path.resolve().as_uri()}
    except Exception:
        _restore_metadata(root, backup_root, plan["profiles"])
        _reverse_moves(completed)
        canonical = Path(plan["canonical"]["source"])
        if canonical.is_dir():
            _repair_worktrees(
                canonical,
                [Path(item["old_path"]) for item in plan["worktrees"][1:]],
            )
        raise


def verify_user_layout_migration(
    client_root: Path,
    migration_id: str,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    receipt = _load_receipt(root, migration_id)
    canonical = Path(receipt["canonical_mapping"]["new_path"])
    settings = CanonicalFactorRepoStore(root).load()
    snapshot = _repo_snapshot(canonical) if canonical.is_dir() else None
    store = LocalProfileStore(root)
    checks = {
        "canonical_target_active": (
            canonical.is_dir()
            and Path(str(settings["path"])).resolve() == canonical
            and settings["canonical_repo_ref"]
                == receipt["canonical_mapping"]["new_ref"]
        ),
        "worktrees_preserved_and_repaired": bool(
            snapshot
            and _worktrees_match(
                receipt["worktree_mapping"], snapshot["worktrees"]
            )
        ),
        "profiles_relocated": all(
            _profile_mapping_matches(store, item)
            for item in receipt["profile_mapping"]
        ),
        "factor_worktree_bindings_valid": all(
            (
                not item["target_worktree"]
                or verify_factor_worktree_binding(
                    root, item["profile_id"]
                )["valid"]
            )
            for item in receipt["profile_mapping"]
        ),
        "research_and_local_data_preserved": all(
            (
                not item["research_present"]
                or Path(item["target_research"]).exists()
            ) and (
                not item["local_data_present"]
                or Path(item["target_local_data"]).exists()
            )
            for item in receipt["profile_mapping"]
        ),
        "legacy_quarantined_not_deleted": all(
            not Path(item["source"]).exists()
            and Path(item["target"]).exists()
            for item in receipt["legacy_quarantine"]
        ),
        "historical_receipts_unchanged": (
            _historical_receipts_hash(root)
            == receipt["historical_receipts_sha256"]
        ),
        "receipt_immutable": (
            _load_receipt(root, migration_id)["receipt_hash"]
            == receipt["receipt_hash"]
        ),
    }
    return {
        "schema_version": 1,
        "operation": "verify_principal_user_layout_migration",
        "migration_id": migration_id,
        "valid": all(checks.values()),
        "checks": checks,
        "source_layout": receipt["source_layout"],
        "target_layout": receipt["target_layout"],
        "receipt_ref": _receipt_path(root, migration_id).resolve().as_uri(),
    }


def rollback_user_layout_migration(
    client_root: Path,
    migration_id: str,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    receipt = _load_receipt(root, migration_id)
    rollback_path = _rollback_receipt_path(root, migration_id)
    existing = read_json(rollback_path)
    if existing:
        return {**existing, "receipt_ref": rollback_path.resolve().as_uri()}
    plan = {
        "profiles": receipt["profile_mapping"],
        "worktrees": receipt["worktree_mapping"],
        "canonical": {
            "source": receipt["canonical_mapping"]["old_path"],
            "target": receipt["canonical_mapping"]["new_path"],
        },
        "legacy_quarantine": receipt["legacy_quarantine"],
    }
    backup_root = Path(
        str(receipt["metadata_backup_ref"]).removeprefix("file://")
    )
    completed: list[tuple[Path, Path]] = []
    try:
        canonical_old = Path(plan["canonical"]["source"])
        canonical_new = Path(plan["canonical"]["target"])
        _move(canonical_new, canonical_old)
        completed.append((canonical_new, canonical_old))
        for item in reversed(plan["profiles"]):
            target_root = Path(item["target_root"])
            source_root = Path(item["source_root"])
            if item["source_worktree"]:
                fixed = Path(item["target_worktree"])
                old_relative = target_root / Path(
                    item["source_worktree"]
                ).relative_to(source_root)
                if fixed != old_relative:
                    _move(fixed, old_relative)
                    completed.append((fixed, old_relative))
            _move(target_root, source_root)
            completed.append((target_root, source_root))
        for item in reversed(plan["legacy_quarantine"]):
            _move(Path(item["target"]), Path(item["source"]))
            completed.append((Path(item["target"]), Path(item["source"])))
        _repair_worktrees(
            canonical_old,
            [Path(item["old_path"]) for item in plan["worktrees"][1:]],
        )
        _restore_metadata(root, backup_root, plan["profiles"])
        body = {
            "schema_version": 1,
            "operation": "rollback_principal_user_layout_migration",
            "migration_id": migration_id,
            "status": "rolled_back",
            "branches_retained": True,
            "commits_retained": True,
            "uncommitted_retained": True,
            "research_retained": True,
            "local_data_retained": True,
            "legacy_restored": True,
            "rolled_back_at": utc_now(),
        }
        value = {**body, "receipt_hash": json_hash(body)}
        write_json(rollback_path, value)
        rollback_path.chmod(0o600)
        return {**value, "receipt_ref": rollback_path.resolve().as_uri()}
    except Exception:
        _reverse_moves(completed)
        raise


def _owned_profiles(
    store: LocalProfileStore,
    principal_ref: str,
    canonical_ref: str,
) -> list[dict[str, Any]]:
    selected = []
    for profile in store.list():
        session = profile.get("session_binding") or {}
        binding = profile.get("factor_workspace_binding") or {}
        if (
            session.get("principal_ref") == principal_ref
            or binding.get("canonical_repo_ref") == canonical_ref
        ):
            selected.append(profile)
    return selected


def _compact_profile(profile: dict[str, Any]) -> dict[str, Any]:
    binding = profile.get("factor_workspace_binding") or {}
    return {
        "profile_id": profile["profile_id"],
        "workspace_root": profile["workspace_root"],
        "agent_ids": [
            agent["agent_id"] for agent in profile["agents"]
        ],
        "workspaces": [
            {
                "workspace_id": item["workspace_id"],
                "path": item["path"],
            }
            for item in profile["workspaces"]
        ],
        "factor_workspace_binding": (
            {
                key: binding[key]
                for key in (
                    "binding_id", "canonical_repo_ref", "base_commit",
                    "branch", "worktree_path", "research_root",
                    "git_common_dir", "sync_policy",
                )
            }
            if binding else {}
        ),
    }


def _legacy_entries(
    profile: dict[str, Any],
    *,
    source_root: Path,
    target_quarantine: Path,
    active_worktree: Path | None,
) -> list[dict[str, Any]]:
    candidates: dict[Path, list[str]] = {}
    for workspace in profile["workspaces"]:
        path = Path(str(workspace["path"])).resolve()
        if path.exists() and _within(path, source_root):
            candidates.setdefault(path, []).append(
                f"workspace:{workspace['workspace_id']}"
            )
    for path in source_root.rglob("*unsafe-backup*"):
        if path.is_dir():
            candidates.setdefault(path.resolve(), []).append("unsafe_backup")
    roots = []
    for path in sorted(candidates, key=lambda value: len(value.parts)):
        if path == source_root or (
            active_worktree is not None
            and (path == active_worktree or _within(active_worktree, path))
        ):
            continue
        if any(_within(path, parent) for parent in roots):
            continue
        roots.append(path)
    entries = []
    for index, path in enumerate(roots):
        entries.append({
            "profile_id": profile["profile_id"],
            "source": str(path),
            "target": str(
                target_quarantine / f"{index:03d}-{path.name}"
            ),
            "refs": sorted(candidates[path]),
            "content_sha256": _content_hash(path),
            "bytes": _tree_bytes(path),
        })
    return entries


def _update_profiles(
    store: LocalProfileStore,
    plan: dict[str, Any],
    *,
    new_ref: str,
    new_common: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    legacy_by_profile: dict[str, set[str]] = {}
    for item in plan["legacy_quarantine"]:
        legacy_by_profile.setdefault(item["profile_id"], set()).add(
            item["source"]
        )
    mappings, claims = [], []
    for item in plan["profiles"]:
        profile = store.load(item["profile_id"])
        profile["workspace_root"] = item["target_root"]
        removed = legacy_by_profile.get(item["profile_id"], set())
        profile["workspaces"] = [
            workspace for workspace in profile["workspaces"]
            if str(Path(workspace["path"]).resolve()) not in removed
        ]
        binding = profile.get("factor_workspace_binding") or {}
        if binding:
            binding["canonical_repo_ref"] = new_ref
            binding["worktree_path"] = item["target_worktree"]
            binding["research_root"] = item["target_research"]
            binding["git_common_dir"] = new_common
            profile["factor_workspace_binding"] = binding
        saved = store.save(profile)
        if binding:
            repair = repair_factor_worktree_binding(
                store.root.parent,
                saved["profile_id"],
                run_pyright=False,
                refresh_manifest=False,
            )
            if not repair["valid"]:
                raise ValueError(
                    "relocated factor worktree repair failed: "
                    + json.dumps(repair["checks"], sort_keys=True)
                )
        mapping = {**item, "removed_workspace_paths": sorted(removed)}
        mapping["profile_sha256"] = json_hash(saved)
        mappings.append(mapping)
        for agent in saved["agents"]:
            old_path = (
                store.root / "claim-receipts" / saved["profile_id"]
                / f"{agent['agent_id']}.json"
            )
            old_hash = (
                sha256(old_path.read_bytes()).hexdigest()
                if old_path.is_file() else ""
            )
            claim = store.claim_agent(
                saved["profile_id"], agent["agent_id"]
            )
            claims.append({
                "profile_id": saved["profile_id"],
                "agent_id": agent["agent_id"],
                "old_receipt_sha256": old_hash,
                "new_receipt_hash": claim["receipt_hash"],
                "receipt_ref": claim["receipt_ref"],
            })
    return mappings, claims


def _profile_mapping_matches(
    store: LocalProfileStore,
    item: dict[str, Any],
) -> bool:
    profile = store.load(item["profile_id"])
    binding = profile.get("factor_workspace_binding") or {}
    return (
        profile["workspace_root"] == item["target_root"]
        and (
            not item["target_worktree"]
            or binding.get("worktree_path") == item["target_worktree"]
        )
        and json_hash(profile) == item["profile_sha256"]
    )


def _backup_metadata(
    root: Path,
    backup: Path,
    profiles: list[dict[str, Any]],
) -> None:
    backup.mkdir(parents=True)
    settings = (
        root / "settings" / "factor-workspace.json"
    )
    shutil.copy2(settings, backup / "factor-workspace.json")
    (backup / "profiles").mkdir()
    for item in profiles:
        source = root / "profiles" / f"{item['profile_id']}.json"
        shutil.copy2(source, backup / "profiles" / source.name)
    claims = root / "profiles" / "claim-receipts"
    if claims.is_dir():
        shutil.copytree(claims, backup / "claim-receipts")


def _restore_metadata(
    root: Path,
    backup: Path,
    profiles: list[dict[str, Any]],
) -> None:
    shutil.copy2(
        backup / "factor-workspace.json",
        root / "settings" / "factor-workspace.json",
    )
    for item in profiles:
        shutil.copy2(
            backup / "profiles" / f"{item['profile_id']}.json",
            root / "profiles" / f"{item['profile_id']}.json",
        )
    claims = root / "profiles" / "claim-receipts"
    if claims.exists():
        shutil.rmtree(claims)
    if (backup / "claim-receipts").is_dir():
        shutil.copytree(backup / "claim-receipts", claims)


def _repo_snapshot(repo: Path) -> dict[str, Any]:
    rows = _worktree_rows(repo)
    items = []
    for row in rows:
        path = Path(row["worktree"]).resolve()
        status = _git_bytes(path, "status", "--porcelain=v1", "-z")
        items.append({
            "path": str(path),
            "branch": row.get("branch", "").removeprefix("refs/heads/"),
            "head": row.get("HEAD", ""),
            "status_sha256": sha256(status).hexdigest(),
            "dirty_file_count": len(
                [value for value in status.split(b"\0") if value]
            ),
        })
    return {"main": items[0], "worktrees": items}


def _assert_worktrees_preserved(
    planned: list[dict[str, Any]],
    observed: list[dict[str, Any]],
) -> None:
    if not _worktrees_match(planned, observed):
        raise ValueError("worktree paths, branches, commits, or dirty state changed")


def _worktrees_match(
    planned: list[dict[str, Any]],
    observed: list[dict[str, Any]],
) -> bool:
    expected = sorted(
        (
            str(Path(item["new_path"]).resolve()),
            item["branch"], item["head"], item["status_sha256"],
        )
        for item in planned
    )
    actual = sorted(
        (
            str(Path(item["path"]).resolve()),
            item["branch"], item["head"], item["status_sha256"],
        )
        for item in observed
    )
    return expected == actual


def _repair_worktrees(repo: Path, linked: list[Path]) -> None:
    _git(repo, "worktree", "repair", *(str(path) for path in linked))


def _move(source: Path, target: Path) -> None:
    if not source.exists():
        raise ValueError(f"migration source is missing: {source}")
    if target.exists():
        raise ValueError(f"migration target exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)


def _reverse_moves(completed: list[tuple[Path, Path]]) -> None:
    for source, target in reversed(completed):
        if target.exists() and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, source)


def _remove_empty_parents(path: Path, stop: Path) -> None:
    current = path
    while current != stop and _within(current, stop):
        if not current.is_dir() or any(current.iterdir()):
            return
        current.rmdir()
        current = current.parent


def _historical_receipts_hash(root: Path) -> str:
    receipts = root / "profiles"
    digest = sha256()
    if not receipts.is_dir():
        return digest.hexdigest()
    for path in sorted(receipts.rglob("*.json")):
        relative = path.relative_to(receipts)
        if relative.parts[:1] in {
            ("claim-receipts",),
            ("user-layout-migration-backups",),
            ("user-layout-migrations",),
        } or len(relative.parts) == 1:
            continue
        digest.update(str(relative).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _validate_plan(plan: dict[str, Any]) -> None:
    body = dict(plan)
    declared = str(body.pop("plan_hash", ""))
    if (
        plan.get("schema_version") != 1
        or plan.get("operation") != "principal_user_layout_migration"
        or declared != json_hash(body)
    ):
        raise ValueError("principal user layout migration plan is invalid")


def _plan_state_hash(plan: dict[str, Any]) -> str:
    value = dict(plan)
    value.pop("plan_hash", None)
    capacity = dict(value["capacity"])
    capacity.pop("available_bytes", None)
    value["capacity"] = capacity
    return json_hash(value)


def _load_receipt(root: Path, migration_id: str) -> dict[str, Any]:
    validate_local_identifier(migration_id, "migration_id")
    value = read_json(_receipt_path(root, migration_id))
    if not value:
        raise ValueError("principal user layout migration receipt not found")
    body = dict(value)
    declared = str(body.pop("receipt_hash", ""))
    if declared != json_hash(body):
        raise ValueError("principal user layout migration receipt is corrupt")
    return value


def _receipt_path(root: Path, migration_id: str) -> Path:
    return (
        validate_client_root(root) / "profiles"
        / "user-layout-migrations" / f"{migration_id}.json"
    )


def _rollback_receipt_path(root: Path, migration_id: str) -> Path:
    return (
        validate_client_root(root) / "profiles"
        / "user-layout-migrations" / f"{migration_id}.rollback.json"
    )


def _content_hash(root: Path) -> str:
    digest = sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        digest.update(str(relative).encode())
        if path.is_symlink():
            digest.update(b"link:")
            digest.update(str(path.readlink()).encode())
        elif path.is_file():
            digest.update(b"file:")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _tree_bytes(root: Path) -> int:
    return sum(
        path.lstat().st_size for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _common_dir(repo: Path) -> str:
    value = Path(_git(repo, "rev-parse", "--git-common-dir").strip())
    return str(
        (repo / value).resolve() if not value.is_absolute()
        else value.resolve()
    )


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


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _device(path: Path) -> int:
    current = path
    while not current.exists():
        current = current.parent
    return current.stat().st_dev


def _checkpoint(callback, name: str) -> None:
    if callback is not None:
        callback(name)


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

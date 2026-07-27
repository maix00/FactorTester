"""Plan and apply one Profile-isolated strategy Actor worktree."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any
import uuid

from .local_profile import LocalProfileStore
from .storage import json_hash, utc_now, write_json
from .strategy_workspace import CanonicalStrategyRepoStore


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def plan_strategy_worktree_binding(
    client_root: Path,
    profile_id: str,
    *,
    branch: str = "",
    source_sync_enabled: bool = False,
) -> dict[str, Any]:
    store = LocalProfileStore(client_root)
    profile = store.load(profile_id)
    settings = CanonicalStrategyRepoStore(client_root).load()
    repo = Path(str(settings["path"])).resolve()
    owner = str(settings["owner_ref"])
    session = profile.get("session_binding") or {}
    if session.get("principal_ref") != owner:
        raise ValueError("strategy repository owner does not match Profile")
    profile_root = Path(str(profile["workspace_root"])).resolve()
    target = profile_root / "strategy-worktree"
    branch_name = branch or f"strategy/{profile_id}"
    if ".." in Path(branch_name).parts:
        raise ValueError("strategy branch is invalid")
    existing = profile.get("strategy_workspace_binding") or {}
    idempotent = bool(
        existing
        and existing.get("canonical_repo_ref") == settings["canonical_repo_ref"]
        and existing.get("branch") == branch_name
        and Path(str(existing.get("worktree_path"))).resolve() == target
    )
    branch_exists = bool(_git(repo, "branch", "--list", branch_name))
    target_exists = target.exists()
    collisions = [] if idempotent else [
        item for item, present in (("branch_exists", branch_exists), ("target_exists", target_exists))
        if present
    ]
    body = {
        "schema_version": 1,
        "profile_id": profile_id,
        "canonical_repo_ref": settings["canonical_repo_ref"],
        "canonical_settings_hash": json_hash(settings),
        "owner_ref": owner,
        "base_commit": _git(repo, "rev-parse", "HEAD"),
        "branch": branch_name,
        "worktree_path": str(target),
        "research_root": str(profile_root / "research"),
        "git_common_dir": str((repo / _git(repo, "rev-parse", "--git-common-dir")).resolve()),
        "sync_policy": {
            "source_sync_enabled": bool(source_sync_enabled),
            "auto_push": False,
            "auto_merge": False,
        },
        "checks": {
            "owner_matches": True,
            "target_within_profile_root": target.parent == profile_root,
            "collisions": collisions,
        },
        "idempotent": idempotent,
    }
    body["ready"] = not collisions and body["checks"]["target_within_profile_root"]
    plan = {**body, "plan_hash": json_hash(body)}
    plan["binding_id"] = f"strategy-worktree-{plan['plan_hash'][:16]}"
    return plan


def apply_strategy_worktree_binding(client_root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    if not plan.get("ready"):
        raise ValueError("strategy worktree plan is not ready")
    store = LocalProfileStore(client_root)
    profile = store.load(str(plan["profile_id"]))
    settings = CanonicalStrategyRepoStore(client_root).load()
    if json_hash(settings) != plan.get("canonical_settings_hash"):
        raise ValueError("canonical strategy repo settings changed after plan")
    repo = Path(str(settings["path"])).resolve()
    target = Path(str(plan["worktree_path"])).resolve()
    existing = profile.get("strategy_workspace_binding") or {}
    if existing.get("binding_id") == plan.get("binding_id") and target.is_dir():
        return dict(existing)
    target.parent.mkdir(parents=True, exist_ok=True)
    branch = str(plan["branch"])
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(target), str(plan["base_commit"])],
        check=True, capture_output=True,
    )
    manifest = {
        "schema_version": 1,
        "kind": "profile-strategy-worktree",
        "profile_id": str(plan["profile_id"]),
        "owner_ref": str(plan["owner_ref"]),
        "canonical_repo_ref": str(plan["canonical_repo_ref"]),
        "base_commit": str(plan["base_commit"]),
        "created_at": utc_now(),
    }
    write_json(target / ".strategy_workspace" / "manifest.json", manifest)
    receipt = {**plan, "applied_at": utc_now(), "receipt_id": str(uuid.uuid4())}
    receipt["receipt_hash"] = json_hash(receipt)
    profile["strategy_workspace_binding"] = {
        key: receipt[key]
        for key in (
            "binding_id", "canonical_repo_ref", "base_commit", "branch",
            "worktree_path", "research_root", "git_common_dir", "owner_ref",
            "sync_policy", "receipt_hash",
        )
    }
    receipt_path = store.root / "worktree-receipts" / str(plan["profile_id"])
    receipt_path.mkdir(parents=True, exist_ok=True)
    path = receipt_path / f"{plan['binding_id']}.json"
    write_json(path, receipt)
    profile["strategy_workspace_binding"]["receipt_ref"] = path.resolve().as_uri()
    store.save(profile)
    return {**receipt, "receipt_ref": path.resolve().as_uri()}

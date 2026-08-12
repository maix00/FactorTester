"""Verification and explicit rollback for Profile Strategy worktrees."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from .local_profile import LocalProfileStore
from .storage import json_hash, read_json, utc_now
from .strategy_workspace import CanonicalStrategyRepoStore


def verify_strategy_worktree_binding(client_root: Path, profile_id: str) -> dict[str, Any]:
    profile = LocalProfileStore(client_root).load(profile_id)
    binding = profile.get("strategy_workspace_binding") or {}
    if not binding:
        return {"valid": False, "reason": "strategy worktree is not bound", "profile_id": profile_id}
    settings = CanonicalStrategyRepoStore(client_root).load()
    target = Path(str(binding.get("worktree_path") or "")).resolve()
    manifest = read_json(target / ".strategy_workspace" / "manifest.json")
    checks = {
        "target_exists": target.is_dir(),
        "owner_matches": binding.get("owner_ref") == settings.get("owner_ref"),
        "canonical_matches": binding.get("canonical_repo_ref") == settings.get("canonical_repo_ref"),
        "manifest_valid": isinstance(manifest, dict),
        "manifest_hash": False,
    }
    if isinstance(manifest, dict):
        body = {key: value for key, value in manifest.items() if key != "manifest_hash"}
        checks["manifest_hash"] = manifest.get("manifest_hash") == json_hash(body)
    return {
        "valid": all(checks.values()),
        "profile_id": profile_id,
        "worktree_path": str(target),
        "checks": checks,
    }


def rollback_strategy_worktree_binding(client_root: Path, profile_id: str) -> dict[str, Any]:
    store = LocalProfileStore(client_root)
    profile = store.load(profile_id)
    binding = profile.get("strategy_workspace_binding") or {}
    if not binding:
        return {"status": "not_bound", "profile_id": profile_id}
    target = Path(str(binding.get("worktree_path") or "")).resolve()
    root = Path(str(profile["workspace_root"])).resolve()
    if target != root / "strategy-worktree":
        raise ValueError("refusing to remove a worktree outside the Profile workspace")
    settings = CanonicalStrategyRepoStore(client_root).load()
    repo = Path(str(settings["path"])).resolve()
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(target)],
        check=True, capture_output=True,
    )
    profile.pop("strategy_workspace_binding", None)
    store.save(profile)
    return {"status": "rolled_back", "profile_id": profile_id, "removed_path": str(target), "at": utc_now()}

"""Current principal-scoped FactorTester filesystem contract."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import subprocess
from typing import Any

from .factor_worktree import CanonicalFactorRepoStore
from .local_profile import LocalProfileStore
from .local_profile_contracts import validate_local_identifier
from .locations import validate_client_root


_GIT_ENV = {
    "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1",
    "GIT_TERMINAL_PROMPT": "0",
}


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


def default_user_strategy_library(principal_ref: str) -> Path:
    """Return the personal strategy source repository path.

    Strategies are executable actors, not factor source, so they have an
    independent repository and manifest namespace.
    """
    return (
        default_user_root(principal_ref)
        / "personal-workspace"
        / "strategy-library"
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
    """Return the active layout without probing obsolete locations."""
    root = validate_client_root(client_root)
    user_root = default_user_root(principal_ref).resolve()
    factor_library = default_user_factor_library(principal_ref).resolve()
    strategy_library = default_user_strategy_library(principal_ref).resolve()
    profiles_root = (user_root / "profiles").resolve()
    settings = CanonicalFactorRepoStore(root).load()
    canonical = Path(str(settings["path"])).resolve()
    if settings["owner_ref"] != principal_ref:
        raise ValueError("canonical factor library owner does not match")
    if canonical != factor_library:
        raise ValueError(
            "canonical factor library is outside the unified user layout"
        )

    profiles = []
    for profile in LocalProfileStore(root).list():
        session = profile.get("session_binding") or {}
        binding = profile.get("factor_workspace_binding") or {}
        strategy_binding = profile.get("strategy_workspace_binding") or {}
        if session.get("principal_ref") != principal_ref:
            continue
        expected = default_user_profile_root(
            principal_ref, str(profile["profile_id"])
        ).resolve()
        workspace = Path(str(profile["workspace_root"])).resolve()
        if workspace != expected:
            raise ValueError(
                f"profile {profile['profile_id']} is outside the unified "
                "user layout"
            )
        worktree = str(binding.get("worktree_path") or "")
        if worktree and Path(worktree).resolve() != (
            expected / "factor-worktree"
            ):
            raise ValueError(
                f"profile {profile['profile_id']} factor worktree is "
                "outside its unified profile root"
            )
        strategy_worktree = str(strategy_binding.get("worktree_path") or "")
        if strategy_worktree and Path(strategy_worktree).resolve() != (
            expected / "strategy-worktree"
        ):
            raise ValueError(
                f"profile {profile['profile_id']} strategy worktree is "
                "outside its unified profile root"
            )
        profiles.append({
            "profile_id": profile["profile_id"],
            "display_name": profile["display_name"],
            "workspace_root": str(workspace),
            "agent_ids": [
                str(item["agent_id"])
                for item in profile.get("agents", [])
            ],
            "branch": str(binding.get("branch") or ""),
            "worktree_path": worktree,
            "research_root": str(binding.get("research_root") or ""),
            "strategy_branch": str(strategy_binding.get("branch") or ""),
            "strategy_worktree_path": strategy_worktree,
            "strategy_research_root": str(
                strategy_binding.get("research_root") or ""
            ),
        })

    status = _git(canonical, "status", "--porcelain=v1", "-z")
    return {
        "schema_version": 2,
        "principal_ref": principal_ref,
        "user_root": str(user_root),
        "personal_workspace": str(user_root / "personal-workspace"),
        "factor_library": str(factor_library),
        "strategy_library": str(strategy_library),
        "profiles_root": str(profiles_root),
        "canonical": {
            "path": str(canonical),
            "owner_ref": principal_ref,
            "canonical_repo_ref": settings["canonical_repo_ref"],
            "head": _git(canonical, "rev-parse", "HEAD").strip(),
            "branch": _git(
                canonical, "branch", "--show-current"
            ).strip(),
            "dirty_file_count": len(
                [item for item in status.split("\0") if item]
            ),
            "status_sha256": sha256(status.encode()).hexdigest(),
        },
        "profiles": sorted(
            profiles, key=lambda item: str(item["profile_id"])
        ),
    }


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        env={**os.environ, **_GIT_ENV},
        capture_output=True,
        text=True,
        check=True,
    ).stdout

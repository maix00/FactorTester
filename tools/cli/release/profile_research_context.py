"""Local validation for Profile-scoped research creation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .local_profile import LocalProfileStore


@dataclass(frozen=True)
class ProfileResearchContext:
    profile_id: str
    profile: dict[str, Any]
    agent_id: str
    workspace_id: str
    workspace_ref: str
    profile_ref: str


def load_creation_context(
    store: LocalProfileStore,
    profile_id: str,
    *,
    agent_id: str = "",
    workspace_id: str = "",
) -> ProfileResearchContext:
    """Validate identity, scope, workspace, and factor worktree locally."""
    profile = store.load(profile_id)
    if profile["status"] != "active":
        raise ValueError(f"profile is not active: {profile_id}")
    binding = profile.get("factor_workspace_binding") or {}
    if not binding:
        raise ValueError(
            f"profile has no factor worktree binding: {profile_id}"
        )
    worktree = Path(str(binding.get("worktree_path") or "")).expanduser()
    if not worktree.is_dir():
        raise ValueError(f"profile factor worktree is unavailable: {worktree}")

    principal = str(
        (profile.get("session_binding") or {}).get("principal_ref") or ""
    )
    if not principal:
        raise ValueError(f"profile has no authenticated principal: {profile_id}")
    binding_owner = str(binding.get("owner_ref") or "")
    if binding_owner and binding_owner != principal:
        raise ValueError(
            "profile factor worktree owner does not match its session principal"
        )
    owned = [
        item for item in profile["workspaces"]
        if item["access_mode"] == "owner"
        and item["server_workspace_ref"]
        and (not workspace_id or item["workspace_id"] == workspace_id)
    ]
    if not owned:
        suffix = f": {workspace_id}" if workspace_id else ""
        raise ValueError(f"profile has no owned server workspace{suffix}")
    if len(owned) > 1 and not workspace_id:
        raise ValueError(
            "profile has multiple owned workspaces; supply --workspace-id"
        )
    workspace = owned[0]
    if workspace["owner_ref"] != principal:
        raise ValueError(
            "profile workspace owner does not match its session principal"
        )
    expected_server_ref = f"workspace:{workspace['workspace_id']}"
    if workspace["server_workspace_ref"] != expected_server_ref:
        raise ValueError(
            "profile workspace server reference does not match workspace_id"
        )
    agents = [
        item for item in profile["agents"]
        if item["role"] == "research" and item["status"] == "ready"
        and (not agent_id or item["agent_id"] == agent_id)
    ]
    if not agents:
        suffix = f": {agent_id}" if agent_id else ""
        raise ValueError(f"profile has no ready research Agent{suffix}")
    if len(agents) > 1 and not agent_id:
        raise ValueError(
            "profile has multiple ready research Agents; supply --agent-id"
        )
    return ProfileResearchContext(
        profile_id=profile_id,
        profile=profile,
        agent_id=agents[0]["agent_id"],
        workspace_id=workspace["workspace_id"],
        workspace_ref=workspace["server_workspace_ref"],
        profile_ref=f"profile:{profile_id}",
    )

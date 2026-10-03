"""Version-independent local profile and identity descriptors."""

from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from .local_profile_contracts import (
    new_local_profile,
    session_binding_reference,
    validate_local_identifier,
    validate_local_profile,
)
from .locations import validate_client_root
from .storage import read_json, write_json

__all__ = [
    "LocalProfileStore",
    "new_local_profile",
    "validate_local_profile",
]


class LocalProfileStore:
    def __init__(self, client_root: Path) -> None:
        self.root = validate_client_root(client_root) / "profiles"

    def list(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        return [
            self.load(path.stem)
            for path in sorted(self.root.glob("*.json"))
        ]

    def load(self, profile_id: str) -> dict[str, Any]:
        value = read_json(self._path(profile_id))
        if value is None:
            raise ValueError(f"local profile not found: {profile_id}")
        profile = validate_local_profile(value)
        if profile != value:
            return self.save(profile)
        return profile

    def save(self, value: dict[str, Any]) -> dict[str, Any]:
        profile = validate_local_profile(value)
        path = self._path(str(profile["profile_id"]))
        write_json(path, profile)
        path.chmod(0o600)
        return profile

    def upsert_agent(
        self,
        profile_id: str,
        descriptor: dict[str, Any],
    ) -> dict[str, Any]:
        profile = self.load(profile_id)
        descriptor = dict(descriptor)
        scope = dict(descriptor.get("scope") or {})
        workspace_id = str(scope.get("workspace_id") or "")
        scope_bound = (
            workspace_id not in {"", "all", "unbound"}
            and any(
                item["workspace_id"] == workspace_id
                and bool(item["server_workspace_ref"])
                for item in profile["workspaces"]
            )
        )
        descriptor["status"] = "ready" if scope_bound else "needs_scope"
        descriptor["next_action"] = (
            "Resume the authorized research scope."
            if scope_bound
            else "Bind an authorized research workspace before execution."
        )
        agents = [
            item for item in profile["agents"]
            if item["agent_id"] != descriptor.get("agent_id")
        ]
        profile["agents"] = [*agents, descriptor]
        return self.save(profile)

    def set_server_url(
        self,
        profile_id: str,
        server_url: str,
    ) -> dict[str, Any]:
        del profile_id, server_url
        raise ValueError(
            "client Profile has no server endpoint; configure the client "
            "connection with `factortester configure`"
        )

    def upsert_workspace(
        self,
        profile_id: str,
        descriptor: dict[str, Any],
        *,
        workspace_root: Path | None = None,
    ) -> dict[str, Any]:
        profile = self.load(profile_id)
        workspaces = [
            item for item in profile["workspaces"]
            if item["workspace_id"] != descriptor.get("workspace_id")
        ]
        profile["workspaces"] = [*workspaces, descriptor]
        if workspace_root is not None:
            profile["workspace_root"] = str(
                workspace_root.expanduser().resolve()
            )
        return self.save(profile)

    def remove_workspace(
        self,
        profile_id: str,
        workspace_id: str,
    ) -> dict[str, Any]:
        profile = self.load(profile_id)
        remaining = [
            item for item in profile["workspaces"]
            if item["workspace_id"] != workspace_id
        ]
        if len(remaining) == len(profile["workspaces"]):
            raise ValueError(f"local workspace not found: {workspace_id}")
        profile["workspaces"] = remaining
        for agent in profile["agents"]:
            if agent["scope"]["workspace_id"] == workspace_id:
                agent["scope"] = {"workspace_id": "unbound"}
                agent["status"] = "needs_scope"
                agent["next_action"] = (
                    "Bind an authorized research workspace before execution."
                )
        return self.save(profile)

    def upsert_adapter(
        self,
        profile_id: str,
        descriptor: dict[str, Any],
    ) -> dict[str, Any]:
        profile = self.load(profile_id)
        adapters = [
            item for item in profile["adapters"]
            if item["adapter_id"] != descriptor.get("adapter_id")
        ]
        profile["adapters"] = [*adapters, descriptor]
        return self.save(profile)

    def upsert_initialization_source(
        self,
        profile_id: str,
        descriptor: dict[str, Any],
    ) -> dict[str, Any]:
        profile = self.load(profile_id)
        sources = [
            item for item in profile["initialization_sources"]
            if item["source_id"] != descriptor.get("source_id")
        ]
        profile["initialization_sources"] = [*sources, descriptor]
        return self.save(profile)

    def bind_session(
        self,
        profile_id: str,
        *,
        principal_ref: str,
    ) -> dict[str, Any]:
        profile = self.load(profile_id)
        current = profile.get("session_binding") or {}
        if current and current.get("principal_ref") != principal_ref:
            raise ValueError(
                "profile is bound to another principal; "
                "rebind or create a new profile"
            )
        profile["session_binding"] = {
            "principal_ref": principal_ref,
            "session_ref": session_binding_reference(
                principal_ref, profile_id,
            ),
        }
        return self.save(profile)

    def load_agent(
        self,
        profile_id: str,
        agent_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        profile = self.load(profile_id)
        for agent in profile["agents"]:
            if agent["agent_id"] == agent_id:
                return profile, agent
        raise ValueError(
            f"local Agent not found: {profile_id}/{agent_id}"
        )

    def ensure_workspace_root(self, profile_id: str) -> Path:
        profile = self.load(profile_id)
        root = Path(profile["workspace_root"]).expanduser()
        if root.exists() and not root.is_dir():
            raise ValueError(f"profile workspace root is not a directory: {root}")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        return root.resolve()

    def claim_agent(
        self,
        profile_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        profile, agent = self.load_agent(profile_id, agent_id)
        workspace_root = self.ensure_workspace_root(profile_id)
        scope = dict(agent["scope"])
        scope_bound = agent["status"] == "ready" and all(
            value not in {"", "all", "unbound"}
            for value in scope.values()
        )
        binding = profile.get("factor_workspace_binding") or {}
        worktree_path = str(binding.get("worktree_path") or "")
        worktree = Path(worktree_path) if worktree_path else None
        worktree_available = bool(worktree and worktree.is_dir())
        commit, commit_kind = _factor_worktree_commit(binding, worktree)
        receipt = {
            "schema_version": 2,
            "profile_id": profile_id,
            "agent_id": agent_id,
            "role": agent["role"],
            "agent_status": agent["status"],
            "next_action": agent["next_action"],
            "workspace_root": str(workspace_root),
            "session_binding_ref": str(
                (profile.get("session_binding") or {}).get(
                    "session_ref", ""
                )
            ),
            "initialization_source_refs": sorted(
                str(item["source_ref"])
                for item in profile["initialization_sources"]
            ),
            "registered_workspace_refs": sorted(
                str(item["server_workspace_ref"])
                for item in profile["workspaces"]
                if item["server_workspace_ref"]
            ),
            "can_start_inspection_and_planning": True,
            "research_execution_scope_bound": scope_bound,
            "factor_worktree_ref": str(binding.get("receipt_ref") or ""),
            "factor_worktree_path": worktree_path,
            "factor_worktree_branch": str(binding.get("branch") or ""),
            "factor_worktree_commit": commit,
            "factor_worktree_commit_kind": commit_kind,
            "factor_worktree_available": worktree_available,
            "canonical_repo_ref": str(
                binding.get("canonical_repo_ref") or ""
            ),
            "sync_policy": dict(binding.get("sync_policy") or {}),
            "recommended_cwd": (
                worktree_path if worktree_available else str(workspace_root)
            ),
            "next_command": "",
        }
        encoded = json.dumps(
            receipt, sort_keys=True, separators=(",", ":")
        ).encode()
        receipt["receipt_hash"] = sha256(encoded).hexdigest()
        path = (
            self.root
            / "claim-receipts"
            / profile_id
            / f"{agent_id}.json"
        )
        existing = read_json(path)
        if existing != receipt:
            write_json(path, receipt)
            path.chmod(0o600)
        return {**receipt, "receipt_ref": path.resolve().as_uri()}

    def _path(self, profile_id: str) -> Path:
        validate_local_identifier(profile_id, "profile_id")
        return self.root / f"{profile_id}.json"


def _factor_worktree_commit(
    binding: dict[str, Any],
    worktree: Path | None,
) -> tuple[str, str]:
    base = str(binding.get("base_commit") or "")
    if worktree is None or not worktree.is_dir():
        return (base, "base") if base else ("", "")
    result = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    head = result.stdout.strip()
    if (
        result.returncode == 0
        and len(head) == 40
        and all(character in "0123456789abcdef" for character in head)
    ):
        return head, "head"
    return (base, "base") if base else ("", "")

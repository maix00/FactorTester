"""Version-independent local profile and identity descriptors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .locations import validate_client_root
from .local_profile_contracts import (
    new_local_profile,
    validate_local_identifier,
    validate_local_profile,
)
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
            validate_local_profile(read_json(path))
            for path in sorted(self.root.glob("*.json"))
        ]

    def load(self, profile_id: str) -> dict[str, Any]:
        value = read_json(self._path(profile_id))
        if value is None:
            raise ValueError(f"local profile not found: {profile_id}")
        return validate_local_profile(value)

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
        agents = [
            item for item in profile["agents"]
            if item["agent_id"] != descriptor.get("agent_id")
        ]
        profile["agents"] = [*agents, descriptor]
        return self.save(profile)

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

    def _path(self, profile_id: str) -> Path:
        validate_local_identifier(profile_id, "profile_id")
        return self.root / f"{profile_id}.json"

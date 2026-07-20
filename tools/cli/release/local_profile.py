"""Version-independent local profile and identity descriptors."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from .locations import validate_client_root
from .storage import read_json, write_json


_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_AGENT_ROLES = {"planning", "research"}


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

    def _path(self, profile_id: str) -> Path:
        if not _IDENTIFIER.fullmatch(profile_id):
            raise ValueError("profile_id is invalid")
        return self.root / f"{profile_id}.json"


def new_local_profile(
    *,
    profile_id: str,
    display_name: str,
    server_url: str,
    workspace_root: Path,
) -> dict[str, Any]:
    return validate_local_profile({
        "schema_version": 1,
        "profile_id": profile_id,
        "display_name": display_name,
        "server": {"base_url": server_url},
        "workspace_root": str(workspace_root.expanduser().resolve()),
        "agents": [],
        "adapters": [],
    })


def validate_local_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("local profile must be an object")
    if set(value) != {
        "schema_version", "profile_id", "display_name", "server",
        "workspace_root", "agents", "adapters",
    }:
        raise ValueError("local profile fields are invalid")
    if value.get("schema_version") != 1:
        raise ValueError("local profile schema_version is unsupported")
    profile_id = _identifier(value.get("profile_id"), "profile_id")
    display_name = _text(value.get("display_name"), "display_name")
    server = value.get("server")
    if not isinstance(server, dict) or set(server) != {"base_url"}:
        raise ValueError("local profile server fields are invalid")
    base_url = _text(server.get("base_url"), "server.base_url").rstrip("/")
    if urlparse(base_url).scheme not in {"http", "https"}:
        raise ValueError("server.base_url must use http or https")
    workspace_root = _text(value.get("workspace_root"), "workspace_root")
    agents = _array(value.get("agents"), "agents")
    adapters = _array(value.get("adapters"), "adapters")
    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "display_name": display_name,
        "server": {"base_url": base_url},
        "workspace_root": workspace_root,
        "agents": [_agent(item) for item in agents],
        "adapters": [_adapter(item) for item in adapters],
    }


def _agent(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "agent_id", "role", "scope",
    }:
        raise ValueError("local agent descriptor fields are invalid")
    role = _text(value.get("role"), "agent.role")
    if role not in _AGENT_ROLES:
        raise ValueError("local agent role is unsupported")
    scope = value.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("local agent scope must be an object")
    return {
        "agent_id": _identifier(value.get("agent_id"), "agent.agent_id"),
        "role": role,
        "scope": {
            str(key): _text(item, f"agent.scope.{key}")
            for key, item in sorted(scope.items())
        },
    }


def _adapter(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "adapter_id", "enabled", "credential_ref", "configuration_ref",
    }:
        raise ValueError("local adapter descriptor fields are invalid")
    enabled = value.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("local adapter enabled must be boolean")
    return {
        "adapter_id": _identifier(
            value.get("adapter_id"), "adapter.adapter_id"
        ),
        "enabled": enabled,
        "credential_ref": str(value.get("credential_ref") or ""),
        "configuration_ref": str(value.get("configuration_ref") or ""),
    }


def _array(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _identifier(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text

"""Strict schemas for local profiles, Agents, and adapter references."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse


_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_AGENT_ROLES = {"planning", "research"}


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
    server = value.get("server")
    if not isinstance(server, dict) or set(server) != {"base_url"}:
        raise ValueError("local profile server fields are invalid")
    base_url = _text(server.get("base_url"), "server.base_url").rstrip("/")
    if urlparse(base_url).scheme not in {"http", "https"}:
        raise ValueError("server.base_url must use http or https")
    agents = _array(value.get("agents"), "agents")
    adapters = _array(value.get("adapters"), "adapters")
    return {
        "schema_version": 1,
        "profile_id": validate_local_identifier(
            value.get("profile_id"), "profile_id"
        ),
        "display_name": _text(value.get("display_name"), "display_name"),
        "server": {"base_url": base_url},
        "workspace_root": _text(
            value.get("workspace_root"), "workspace_root"
        ),
        "agents": [_agent(item) for item in agents],
        "adapters": [_adapter(item) for item in adapters],
    }


def validate_local_identifier(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _agent(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "agent_id", "role", "scope",
    }:
        raise ValueError("local agent descriptor fields are invalid")
    role = _text(value.get("role"), "agent.role")
    if role not in _AGENT_ROLES:
        raise ValueError("local agent role is unsupported")
    scope = value.get("scope")
    expected = (
        {"workspace_id"}
        if role == "planning"
        else {"instance_id", "branch_id"}
    )
    if not isinstance(scope, dict) or set(scope) != expected:
        raise ValueError(f"local {role} agent scope fields are invalid")
    return {
        "agent_id": validate_local_identifier(
            value.get("agent_id"), "agent.agent_id"
        ),
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
    credential_ref = str(value.get("credential_ref") or "").strip()
    configuration_ref = str(value.get("configuration_ref") or "").strip()
    _reference(
        credential_ref,
        field="adapter.credential_ref",
        schemes={"keychain"},
    )
    _reference(
        configuration_ref,
        field="adapter.configuration_ref",
        schemes={"file", "profile"},
    )
    return {
        "adapter_id": validate_local_identifier(
            value.get("adapter_id"), "adapter.adapter_id"
        ),
        "enabled": enabled,
        "credential_ref": credential_ref,
        "configuration_ref": configuration_ref,
    }


def _array(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _reference(value: str, *, field: str, schemes: set[str]) -> None:
    if not value:
        return
    parsed = urlparse(value)
    if (
        parsed.scheme not in schemes
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"{field} must be an opaque local reference")


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text

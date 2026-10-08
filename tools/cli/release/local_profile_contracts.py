"""Strict schemas for local profiles, Agents, and adapter references."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_AGENT_ROLES = {"planning", "research"}
_WORKSPACE_ACCESS = {"owner", "granted", "read_only"}


def new_local_profile(
    *,
    profile_id: str,
    display_name: str,
    server_url: str | None = None,
    workspace_root: Path,
    principal_ref: str = "",
) -> dict[str, Any]:
    """Create a client-owned Profile without a server endpoint.

    ``server_url`` is retained as an ignored call-site argument for one
    release so older installed callers can create a Profile while their
    connection is migrated to the client configuration.  It must never be
    serialized into the Profile.
    """
    del server_url
    return validate_local_profile({
        "schema_version": 11,
        "profile_id": profile_id,
        "status": "active",
        "display_name": display_name,
        "workspace_root": str(workspace_root.expanduser().resolve()),
        "workspaces": [],
        "initialization_sources": [],
        "session_binding": (
            {
                "principal_ref": principal_ref,
                "session_ref": session_binding_reference(
                    principal_ref, profile_id,
                ),
            }
            if principal_ref else {}
        ),
        "agents": [],
        "factor_workspace_binding": {},
        "strategy_workspace_binding": {},
        "adapters": [],
    })


def session_binding_reference(
    principal_ref: str,
    profile_id: str,
    suffix: str = "",
) -> str:
    """Build an opaque reference that also supports ``org@alias@random``.

    Keep the historical authority-shaped reference for principals that cannot
    be confused with URL credentials. New compound usernames contain ``@``;
    encode those in the path so ``urlparse`` never treats them as userinfo.
    """
    principal = str(principal_ref or "").strip()
    profile = str(profile_id or "").strip()
    tail = str(suffix or "").strip("/")
    tail = f"/{tail}" if tail else ""
    if "@" not in principal:
        return f"session-binding://{principal}/{profile}{tail}"
    return (
        "session-binding:/"
        f"{quote(principal, safe='')}/{quote(profile, safe='')}"
        f"{tail}"
    )


def validate_local_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("local profile must be an object")
    allowed = {
        "schema_version", "profile_id", "status", "display_name",
        "workspace_root", "workspaces", "agents", "adapters",
        "initialization_sources",
        "session_binding",
        "factor_workspace_binding",
        "strategy_workspace_binding",
    }
    legacy_allowed = {*allowed, "server", "research_records"}
    observed = set(value)
    legacy_optional = {
        "workspaces", "initialization_sources", "session_binding",
        "factor_workspace_binding", "strategy_workspace_binding", "status",
        "research_records",
    }
    if not (allowed - legacy_optional).issubset(observed):
        raise ValueError("local profile fields are invalid")
    if observed - (legacy_allowed):
        raise ValueError("local profile fields are invalid")
    schema_version = value.get("schema_version")
    if schema_version not in {
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
    }:
        raise ValueError("local profile schema_version is unsupported")
    if schema_version >= 10 and "server" in value:
        raise ValueError("client Profile must not contain server metadata")
    if schema_version >= 11 and "research_records" in value:
        raise ValueError("client Profile must not contain Graph research history")
    if schema_version < 10:
        server = value.get("server")
        if not isinstance(server, dict) or set(server) != {"base_url"}:
            raise ValueError("legacy local profile server fields are invalid")
        base_url = _text(
            server.get("base_url"), "server.base_url",
        ).rstrip("/")
        if urlparse(base_url).scheme not in {"http", "https"}:
            raise ValueError("server.base_url must use http or https")
    status = value.get("status", "active")
    if status not in {"active", "inactive"}:
        raise ValueError("local profile status is invalid")
    agents = _array(value.get("agents"), "agents")
    adapters = _array(value.get("adapters"), "adapters")
    workspaces = _array(value.get("workspaces", []), "workspaces")
    sources = _array(
        value.get("initialization_sources", []),
        "initialization_sources",
    )
    session_binding = _session_binding(value.get("session_binding", {}))
    factor_workspace_binding = _factor_workspace_binding(
        value.get("factor_workspace_binding", {})
    )
    strategy_workspace_binding = _strategy_workspace_binding(
        value.get("strategy_workspace_binding", {})
    )
    return {
        "schema_version": 11,
        "profile_id": validate_local_identifier(
            value.get("profile_id"), "profile_id"
        ),
        "status": status,
        "display_name": _text(value.get("display_name"), "display_name"),
        "workspace_root": _text(
            value.get("workspace_root"), "workspace_root"
        ),
        "workspaces": [_workspace(item) for item in workspaces],
        "initialization_sources": [
            _initialization_source(item) for item in sources
        ],
        "session_binding": session_binding,
        "factor_workspace_binding": factor_workspace_binding,
        "strategy_workspace_binding": strategy_workspace_binding,
        "agents": [
            _agent(item, migrate_legacy_scope=schema_version < 11)
            for item in agents
        ],
        "adapters": [_adapter(item) for item in adapters],
    }


def _factor_workspace_binding(value: Any) -> dict[str, Any]:
    if value == {}:
        return {}
    fields = {
        "binding_id", "canonical_repo_ref", "base_commit", "branch",
        "worktree_path", "research_root", "git_common_dir", "owner_ref",
        "sync_policy", "receipt_hash", "receipt_ref",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("factor workspace binding fields are invalid")
    sync = value.get("sync_policy")
    if not isinstance(sync, dict) or set(sync) != {
        "source_sync_enabled", "auto_push", "auto_merge",
    }:
        raise ValueError("factor workspace sync policy fields are invalid")
    if sync["auto_push"] is not False or sync["auto_merge"] is not False:
        raise ValueError("factor workspace cannot auto push or merge")
    commit = _text(value.get("base_commit"), "factor_workspace.base_commit")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("factor workspace base_commit is invalid")
    canonical_ref = _text(
        value.get("canonical_repo_ref"),
        "factor_workspace.canonical_repo_ref",
    )
    _reference(
        canonical_ref,
        field="factor_workspace.canonical_repo_ref",
        schemes={"local-factor-git"},
    )
    receipt_ref = _text(
        value.get("receipt_ref"), "factor_workspace.receipt_ref"
    )
    _reference(
        receipt_ref,
        field="factor_workspace.receipt_ref",
        schemes={"file"},
    )
    return {
        "binding_id": validate_local_identifier(
            value.get("binding_id"), "factor_workspace.binding_id"
        ),
        "canonical_repo_ref": canonical_ref,
        "base_commit": commit,
        "branch": _text(value.get("branch"), "factor_workspace.branch"),
        "worktree_path": _text(
            value.get("worktree_path"), "factor_workspace.worktree_path"
        ),
        "research_root": _text(
            value.get("research_root"), "factor_workspace.research_root"
        ),
        "git_common_dir": _text(
            value.get("git_common_dir"), "factor_workspace.git_common_dir"
        ),
        "owner_ref": _text(
            value.get("owner_ref"), "factor_workspace.owner_ref"
        ),
        "sync_policy": {
            "source_sync_enabled": bool(sync["source_sync_enabled"]),
            "auto_push": False,
            "auto_merge": False,
        },
        "receipt_hash": _text(
            value.get("receipt_hash"), "factor_workspace.receipt_hash"
        ),
        "receipt_ref": receipt_ref,
    }


def _strategy_workspace_binding(value: Any) -> dict[str, Any]:
    """Validate an isolated actor source worktree, independent of factors."""
    if value == {}:
        return {}
    fields = {
        "binding_id", "canonical_repo_ref", "base_commit", "branch",
        "worktree_path", "research_root", "git_common_dir", "owner_ref",
        "sync_policy", "receipt_hash", "receipt_ref",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("strategy workspace binding fields are invalid")
    sync = value.get("sync_policy")
    if not isinstance(sync, dict) or set(sync) != {
        "source_sync_enabled", "auto_push", "auto_merge",
    }:
        raise ValueError("strategy workspace sync policy fields are invalid")
    if sync["auto_push"] is not False or sync["auto_merge"] is not False:
        raise ValueError("strategy workspace cannot auto push or merge")
    commit = _text(value.get("base_commit"), "strategy_workspace.base_commit")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("strategy workspace base_commit is invalid")
    canonical_ref = _text(
        value.get("canonical_repo_ref"),
        "strategy_workspace.canonical_repo_ref",
    )
    _reference(
        canonical_ref,
        field="strategy_workspace.canonical_repo_ref",
        schemes={"local-strategy-git"},
    )
    receipt_ref = _text(
        value.get("receipt_ref"), "strategy_workspace.receipt_ref"
    )
    _reference(receipt_ref, field="strategy_workspace.receipt_ref", schemes={"file"})
    return {
        "binding_id": validate_local_identifier(
            value.get("binding_id"), "strategy_workspace.binding_id"
        ),
        "canonical_repo_ref": canonical_ref,
        "base_commit": commit,
        "branch": _text(value.get("branch"), "strategy_workspace.branch"),
        "worktree_path": _text(
            value.get("worktree_path"), "strategy_workspace.worktree_path"
        ),
        "research_root": _text(
            value.get("research_root"), "strategy_workspace.research_root"
        ),
        "git_common_dir": _text(
            value.get("git_common_dir"), "strategy_workspace.git_common_dir"
        ),
        "owner_ref": _text(value.get("owner_ref"), "strategy_workspace.owner_ref"),
        "sync_policy": {
            "source_sync_enabled": bool(sync["source_sync_enabled"]),
            "auto_push": False,
            "auto_merge": False,
        },
        "receipt_hash": _text(
            value.get("receipt_hash"), "strategy_workspace.receipt_hash"
        ),
        "receipt_ref": receipt_ref,
    }


def _session_binding(value: Any) -> dict[str, str]:
    if value == {}:
        return {}
    if not isinstance(value, dict) or set(value) != {
        "principal_ref", "session_ref",
    }:
        raise ValueError("session binding fields are invalid")
    principal = _text(value.get("principal_ref"), "principal_ref")
    reference = _text(value.get("session_ref"), "session_ref")
    _reference(reference, field="session_ref", schemes={"session-binding"})
    return {"principal_ref": principal, "session_ref": reference}


def _initialization_source(value: Any) -> dict[str, Any]:
    fields = {
        "source_id", "kind", "owner_ref", "mode", "source_ref",
        "snapshot_ref", "principal_ref", "session_ref",
        "projection_hash", "source_materialized",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("initialization source fields are invalid")
    kind = _text(value.get("kind"), "initialization_source.kind")
    if kind != "server_factor_library":
        raise ValueError("initialization source kind is unsupported")
    mode = _text(value.get("mode"), "initialization_source.mode")
    if mode not in {"reference", "snapshot"}:
        raise ValueError("initialization source mode is unsupported")
    source_ref = _text(
        value.get("source_ref"),
        "initialization_source.source_ref",
    )
    _reference(
        source_ref,
        field="initialization_source.source_ref",
        schemes={"factortester"},
    )
    snapshot_ref = str(value.get("snapshot_ref") or "").strip()
    _reference(
        snapshot_ref,
        field="initialization_source.snapshot_ref",
        schemes={"file", "artifact"},
    )
    if mode == "snapshot" and not snapshot_ref:
        raise ValueError("snapshot initialization requires snapshot_ref")
    session_ref = _text(
        value.get("session_ref"),
        "initialization_source.session_ref",
    )
    _reference(
        session_ref,
        field="initialization_source.session_ref",
        schemes={"session-binding"},
    )
    materialized = value.get("source_materialized")
    if materialized is not False:
        raise ValueError("source_materialized must remain false")
    return {
        "source_id": validate_local_identifier(
            value.get("source_id"),
            "initialization_source.source_id",
        ),
        "kind": kind,
        "owner_ref": _text(
            value.get("owner_ref"),
            "initialization_source.owner_ref",
        ),
        "mode": mode,
        "source_ref": source_ref,
        "snapshot_ref": snapshot_ref,
        "principal_ref": _text(
            value.get("principal_ref"),
            "initialization_source.principal_ref",
        ),
        "session_ref": session_ref,
        "projection_hash": _text(
            value.get("projection_hash"),
            "initialization_source.projection_hash",
        ),
        "source_materialized": False,
    }


def _workspace(value: Any) -> dict[str, Any]:
    fields = {
        "workspace_id", "path", "access_mode", "owner_ref",
        "server_workspace_ref",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("local workspace descriptor fields are invalid")
    access_mode = _text(value.get("access_mode"), "workspace.access_mode")
    if access_mode not in _WORKSPACE_ACCESS:
        raise ValueError("local workspace access_mode is unsupported")
    owner_ref = _text(value.get("owner_ref"), "workspace.owner_ref")
    server_ref = str(value.get("server_workspace_ref") or "").strip()
    return {
        "workspace_id": validate_local_identifier(
            value.get("workspace_id"), "workspace.workspace_id"
        ),
        "path": _text(value.get("path"), "workspace.path"),
        "access_mode": access_mode,
        "owner_ref": owner_ref,
        "server_workspace_ref": server_ref,
    }


def validate_local_identifier(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def validate_principal_identifier(value: Any, field: str) -> str:
    """Validate a principal as one safe filesystem path component.

    Profile/Agent IDs stay lowercase local identifiers. Account principals may
    use the canonical ``organization@alias@random`` form, so they need a
    separate validator rather than the ID regex.
    """
    text = _text(value, field)
    if text in {".", ".."} or any(
        character in text for character in ("/", "\\", "\x00")
    ) or any(ord(character) < 32 for character in text):
        raise ValueError(f"{field} is invalid")
    return text


def _agent(
    value: Any,
    *,
    migrate_legacy_scope: bool = False,
) -> dict[str, Any]:
    legacy = {"agent_id", "role", "scope"}
    current = legacy | {"status", "next_action"}
    if not isinstance(value, dict) or set(value) not in {frozenset(legacy), frozenset(current)}:
        raise ValueError("local agent descriptor fields are invalid")
    role = _text(value.get("role"), "agent.role")
    if role not in _AGENT_ROLES:
        raise ValueError("local agent role is unsupported")
    scope = value.get("scope")
    if not isinstance(scope, dict):
        raise ValueError(f"local {role} agent scope fields are invalid")
    migrated_graph_scope = (
        migrate_legacy_scope
        and role == "research"
        and set(scope) == {"instance_id", "branch_id"}
    )
    if migrated_graph_scope:
        scope = {"workspace_id": "unbound"}
    if set(scope) != {"workspace_id"}:
        raise ValueError(f"local {role} agent scope fields are invalid")
    status = str(value.get("status") or "needs_scope")
    next_action = str(
        value.get("next_action")
        or "Bind an authorized research workspace before execution."
    )
    if migrated_graph_scope:
        status = "needs_scope"
        next_action = "Bind an authorized research workspace before execution."
    return {
        "agent_id": validate_local_identifier(
            value.get("agent_id"), "agent.agent_id"
        ),
        "role": role,
        "scope": {
            str(key): _text(item, f"agent.scope.{key}")
            for key, item in sorted(scope.items())
        },
        "status": status,
        "next_action": next_action,
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

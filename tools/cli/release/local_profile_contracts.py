"""Strict schemas for local profiles, Agents, and adapter references."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse


_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_AGENT_ROLES = {"planning", "research"}
_WORKSPACE_ACCESS = {"owner", "granted", "read_only"}
_RESEARCH_STATUS = {
    "pending", "generating", "failed", "stale", "ready",
}
_ARTIFACT_FORMATS = {"markdown", "pdf"}


def new_local_profile(
    *,
    profile_id: str,
    display_name: str,
    server_url: str,
    workspace_root: Path,
    principal_ref: str = "",
) -> dict[str, Any]:
    return validate_local_profile({
        "schema_version": 6,
        "profile_id": profile_id,
        "display_name": display_name,
        "server": {"base_url": server_url},
        "workspace_root": str(workspace_root.expanduser().resolve()),
        "workspaces": [],
        "initialization_sources": [],
        "session_binding": (
            {
                "principal_ref": principal_ref,
                "session_ref": (
                    f"session-binding://{principal_ref}/{profile_id}"
                ),
            }
            if principal_ref else {}
        ),
        "agents": [],
        "research_records": [],
        "adapters": [],
    })


def validate_local_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("local profile must be an object")
    allowed = {
        "schema_version", "profile_id", "display_name", "server",
        "workspace_root", "workspaces", "agents", "adapters",
        "initialization_sources",
        "session_binding",
        "research_records",
    }
    observed = set(value)
    legacy_optional = {
        "workspaces", "initialization_sources", "session_binding",
        "research_records",
    }
    if not (allowed - legacy_optional).issubset(observed) or observed - allowed:
        raise ValueError("local profile fields are invalid")
    if value.get("schema_version") not in {1, 2, 3, 4, 5, 6}:
        raise ValueError("local profile schema_version is unsupported")
    server = value.get("server")
    if not isinstance(server, dict) or set(server) != {"base_url"}:
        raise ValueError("local profile server fields are invalid")
    base_url = _text(server.get("base_url"), "server.base_url").rstrip("/")
    if urlparse(base_url).scheme not in {"http", "https"}:
        raise ValueError("server.base_url must use http or https")
    agents = _array(value.get("agents"), "agents")
    adapters = _array(value.get("adapters"), "adapters")
    workspaces = _array(value.get("workspaces", []), "workspaces")
    sources = _array(
        value.get("initialization_sources", []),
        "initialization_sources",
    )
    session_binding = _session_binding(value.get("session_binding", {}))
    research_records = _array(
        value.get("research_records", []), "research_records"
    )
    return {
        "schema_version": 6,
        "profile_id": validate_local_identifier(
            value.get("profile_id"), "profile_id"
        ),
        "display_name": _text(value.get("display_name"), "display_name"),
        "server": {"base_url": base_url},
        "workspace_root": _text(
            value.get("workspace_root"), "workspace_root"
        ),
        "workspaces": [_workspace(item) for item in workspaces],
        "initialization_sources": [
            _initialization_source(item) for item in sources
        ],
        "session_binding": session_binding,
        "research_records": [
            _research_record(item) for item in research_records
        ],
        "agents": [_agent(item) for item in agents],
        "adapters": [_adapter(item) for item in adapters],
    }


def _research_record(value: Any) -> dict[str, Any]:
    fields = {
        "record_id", "title", "status", "scope", "factor_family_versions",
        "agent_id", "created_at", "updated_at", "workspace_ref", "run_ref",
        "graph_instance_ref", "graph_branch_ref", "checkpoint_ref",
        "evidence_refs", "artifacts", "provenance",
        "timeline_refs",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("research record fields are invalid")
    status = _text(value.get("status"), "research_record.status")
    if status not in _RESEARCH_STATUS:
        raise ValueError("research record status is unsupported")
    scope = value.get("scope")
    provenance = value.get("provenance")
    if not isinstance(scope, dict) or not isinstance(provenance, dict):
        raise ValueError("research record scope/provenance must be objects")
    versions = _array(
        value.get("factor_family_versions"), "factor_family_versions"
    )
    evidence = _array(value.get("evidence_refs"), "evidence_refs")
    artifacts = _array(value.get("artifacts"), "artifacts")
    timeline = _array(value.get("timeline_refs"), "timeline_refs")
    return {
        "record_id": validate_local_identifier(
            value.get("record_id"), "research_record.record_id"
        ),
        "title": _text(value.get("title"), "research_record.title"),
        "status": status,
        "scope": scope,
        "factor_family_versions": [
            _text(item, "factor_family_version") for item in versions
        ],
        "agent_id": _text(value.get("agent_id"), "research_record.agent_id"),
        "created_at": float(value.get("created_at") or 0),
        "updated_at": float(value.get("updated_at") or 0),
        "workspace_ref": str(value.get("workspace_ref") or ""),
        "run_ref": str(value.get("run_ref") or ""),
        "graph_instance_ref": str(value.get("graph_instance_ref") or ""),
        "graph_branch_ref": str(value.get("graph_branch_ref") or ""),
        "checkpoint_ref": str(value.get("checkpoint_ref") or ""),
        "evidence_refs": [
            _text(item, "evidence_ref") for item in evidence
        ],
        "timeline_refs": [_deep_link(item) for item in timeline],
        "artifacts": [_research_artifact(item) for item in artifacts],
        "provenance": provenance,
    }


def _research_artifact(value: Any) -> dict[str, Any]:
    legacy_fields = {
        "artifact_ref", "format", "status", "content_hash", "local_ref",
        "section_refs",
    }
    fields = legacy_fields | {"index_ref"}
    if (
        not isinstance(value, dict)
        or set(value) not in {frozenset(legacy_fields), frozenset(fields)}
    ):
        raise ValueError("research artifact fields are invalid")
    format_name = _text(value.get("format"), "artifact.format")
    if format_name not in _ARTIFACT_FORMATS:
        raise ValueError("research artifact format is unsupported")
    status = _text(value.get("status"), "artifact.status")
    if status not in _RESEARCH_STATUS:
        raise ValueError("research artifact status is unsupported")
    local_ref = str(value.get("local_ref") or "")
    index_ref = str(value.get("index_ref") or "")
    section_refs = _array(value.get("section_refs"), "section_refs")
    _reference(
        local_ref,
        field="artifact.local_ref",
        schemes={"file", "artifact"},
    )
    _reference(
        index_ref,
        field="artifact.index_ref",
        schemes={"file", "artifact"},
    )
    return {
        "artifact_ref": _text(
            value.get("artifact_ref"), "artifact.artifact_ref"
        ),
        "format": format_name,
        "status": status,
        "content_hash": str(value.get("content_hash") or ""),
        "local_ref": local_ref,
        "index_ref": index_ref,
        "section_refs": [_deep_link(item) for item in section_refs],
    }


def _deep_link(value: Any) -> dict[str, str]:
    fields = {"link_id", "kind", "target_ref", "section_ref"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("research deep link fields are invalid")
    kind = _text(value.get("kind"), "deep_link.kind")
    if kind not in {"trial_plan", "obligation", "evidence", "report_section"}:
        raise ValueError("research deep link kind is unsupported")
    return {
        key: _text(value.get(key), f"deep_link.{key}")
        for key in sorted(fields)
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


def _agent(value: Any) -> dict[str, Any]:
    legacy = {"agent_id", "role", "scope"}
    current = legacy | {"status", "next_action"}
    if not isinstance(value, dict) or set(value) not in {frozenset(legacy), frozenset(current)}:
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
        "status": str(value.get("status") or "needs_scope"),
        "next_action": str(
            value.get("next_action")
            or "Bind an authorized research scope before execution."
        ),
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

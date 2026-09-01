"""Stable provenance and sharing labels for research publications."""

from __future__ import annotations

from typing import Any

BUILD_SOURCES = frozenset({"client", "server_agent"})
SHARING_STATES = frozenset({"shared", "not_shared"})


def normalize_build_source(value: Any, *, default: str = "client") -> str:
    """Normalize the construction runtime without guessing from storage."""
    candidate = str(value or "").strip().casefold()
    aliases = {
        "client": "client",
        "local": "client",
        "ftclient": "client",
        "server": "server_agent",
        "agent": "server_agent",
        "server-agent": "server_agent",
        "server_agent": "server_agent",
    }
    normalized = aliases.get(candidate, "")
    if normalized:
        return normalized
    fallback = aliases.get(str(default or "").strip().casefold(), "")
    if fallback:
        return fallback
    raise ValueError("research build source is invalid")


def sharing_state(visibility: Any) -> str:
    """Reduce the access policy to the explicit shared/non-shared label."""
    return "shared" if str(visibility or "").strip() in {"superiors", "authorized", "public"} else "not_shared"


def provenance_fields(
    record: dict[str, Any], *, default_source: str = "client",
) -> dict[str, Any]:
    """Return display-safe provenance fields, including legacy derivation."""
    source = normalize_build_source(
        record.get("build_source"), default=default_source,
    )
    visibility = str(record.get("visibility") or "private").strip() or "private"
    state = sharing_state(visibility)
    source_ref = str(
        record.get("build_source_ref")
        or record.get("agent_ref")
        or record.get("profile_ref")
        or ""
    ).strip()
    return {
        "build_source": source,
        "build_source_ref": source_ref,
        "sharing_state": state,
        "is_shared": state == "shared",
    }


__all__ = [
    "BUILD_SOURCES", "SHARING_STATES", "normalize_build_source",
    "provenance_fields", "sharing_state",
]

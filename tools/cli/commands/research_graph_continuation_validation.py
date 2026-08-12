"""Fail-closed validation for a continuation report parent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.authoring.tree_model import (
    load_snapshot,
)


def require_existing_anchor(
    package_root: Path, branch_id: str, container: dict[str, Any],
) -> None:
    anchor = str(container.get("anchor_node") or "")
    snapshot = load_snapshot(
        package_root=package_root, branch_id=branch_id,
    )
    matches = [
        item for item in snapshot["components"]
        if item["kind"] == "chapter"
        and any(
            binding["kind"] == "graph_reference"
            and binding["target_ref"] == f"node:{anchor}"
            and (binding.get("data") or {}).get("role") == "report_chapter"
            and binding["component_id"] == item["component_id"]
            for binding in snapshot["bindings"]
        )
    ]
    if len(matches) != 1:
        raise ValueError(
            "Graph continuation requires its inherited substantive chapter"
        )


def validate_parent(
    package_root: Path, branch_id: str, component_id: str,
    container: dict[str, Any],
) -> None:
    snapshot = load_snapshot(
        package_root=package_root, branch_id=branch_id,
    )
    matches = [
        item for item in snapshot["components"]
        if item["component_id"] == component_id
    ]
    if len(matches) != 1:
        raise ValueError("Graph continuation report parent is unavailable")
    parent = matches[0]
    if container["kind"] == "chapter":
        if parent["kind"] != "chapter":
            raise ValueError("Graph continuation chapter parent conflicts")
        return
    episode = _active_episode(container)
    bindings = [
        item for item in snapshot["bindings"]
        if item["component_id"] == component_id
    ]
    if (
        parent["kind"] != "special"
        or parent["display_kind"] != "capability_detour"
        or not any(
            binding["kind"] == "graph_reference"
            and binding["target_ref"] == episode
            and (binding.get("data") or {}).get("role")
            == "capability_detour"
            for binding in bindings
        )
    ):
        raise ValueError("Graph continuation top detour parent conflicts")


def _active_episode(container: dict[str, Any]) -> str:
    detour = container.get("detour")
    episode = str(
        detour.get("episode_id") if isinstance(detour, dict) else ""
    )
    if not episode:
        raise ValueError("Graph continuation capability episode is incomplete")
    return episode

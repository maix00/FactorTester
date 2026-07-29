"""Authorize public report writes against the current Graph container."""

from __future__ import annotations

from typing import Any

from .research_graph_report_policy import (
    fetch_graph_node_packet,
    report_container,
)
from .research_report_scope import load_authoring


_SYSTEM_ROLES = {"report_chapter", "capability_detour"}
_SYSTEM_DISPLAY_KINDS = {"capability_detour", "graph_continuation"}


def validate_graph_bound_mutations(
    scope: Any,
    *,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    if not str(scope.branch_ref).startswith("graph-branch:"):
        return {"status": "unbound"}
    container = report_container(fetch_graph_node_packet(scope))
    snapshot = load_authoring(scope)
    parents = {
        str(item["component_id"]): (
            str(item["parent_id"]) if item["parent_id"] is not None else "root"
        )
        for item in snapshot["components"]
    }
    system_ids = _system_component_ids(snapshot)
    root_id = _container_component_id(snapshot, container)
    for operation in operations:
        _validate_operation(
            operation, parents=parents, root_id=root_id,
            system_ids=system_ids,
        )
    return {
        "status": "authorized",
        "container_kind": container["kind"],
        "container_component_id": root_id,
    }


def _validate_operation(
    operation: dict[str, Any],
    *,
    parents: dict[str, str],
    root_id: str,
    system_ids: set[str],
) -> None:
    op = str(operation.get("op") or "")
    if op == "asset":
        return
    component_id = str(operation.get("component_id") or "")
    if (
        op in {"add", "replace"}
        and operation.get("display_kind") in _SYSTEM_DISPLAY_KINDS
    ):
        raise ValueError(
            "Graph lifecycle special sections are system-owned"
        )
    if op == "add":
        if operation.get("kind") == "chapter":
            raise ValueError(
                "Graph node chapters are system-owned; use node advance"
            )
        parent_id = str(operation.get("parent_id") or "root")
        _require_descendant(parent_id, root_id, parents)
        if component_id in parents:
            raise ValueError("report component already exists")
        parents[component_id] = parent_id
        return
    if component_id in system_ids:
        raise ValueError("Graph report containers are system-owned")
    _require_descendant(component_id, root_id, parents)
    if op == "move":
        parent_id = str(operation.get("parent_id") or "")
        _require_descendant(parent_id, root_id, parents)
        parents[component_id] = parent_id
    elif op not in {"replace", "bind"}:
        raise ValueError("unknown report mutation")


def _require_descendant(
    component_id: str,
    root_id: str,
    parents: dict[str, str],
) -> None:
    current = component_id
    seen: set[str] = set()
    while current != root_id:
        if current in seen or current not in parents:
            raise ValueError(
                "report mutation must stay inside the current Graph container"
            )
        seen.add(current)
        current = parents[current]


def _system_component_ids(snapshot: dict[str, Any]) -> set[str]:
    return {
        str(binding["component_id"])
        for binding in snapshot["bindings"]
        if binding["kind"] == "graph_reference"
        and (binding.get("data") or {}).get("role") in _SYSTEM_ROLES
    }


def _container_component_id(
    snapshot: dict[str, Any],
    container: dict[str, Any],
) -> str:
    if container["kind"] == "chapter":
        target = f"node:{container['anchor_node']}"
        role = "report_chapter"
    else:
        detour = container.get("detour") or {}
        target = str(detour.get("episode_id") or "")
        role = "capability_detour"
    matches = {
        str(binding["component_id"])
        for binding in snapshot["bindings"]
        if binding["kind"] == "graph_reference"
        and binding["target_ref"] == target
        and (binding.get("data") or {}).get("role") == role
    }
    if len(matches) != 1:
        raise ValueError(
            "current Graph report container is not synchronized locally; "
            "reconcile the branch before authoring"
        )
    return matches.pop()

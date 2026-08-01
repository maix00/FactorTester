"""Authorize public report writes against the current Graph container."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .research_graph_report_policy import (
    fetch_graph_node_packet,
    report_container,
)
from .research_report_scope import load_authoring


_SYSTEM_ROLES = {
    "report_chapter", "capability_detour", "obligation_requirements_summary",
    "obligation_requirements_resolution",
}
_SYSTEM_DISPLAY_KINDS = {
    "capability_detour",
    "graph_continuation",
    "obligation_changes",
    "research_gap",
    "test_result",
    "entry_requirements",
}


def validate_graph_bound_mutations(
    scope: Any,
    *,
    operations: list[dict[str, Any]],
    historical_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not str(scope.branch_ref).startswith("graph-branch:"):
        return {"status": "unbound"}
    snapshot = load_authoring(scope)
    if historical_review is not None:
        _validate_historical_review(
            snapshot,
            operations=operations,
            review=historical_review,
        )
        return {
            "status": "authorized",
            "container_kind": "historical_source_correction",
            "container_component_id": "",
        }
    container = report_container(fetch_graph_node_packet(scope))
    parents = {
        str(item["component_id"]): (
            str(item["parent_id"]) if item["parent_id"] is not None else "root"
        )
        for item in snapshot["components"]
    }
    system_ids = _system_component_ids(snapshot)
    root_id = _container_component_id(snapshot, container)
    chapter_ids = _graph_chapter_ids(snapshot)
    for operation in operations:
        _validate_operation(
            operation, parents=parents, root_id=root_id,
            system_ids=system_ids, chapter_ids=chapter_ids,
        )
    return {
        "status": "authorized",
        "container_kind": container["kind"],
        "container_component_id": root_id,
    }


def _validate_historical_review(
    snapshot: dict[str, Any],
    *,
    operations: list[dict[str, Any]],
    review: dict[str, Any],
) -> None:
    components = snapshot["components"]
    identities = sorted(str(item["component_id"]) for item in components)
    digest = hashlib.sha256(json.dumps(
        identities, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    if (
        review.get("schema_version") != 1
        or review.get("kind") != "historical_source_correction"
        or review.get("reviewed_component_count") != len(identities)
        or review.get("reviewed_component_digest") != digest
    ):
        raise ValueError(
            "historical source correction review does not match report"
        )
    declared = review.get("components")
    if not isinstance(declared, list):
        raise ValueError(
            "historical source correction needs a component review list"
        )
    reviewed_ids = [
        str(item.get("component_id") or "")
        for item in declared if isinstance(item, dict)
    ]
    operation_ids = [
        str(item.get("component_id") or "") for item in operations
    ]
    if (
        reviewed_ids != operation_ids
        or len(reviewed_ids) != len(declared)
        or any(
            not str(item.get("reason") or "").strip()
            for item in declared if isinstance(item, dict)
        )
    ):
        raise ValueError(
            "historical source correction review must explain every operation"
        )
    system_ids = _system_component_ids(snapshot)
    known_ids = set(identities)
    if not (
        _is_safe_historical_replacement(
            operations, known_ids=known_ids, system_ids=system_ids,
        )
        or _is_safe_historical_system_content_cleanup(
            components,
            operations=operations,
            system_ids=system_ids,
        )
        or _is_safe_historical_section_wrap(
            components,
            operations=operations,
            known_ids=known_ids,
            system_ids=system_ids,
        )
    ):
        raise ValueError(
            "historical source correction must replace reviewed content or "
            "wrap a titled content leaf in one same-parent section"
        )


def _is_safe_historical_system_content_cleanup(
    components: list[dict[str, Any]], *,
    operations: list[dict[str, Any]], system_ids: set[str],
) -> bool:
    """Allow reviewed removal of leaked machine JSON from system sections."""
    current = {
        str(item["component_id"]): item for item in components
        if isinstance(item, dict)
    }
    if not operations:
        return False
    for operation in operations:
        component_id = str(operation.get("component_id") or "")
        before = current.get(component_id) or {}
        if (
            operation.get("op") != "replace"
            or not (
                component_id in system_ids
                or str(before.get("display_kind") or "")
                in _SYSTEM_DISPLAY_KINDS
            )
            or before.get("kind") != "special"
            or operation.get("content") is not None
            or str(operation.get("title") or "")
            != str(before.get("title") or "")
            or str(operation.get("body") or "")
            != str(before.get("body") or "")
            or str(operation.get("display_kind") or "")
            != str(before.get("display_kind") or "")
        ):
            return False
    return True


def _is_safe_historical_replacement(
    operations: list[dict[str, Any]], *,
    known_ids: set[str], system_ids: set[str],
) -> bool:
    return bool(operations) and all(
        item.get("op") == "replace"
        and str(item.get("component_id") or "") in known_ids
        and str(item.get("component_id") or "") not in system_ids
        and item.get("display_kind") not in _SYSTEM_DISPLAY_KINDS
        for item in operations
    )


def _is_safe_historical_section_wrap(
    components: list[dict[str, Any]], *, operations: list[dict[str, Any]],
    known_ids: set[str], system_ids: set[str],
) -> bool:
    """Allow only title-preserving wrappers around existing content leaves."""
    current = {
        str(item["component_id"]): item for item in components
        if isinstance(item, dict)
    }
    additions = {
        str(item.get("component_id") or ""): item
        for item in operations if item.get("op") == "add"
    }
    replacements = {
        str(item.get("component_id") or ""): item
        for item in operations if item.get("op") == "replace"
    }
    moves = {
        str(item.get("component_id") or ""): item
        for item in operations if item.get("op") == "move"
    }
    if (
        not additions
        or len(operations) != len(additions) + len(replacements) + len(moves)
        or set(moves) != set(replacements) | set(additions)
        or len(additions) != len(replacements)
    ):
        return False
    wrappers = set(additions)
    if wrappers & known_ids:
        return False
    wrapped_by_leaf: dict[str, str] = {}
    for wrapper_id in additions:
        moved = [
            component_id for component_id in replacements
            if str(moves[component_id].get("parent_id") or "") == wrapper_id
        ]
        if len(moved) != 1:
            return False
        wrapped_by_leaf[moved[0]] = wrapper_id
    siblings: dict[str, list[str]] = {}
    for item in components:
        parent_id = str(item.get("parent_id") or "root")
        siblings.setdefault(parent_id, []).append(str(item["component_id"]))
    for wrapper_id, add in additions.items():
        if (
            add.get("kind") != "section"
            or not str(add.get("title") or "").strip()
            or str(add.get("body") or "")
            or add.get("content") is not None
        ):
            return False
        moved = [
            component_id for component_id, value in wrapped_by_leaf.items()
            if value == wrapper_id
        ]
        if len(moved) != 1:
            return False
        component_id = moved[0]
        before = current.get(component_id) or {}
        replace = replacements.get(component_id) or {}
        original_siblings = siblings.get(
            str(before.get("parent_id") or "root"), [],
        )
        original_index = original_siblings.index(component_id)
        previous = (
            original_siblings[original_index - 1]
            if original_index > 0 else None
        )
        expected_after = wrapped_by_leaf.get(previous, previous)
        wrapper_move = moves.get(wrapper_id) or {}
        if (
            component_id in system_ids
            or before.get("kind") not in {
                "entry", "list", "table", "image", "code", "math", "result",
            }
            or str(before.get("parent_id") or "")
            != str(add.get("parent_id") or "")
            or str(before.get("title") or "") != str(add.get("title") or "")
            or str(before.get("display_kind") or "")
            != str(add.get("display_kind") or "")
            or str(wrapper_move.get("parent_id") or "")
            != str(before.get("parent_id") or "")
            or wrapper_move.get("after_component_id") != expected_after
            or str(replace.get("title") or "")
            or replace.get("body") != before.get("body")
            or replace.get("content") != before.get("content")
            or str(replace.get("display_kind") or "")
        ):
            return False
    return True


def _validate_operation(
    operation: dict[str, Any],
    *,
    parents: dict[str, str],
    root_id: str,
    system_ids: set[str],
    chapter_ids: set[str],
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
        target_chapter_id = str(
            operation.get("target_chapter_id") or ""
        )
        authorization_root = root_id
        if target_chapter_id:
            if target_chapter_id not in chapter_ids:
                raise ValueError(
                    "target_chapter_id must identify a Graph node chapter"
                )
            authorization_root = target_chapter_id
        parent_id = str(operation.get("parent_id") or "root")
        _require_descendant(parent_id, authorization_root, parents)
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
    elif op == "remove":
        return
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


def _graph_chapter_ids(snapshot: dict[str, Any]) -> set[str]:
    return {
        str(binding["component_id"])
        for binding in snapshot["bindings"]
        if binding["kind"] == "graph_reference"
        and (binding.get("data") or {}).get("role") == "report_chapter"
    }


def resolve_graph_report_parent(
    scope: Any,
    *,
    parent_id: str | None,
    target_chapter_id: str,
) -> tuple[str | None, str, bool]:
    """Resolve the current Graph container unless a chapter is explicit."""
    requested_parent = str(parent_id or "").strip()
    requested_chapter = target_chapter_id.strip()
    if not str(scope.branch_ref).startswith("graph-branch:"):
        return (
            requested_parent or requested_chapter or None,
            requested_chapter,
            False,
        )
    snapshot = load_authoring(scope)
    container = report_container(fetch_graph_node_packet(scope))
    current_root = _container_component_id(snapshot, container)
    chapter_ids = _graph_chapter_ids(snapshot)
    if requested_chapter and requested_chapter not in chapter_ids:
        raise ValueError(
            "target_chapter_id must identify a Graph node chapter"
        )
    target = requested_chapter or current_root
    return (
        requested_parent or target,
        requested_chapter,
        bool(requested_chapter and requested_chapter != current_root),
    )


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

"""Declarative role and dependency checks for TrialPlan fixtures."""

from __future__ import annotations

from typing import Any


def actions_by_id(actions: list[Any]) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("evidence action must be an object")
        action_id = action.get("action_id")
        if not isinstance(action_id, str) or not action_id or action_id in values:
            raise ValueError("evidence action IDs must be unique text")
        values[action_id] = action
    for action_id, action in values.items():
        refs = action.get("prerequisite_action_ids")
        if not isinstance(refs, list) or not all(ref in values for ref in refs):
            raise ValueError(f"{action_id} has unknown prerequisite action")
    _reject_cycle(values)
    return values


def role_map(value: Any, actions: dict[str, Any]) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ValueError("validation_contract.action_roles must be an object")
    roles = {str(role): str(action_id) for role, action_id in value.items()}
    if len(set(roles.values())) != len(roles):
        raise ValueError("action roles must reference distinct actions")
    if not set(roles.values()).issubset(actions):
        raise ValueError("action role references unknown action")
    return roles


def validate_capabilities(
    value: Any,
    roles: dict[str, str],
    actions: dict[str, dict[str, Any]],
) -> None:
    if not isinstance(value, dict) or set(value) != set(roles):
        raise ValueError("capability_by_role must cover every declared role")
    for role, capability in value.items():
        action = actions[roles[role]]
        if action.get("capability_requirement_ref") != capability:
            raise ValueError(f"{role} capability contract does not match")


def validate_dependencies(
    value: Any,
    roles: dict[str, str],
    actions: dict[str, dict[str, Any]],
) -> list[list[str]]:
    if not isinstance(value, list):
        raise ValueError("required_dependency_roles must be an array")
    normalized: list[list[str]] = []
    for edge in value:
        if not isinstance(edge, list) or len(edge) != 2:
            raise ValueError("dependency role edge must contain two roles")
        source_role, target_role = map(str, edge)
        if source_role not in roles or target_role not in roles:
            raise ValueError("dependency edge references unknown role")
        if roles[source_role] not in (
            actions[roles[target_role]].get("prerequisite_action_ids") or []
        ):
            raise ValueError(
                f"{target_role} must cite its required predecessor"
            )
        normalized.append([source_role, target_role])
    return normalized


def _reject_cycle(actions: dict[str, dict[str, Any]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(action_id: str) -> None:
        if action_id in visiting:
            raise ValueError("evidence action dependencies must form a DAG")
        if action_id in visited:
            return
        visiting.add(action_id)
        for dependency in actions[action_id]["prerequisite_action_ids"]:
            visit(dependency)
        visiting.remove(action_id)
        visited.add(action_id)

    for action_id in actions:
        visit(action_id)

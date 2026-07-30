"""Deterministic obligation-delta and requirement-coverage projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_LIMITED_STATES = {"bounded", "serviced"}
_SATISFIED_STATES = {"discharged"}
_PENDING_STATES = {"open", "reopened"}


def apply_obligation_deltas(
    obligations: list[dict[str, Any]],
    deltas: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Apply already accepted deltas, preserving complete obligation bodies."""
    if not isinstance(deltas, list) or any(
        not isinstance(item, dict) for item in deltas
    ):
        raise ValueError("obligation_delta must be an object array")
    projected = deepcopy(obligations)
    by_id = {
        str(item.get("obligation_id") or ""): item for item in projected
        if isinstance(item, dict) and item.get("obligation_id")
    }
    if len(by_id) != len(projected):
        raise ValueError("current obligations must have unique obligation_id")
    changed: set[str] = set()
    for delta in deltas:
        obligation_id = _required(delta, "obligation_id")
        from_state = _required(delta, "from_state")
        to_state = _required(delta, "to_state")
        obligation = by_id.get(obligation_id)
        if obligation is None:
            if from_state != "absent" or not isinstance(delta.get("obligation"), dict):
                raise ValueError("new obligation requires absent state and body")
            obligation = deepcopy(delta["obligation"])
            if (
                obligation.get("obligation_id") != obligation_id
                or obligation.get("status") != to_state
            ):
                raise ValueError("new obligation body does not match delta")
            obligation.setdefault("requirement_refs", [])
            projected.append(obligation)
            by_id[obligation_id] = obligation
        else:
            if str(obligation.get("status") or "") != from_state:
                raise ValueError(
                    f"obligation delta from_state is stale: {obligation_id}"
                )
            before_refs = _refs(obligation.get("requirement_refs"))
            if "to_requirement_refs" in delta:
                if _refs(delta.get("from_requirement_refs")) != before_refs:
                    raise ValueError(
                        f"obligation requirement mapping is stale: {obligation_id}"
                    )
                obligation["requirement_refs"] = _refs(
                    delta.get("to_requirement_refs")
                )
            obligation["status"] = to_state
        changed.add(f"obligation:{obligation_id}")
    return projected, changed


def project_requirement_coverage(
    *,
    requirements: list[dict[str, Any]],
    obligations: list[dict[str, Any]],
    changed_obligation_refs: set[str] | None = None,
    edge_required_ids: set[str] | None = None,
    node_required_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    changed = changed_obligation_refs or set()
    required = edge_required_ids or set()
    node_required = (
        {
            _requirement_id(requirement)
            for requirement in requirements
        }
        if node_required_ids is None else node_required_ids
    )
    rows = []
    for requirement in requirements:
        requirement_id = _requirement_id(requirement)
        mapped = [
            item for item in obligations
            if requirement_id in _refs(item.get("requirement_refs"))
        ]
        refs = [
            f"obligation:{item['obligation_id']}" for item in mapped
        ]
        statuses = [
            str(item.get("status") or "") for item in mapped
        ]
        edge_required = requirement_id in required
        rows.append({
            "requirement_id": requirement_id,
            "description": str(
                requirement.get("title_zh")
                or requirement.get("description_zh")
                or requirement.get("description")
                or ""
            ),
            "obligation_refs": refs,
            "obligation_statuses": statuses,
            "changed": any(item in changed for item in refs),
            "node_required": requirement_id in node_required,
            "edge_required": edge_required,
            "satisfaction": _satisfaction(statuses, edge_required=edge_required),
        })
    return rows


def _satisfaction(statuses: list[str], *, edge_required: bool) -> str:
    values = set(statuses)
    if values & _SATISFIED_STATES:
        return "satisfied"
    if values & _LIMITED_STATES:
        return "limited"
    if not values:
        return "missing" if edge_required else "pending"
    if values & _PENDING_STATES:
        return "missing" if edge_required else "pending"
    return "missing"


def _requirement_id(value: dict[str, Any]) -> str:
    text = value.get("requirement_id")
    if not isinstance(text, str) or not text:
        raise ValueError("requirement_id is required")
    return text.removeprefix("requirement:")


def _required(value: dict[str, Any], field: str) -> str:
    text = value.get(field)
    if not isinstance(text, str) or not text:
        raise ValueError(f"{field} is required")
    return text


def _refs(value: Any) -> list[str]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError("requirement_refs must be a string array")
    return list(dict.fromkeys(
        item.removeprefix("requirement:") for item in value
    ))

"""Validate one Agent-declared obligation requirement reference."""

from __future__ import annotations

from typing import Any

from tools.cli.client import FactorTesterClient

from ..authoring.declared_links import DeclaredReportReference


def validate_entry_requirement_reference(
    *,
    reference: DeclaredReportReference,
    scope: Any,
    client: FactorTesterClient,
) -> dict[str, Any]:
    requirement_id = _requirement_id(reference.target_ref)
    instance_id, branch_id = _graph_branch(scope)
    value = client.get_current_graph_requirement(
        instance_id, branch_id, requirement_id,
    )
    requirement = value.get("requirement")
    if (
        not isinstance(requirement, dict)
        or str(requirement.get("requirement_id") or "") != requirement_id
    ):
        raise ValueError(
            "obligation-requirement authority did not return the exact requirement"
        )
    return {
        key: item
        for key, item in {
            "graph_ref": value.get("graph_ref"),
            "node_id": value.get("node_id"),
            "requirement_sources": value.get("requirement_sources"),
            "requirement_id": requirement_id,
            "title_zh": requirement.get("title_zh"),
            "gate_policy": requirement.get("gate_policy"),
            "detail_ref": f"graph-requirement:{requirement_id}",
        }.items()
        if item not in {None, ""}
    }


def _requirement_id(target_ref: str) -> str:
    prefix = "requirement:"
    if not target_ref.startswith(prefix) or target_ref == prefix:
        raise ValueError(
            "obligation requirement reference must start with requirement:"
        )
    return target_ref.removeprefix(prefix)


def _graph_branch(scope: Any) -> tuple[str, str]:
    value = str(getattr(scope, "branch_ref", "") or "")
    parts = value.split(":")
    if (
        len(parts) != 3
        or parts[0] != "graph-branch"
        or not parts[1]
        or not parts[2]
    ):
        raise ValueError(
            "obligation requirement reference requires an explicit graph branch"
        )
    return parts[1], parts[2]

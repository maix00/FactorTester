"""Validate Agent-declared references owned by one Research Graph branch."""

from __future__ import annotations

from typing import Any

from tools.cli.client import FactorTesterClient

from ..authoring.declared_links import DeclaredReportReference


_CYCLE_FIELDS = {
    "claim": "claim_id",
    "obligation": "obligation_id",
    "task": "task_ref",
}


def validate_cycle_reference(
    *,
    reference: DeclaredReportReference,
    scope: Any,
    client: FactorTesterClient,
) -> dict[str, Any]:
    instance_id, branch_id = _graph_branch(scope)
    object_type = reference.kind
    object_id, trace_id = _object_identity(
        kind=object_type,
        target_ref=reference.target_ref,
    )
    value = client.get_research_cycle_object(
        instance_id,
        branch_id,
        object_type,
        object_id,
        trace_id=trace_id,
    )
    field = _CYCLE_FIELDS[object_type]
    if str(value.get(field) or "") != object_id:
        raise ValueError(
            "research cycle authority did not return the exact reference"
        )
    return _bounded(value)


def _graph_branch(scope: Any) -> tuple[str, str]:
    reference = str(getattr(scope, "branch_ref", "") or "")
    parts = reference.split(":")
    if (
        len(parts) != 3
        or parts[0] != "graph-branch"
        or not parts[1]
        or not parts[2]
    ):
        raise ValueError(
            "Agent-authored cycle reference requires an explicit graph branch"
        )
    return parts[1], parts[2]


def _object_identity(*, kind: str, target_ref: str) -> tuple[str, str | None]:
    prefix = {
        "claim": "claim:",
        "obligation": "obligation:",
    }.get(kind)
    if prefix:
        if not target_ref.startswith(prefix) or target_ref == prefix:
            raise ValueError(f"{kind} reference must start with {prefix}")
        return target_ref.removeprefix(prefix), None
    if kind == "task":
        if not target_ref.strip():
            raise ValueError("task reference is empty")
        return target_ref, None
    raise ValueError(f"unsupported research cycle reference kind: {kind}")


def _bounded(value: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version", "object_kind", "claim_id", "claim_ref",
        "claim_type", "evidence_state", "obligation_id", "obligation_kind",
        "epistemic_question", "status", "materiality", "task_ref",
    }
    return {key: value[key] for key in fields if key in value}

"""Compact, server-derived orchestration for Active Graph changes."""

from __future__ import annotations

from typing import Any

import settings as Settings
from server.services.maintenance_cases import MaintenanceCaseStore
from server.services.research_graph import activation_gate
from server.services.research_graph.active_pointer import (
    activate_graph,
    load_active_graph,
)
from server.services.research_graph.governance_workflow import (
    authorize_graph_activation,
)
from server.services.research_graph.protocol import GraphActivationBlocked
from server.services.research_graph.upgrade_validation import (
    record_upgrade_validation,
)
from server.services.research_graph.versions import load_graph


_GATE_ORDER = (
    "independent_review",
    "deterministic_validation",
)
_OPTIONAL_GATES = ("grill_audit",)


def activation_preflight(
    *,
    graph_id: str,
    version: int,
    owner_user_id: str,
) -> dict[str, Any]:
    """Return bounded readiness with its recoverable public proposal."""
    graph = load_graph(graph_id=graph_id, version=version)
    if graph is None:
        raise KeyError("graph version not found")
    active = load_active_graph(graph_id=graph_id)
    active_version = (
        int(active["version"]) if active is not None else None
    )
    already_active = active_version == int(version)
    rollback_version = (
        int(graph.get("parent_version") or 0) or None
        if already_active
        else active_version
    )
    gates = (
        []
        if already_active
        else _matching_target_gates(
            graph_id=graph_id,
            version=version,
            graph_hash=str(graph["content_hash"]),
            owner_user_id=owner_user_id,
        )
    )
    if len(gates) > 1:
        raise GraphActivationBlocked(
            "activation proposal Gate is ambiguous for target Graph"
        )
    gate = gates[0] if gates else None
    readiness = (
        {}
        if gate is None
        else activation_gate.activation_gate_readiness(gate)
    )
    completed = [
        name for name in (*_GATE_ORDER, *_OPTIONAL_GATES)
        if readiness.get(name) is True
    ]
    missing = (
        ["activation_proposal"]
        if gate is None and not already_active
        else [
            name for name in _GATE_ORDER
            if readiness.get(name) is not True
        ]
    )
    result = {
        "graph_id": graph_id,
        "active_version": active_version,
        "target_version": int(version),
        "rollback_version": rollback_version,
        "ready_for_human_authorization": (
            not already_active and not missing
        ),
        "completed_gates": completed,
        "missing_gates": [] if already_active else missing,
        "already_active": already_active,
    }
    if gate is not None:
        proposal_id = str(gate["case_id"])
        result.update({
            "proposal_id": proposal_id,
            "next_command": _next_gate_command(
                graph_id=graph_id,
                version=version,
                proposal_id=proposal_id,
                missing=missing,
            ),
        })
    return result


def _next_gate_command(
    *,
    graph_id: str,
    version: int,
    proposal_id: str,
    missing: list[str],
) -> str:
    if "independent_review" in missing:
        return (
            "factortester research-graph proposal "
            f"{proposal_id}"
        )
    if "deterministic_validation" in missing:
        return (
            "factortester research-graph activate "
            f"{graph_id} {int(version)} --yes"
        )
    return (
        "factortester research-graph activate "
        f"{graph_id} {int(version)}"
    )


def activate_reviewed_graph(
    *,
    graph_id: str,
    version: int,
    owner_user_id: str,
    approval_ref: str,
) -> dict[str, Any]:
    """Authorize and consume one fully reviewed exact Graph Gate."""
    graph = load_graph(graph_id=graph_id, version=version)
    if graph is None:
        raise KeyError("graph version not found")
    active = load_active_graph(graph_id=graph_id)
    from_version = (
        int(active["version"]) if active is not None else None
    )
    if from_version == int(version):
        return _activation_receipt(
            graph_id=graph_id,
            from_version=from_version,
            to_version=int(version),
            rollback_version=(
                int(graph.get("parent_version") or 0) or None
            ),
            promoted_continuation_count=0,
            already_active=True,
        )
    gate = _target_gate(
        graph_id=graph_id,
        version=version,
        graph_hash=str(graph["content_hash"]),
        owner_user_id=owner_user_id,
    )
    readiness = activation_gate.activation_gate_readiness(gate)
    _require_non_blocking_optional_audit(gate)
    if readiness.get("independent_review") is not True:
        raise GraphActivationBlocked(
            "activation blocked by: independent_review"
        )
    upgrade_validation: dict[str, Any] | None = None
    if readiness.get("deterministic_validation") is not True:
        upgrade_validation = record_upgrade_validation(
            graph_id=graph_id,
            version=version,
            owner_user_id=owner_user_id,
            proposal_id=str(gate["case_id"]),
        )
        gate = _target_gate(
            graph_id=graph_id,
            version=version,
            graph_hash=str(graph["content_hash"]),
            owner_user_id=owner_user_id,
        )
        readiness = activation_gate.activation_gate_readiness(gate)
    missing = [
        name for name in _GATE_ORDER if readiness.get(name) is not True
    ]
    if missing:
        raise GraphActivationBlocked(
            "activation blocked by: " + ", ".join(missing)
        )
    if not readiness["human_authorization"]:
        authorize_graph_activation(
            owner_user_id=owner_user_id,
            graph_id=graph_id,
            graph_version=version,
            proposal_id=str(gate["case_id"]),
            graph_hash=str(graph["content_hash"]),
            diff_hash=_gate_diff_hash(
                gate,
                graph_id=graph_id,
                version=version,
                graph_hash=str(graph["content_hash"]),
            ),
            conversation_ref=str(gate["conversation_ref"]),
            approval_ref=approval_ref,
        )
    activated = activate_graph(
        graph_id=graph_id,
        source_version=version,
        actor=owner_user_id,
        human_authorization_id=str(gate["case_id"]),
    )
    receipt = _activation_receipt(
        graph_id=graph_id,
        from_version=from_version,
        to_version=int(version),
        rollback_version=from_version,
        promoted_continuation_count=int(
            activated.get("promoted_continuation_count") or 0
        ),
        already_active=False,
    )
    if upgrade_validation is not None:
        evidence = upgrade_validation["evidence"]
        receipt["upgrade_validation"] = {
            "validation_id": upgrade_validation["validation_id"],
            "validated_branch_count": int(
                evidence["validated_branch_count"]
            ),
            "persistent_shadow_count": int(
                evidence["persistent_shadow_count"]
            ),
            "shadow_cleanup": str(evidence["shadow_cleanup"]),
        }
    return receipt


def _require_non_blocking_optional_audit(gate: dict[str, Any]) -> None:
    dispositions = [
        str(reference).rsplit(":", 1)[-1]
        for reference in gate.get("change_refs") or []
        if str(reference).startswith("gate-grill:")
    ]
    blocked = [
        disposition for disposition in dispositions
        if disposition != "approved"
    ]
    if blocked:
        raise GraphActivationBlocked(
            "activation blocked by optional grill: "
            + ", ".join(sorted(set(blocked)))
        )


def _activation_receipt(
    *,
    graph_id: str,
    from_version: int | None,
    to_version: int,
    rollback_version: int | None,
    promoted_continuation_count: int,
    already_active: bool,
) -> dict[str, Any]:
    return {
        "graph_id": graph_id,
        "from_version": from_version,
        "to_version": to_version,
        "rollback_version": rollback_version,
        "already_active": already_active,
        "promoted_continuation_count": promoted_continuation_count,
    }


def _gate_diff_hash(
    gate: dict[str, Any],
    *,
    graph_id: str,
    version: int,
    graph_hash: str,
) -> str:
    prefix = f"graph-proposal:{graph_id}@{version}:{graph_hash}:"
    values = [
        ref[len(prefix):]
        for ref in gate["affected_refs"]
        if ref.startswith(prefix)
    ]
    if len(values) != 1:
        raise GraphActivationBlocked(
            "activation proposal Gate target is invalid"
        )
    return values[0]


def _target_gate(
    *,
    graph_id: str,
    version: int,
    graph_hash: str,
    owner_user_id: str,
) -> dict[str, Any]:
    matches = _matching_target_gates(
        graph_id=graph_id,
        version=version,
        graph_hash=graph_hash,
        owner_user_id=owner_user_id,
    )
    if not matches:
        raise GraphActivationBlocked(
            "activation proposal Gate not found for target Graph"
        )
    if len(matches) != 1:
        raise GraphActivationBlocked(
            "activation proposal Gate is ambiguous for target Graph"
        )
    return matches[0]


def _matching_target_gates(
    *,
    graph_id: str,
    version: int,
    graph_hash: str,
    owner_user_id: str,
) -> list[dict[str, Any]]:
    prefix = (
        f"graph-proposal:{graph_id}@{int(version)}:{graph_hash}:"
    )
    matches = []
    for case in MaintenanceCaseStore(
        Settings.CACHE_DB_PATH
    ).find_cases_by_affected_ref_prefix(
        owner_user_id=owner_user_id,
        kind="approval_gate",
        ref_prefix=prefix,
        required_ref=(
            f"gate-action:{activation_gate.ACTIVATE_ACTION}"
        ),
        limit=2,
    ):
        if f"gate-action:{activation_gate.ACTIVATE_ACTION}" not in (
            case["affected_refs"]
        ):
            continue
        if sum(
            ref.startswith(prefix) for ref in case["affected_refs"]
        ) == 1:
            matches.append(case)
    return matches

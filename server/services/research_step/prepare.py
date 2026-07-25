"""Ephemeral configuration-identity contracts for one Evidence Action."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools.cli.protocols.research_step import (
    contract_hash,
    context_ref,
    identifier,
    normalize_configuration,
    validate_prepare_contract,
)
from .inspect import validate_inspect_contract


def build_prepare_contract(
    inspect_contract: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    """Validate N configuration identities; never invent RunSpec snapshots."""
    validate_inspect_contract(inspect_contract)
    if not isinstance(request, dict) or set(request) != {
        "schema_version", "context_ref", "action_id", "configurations",
    }:
        raise ValueError("research step prepare request fields are invalid")
    if request.get("schema_version") != 1:
        raise ValueError("prepare request schema_version must be 1")
    current_context = context_ref(request.get("context_ref"))
    if current_context != inspect_contract["graph"]["context_ref"]:
        raise ValueError("prepare request context_ref is stale")
    action_id = identifier(request.get("action_id"), "action_id")
    if action_id != inspect_contract["action"]["action_id"]:
        raise ValueError("prepare request action_id is stale")
    raw = request.get("configurations")
    if not isinstance(raw, list) or not raw:
        raise ValueError("configurations must be a non-empty array")
    configurations = [normalize_configuration(item) for item in raw]
    _require_unique_configurations(configurations)
    comparisons = set(inspect_contract["action"]["comparison_ids"])
    unknown = sorted({
        item["comparison_id"] for item in configurations
        if item["comparison_id"] not in comparisons
    })
    if unknown:
        raise ValueError(
            "configuration request uses unknown comparison_id: "
            + ", ".join(unknown)
        )
    invalid_roles = sorted({
        item["trial_role"] for item in configurations
        if item["trial_role"] not in inspect_contract["action"][
            "comparison_roles"
        ][item["comparison_id"]]
    })
    if invalid_roles:
        raise ValueError(
            "configuration trial_role is not declared: "
            + ", ".join(invalid_roles)
        )
    value = {
        "schema_version": 1,
        "operation": "research.step.prepare",
        "inspect_context_ref": current_context,
        "binding": deepcopy(inspect_contract["binding"]),
        "cas": deepcopy(inspect_contract["cas"]),
        "action": deepcopy(inspect_contract["action"]),
        "configuration_requests": configurations,
        "execution_ready": False,
        "authority_refresh_required": True,
        "capability_gaps": [{
            "capability_id": (
                "research-run.immutable-configuration-snapshot"
            ),
            "reason": (
                "stable immutable configuration snapshot preview is "
                "unavailable"
            ),
        }],
    }
    value["contract_hash"] = contract_hash(value)
    validate_prepare_contract(value)
    return value


def _require_unique_configurations(
    configurations: list[dict[str, Any]],
) -> None:
    identities = [
        (item["configuration_id"], item["configuration_revision"])
        for item in configurations
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("configuration identities must be unique")

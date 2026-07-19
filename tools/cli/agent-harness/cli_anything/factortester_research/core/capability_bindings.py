"""Bind capability ids to approved, source-verified implementations."""

from __future__ import annotations

from typing import Any

from .capability_registry import capability_descriptor


def resolve_capability_ids(
    *,
    capability_ids: list[str],
    contracts: dict[str, dict[str, Any]],
    product_group: str,
    grants: set[str],
    required_by: str,
    source_states: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bindings: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for capability_id in sorted(set(capability_ids)):
        contract = contracts.get(capability_id)
        if contract is None:
            gaps.append({
                "capability_id": capability_id,
                "reason": "capability_contract_missing",
                "required_by": required_by,
            })
            continue
        descriptor = capability_descriptor(contract)
        product_candidates = sorted(
            (
                implementation
                for implementation in contract["implementations"]
                if implementation["approval_status"] == "approved"
                and (
                    product_group in implementation["product_scopes"]
                    or "all" in implementation["product_scopes"]
                )
            ),
            key=lambda item: str(item["implementation_id"]),
        )
        if not product_candidates:
            gaps.append({
                "capability_id": capability_id,
                **descriptor,
                "reason": "approved_product_implementation_missing",
                "required_by": required_by,
            })
            continue
        verified_candidates = [
            implementation
            for implementation in product_candidates
            if source_states.get(
                str(implementation["implementation_id"]),
                {"status": "internal"},
            )["status"] in {"internal", "verified"}
        ]
        if not verified_candidates:
            source_state = source_states[
                str(product_candidates[0]["implementation_id"])
            ]
            reason_by_status = {
                "mismatch": "provider_fingerprint_mismatch",
                "unavailable": "provider_source_unavailable",
                "unapproved": "provider_source_fingerprint_unapproved",
            }
            gaps.append({
                "capability_id": capability_id,
                **descriptor,
                "reason": reason_by_status[source_state["status"]],
                **{
                    key: source_state[key]
                    for key in (
                        "implementation_id",
                        "expected_sha256",
                        "observed_sha256",
                    )
                    if key in source_state
                },
                "required_by": required_by,
            })
            continue
        candidates = [
            implementation
            for implementation in verified_candidates
            if not implementation.get("requires_execution_approval", False)
            or implementation.get("kind") == "skill"
            or implementation["implementation_id"] in grants
        ]
        if not candidates:
            gaps.append({
                "capability_id": capability_id,
                **descriptor,
                "reason": "execution_approval_required",
                "candidate_implementation_ids": [
                    item["implementation_id"] for item in verified_candidates
                ],
                "required_by": required_by,
            })
            continue
        implementation = candidates[0]
        requires_execution_approval = bool(
            implementation.get("requires_execution_approval", False)
        )
        explicitly_granted = (
            implementation["implementation_id"] in grants
        )
        source_state = source_states.get(
            str(implementation["implementation_id"]),
            {"status": "internal"},
        )
        bindings.append({
            "capability_id": capability_id,
            **descriptor,
            "implementation_id": implementation["implementation_id"],
            "provider": str(implementation.get("provider") or ""),
            "kind": implementation["kind"],
            "execution_mode": implementation["execution_mode"],
            "execution_approval_granted": (
                not requires_execution_approval or explicitly_granted
            ),
            "local_execution_approval_required": (
                implementation.get("kind") == "skill"
                and requires_execution_approval
                and not explicitly_granted
            ),
            "execution_approval_source": (
                "explicit_grant"
                if explicitly_granted
                else (
                    "catalog_default"
                    if not requires_execution_approval
                    else "none"
                )
            ),
            **({
                "source_fingerprint": source_state["observed_sha256"],
            } if source_state["status"] == "verified" else {}),
            "required_by": required_by,
        })
    return bindings, gaps

"""Stable machine references that connect obligations to deterministic gates."""

from __future__ import annotations

from typing import Any


DATA_REQUIREMENT_REFS = frozenset({
    "data-availability.scope",
    "data-provenance.point-in-time",
})
POINT_IN_TIME_REQUIREMENT_REF = "data-provenance.point-in-time"


def data_obligation_gate_satisfied(
    checkpoint: dict[str, Any] | None,
    *,
    provenance_integrity_status: str = "",
) -> bool:
    """Require explicit, adjudicated debt when PIT remains unverified."""
    obligations = (
        checkpoint.get("obligations")
        if isinstance(checkpoint, dict)
        else None
    )
    if not isinstance(obligations, list):
        obligations = []
    relevant = [
        item for item in obligations
        if isinstance(item, dict)
        and item.get("materiality") == "decision_blocking"
        and _is_data_obligation(item)
    ]
    if any(item.get("status") in {"open", "reopened"} for item in relevant):
        return False
    if provenance_integrity_status == "bounded_unverified":
        return any(
            item.get("status") == "bounded"
            and _has_point_in_time_requirement(item)
            for item in relevant
        )
    return provenance_integrity_status in {"", "verified", "unavailable"}


def _is_data_obligation(item: dict[str, Any]) -> bool:
    refs = set(item.get("requirement_refs") or [])
    if refs & DATA_REQUIREMENT_REFS:
        return True
    # Early Research Cycle bootstrap records predate requirement_refs.  Keep
    # their explicit semantic kind/criterion authoritative instead of making a
    # valid data-debt transition impossible after a server restart.
    return (
        item.get("obligation_kind") == "data_availability_for_trial_design"
        or (
            isinstance(item.get("discharge_criterion"), dict)
            and item["discharge_criterion"].get("rule_ref")
            == "research-rule:data-availability-exact-scope"
        )
    )


def _has_point_in_time_requirement(item: dict[str, Any]) -> bool:
    refs = set(item.get("requirement_refs") or [])
    return (
        POINT_IN_TIME_REQUIREMENT_REF in refs
        or item.get("obligation_kind") == "data_availability_for_trial_design"
        or (
            isinstance(item.get("discharge_criterion"), dict)
            and item["discharge_criterion"].get("rule_ref")
            == "research-rule:data-availability-exact-scope"
        )
    )

"""Stable machine references that connect obligations to deterministic gates."""

from __future__ import annotations

from typing import Any


DATA_REQUIREMENT_REFS = frozenset({
    "data-availability.scope",
})


def data_obligation_gate_satisfied(
    checkpoint: dict[str, Any] | None,
) -> bool:
    """Block only unresolved, decision-blocking data obligations."""
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
    return not any(
        item.get("status") in {"open", "reopened"} for item in relevant
    )


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

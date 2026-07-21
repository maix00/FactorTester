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
        and DATA_REQUIREMENT_REFS.intersection(
            item.get("requirement_refs") or []
        )
    ]
    if any(item.get("status") in {"open", "reopened"} for item in relevant):
        return False
    if provenance_integrity_status == "bounded_unverified":
        return any(
            item.get("status") == "bounded"
            and POINT_IN_TIME_REQUIREMENT_REF
            in (item.get("requirement_refs") or [])
            for item in relevant
        )
    return provenance_integrity_status in {"", "verified", "unavailable"}

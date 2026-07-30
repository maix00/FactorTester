"""Authoritative Research Cycle deltas derived from accepted checkpoint state."""

from __future__ import annotations

from typing import Any


def accepted_checkpoint_deltas(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Return only state changes that survived replay into the checkpoint."""
    before_claims = _by_id(before.get("claims"), "claim_id")
    claim_deltas = []
    for claim in after.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("claim_id") or "")
        previous = before_claims.get(claim_id)
        if previous is None:
            continue
        from_state = str(previous.get("evidence_state") or "")
        to_state = str(claim.get("evidence_state") or "")
        if from_state != to_state:
            claim_deltas.append({
                "claim_id": claim_id,
                "from_state": from_state,
                "to_state": to_state,
            })

    before_obligations = _by_id(before.get("obligations"), "obligation_id")
    obligation_deltas = []
    for obligation in after.get("obligations") or []:
        if not isinstance(obligation, dict):
            continue
        obligation_id = str(obligation.get("obligation_id") or "")
        previous = before_obligations.get(obligation_id)
        from_state = (
            str(previous.get("status") or "")
            if previous is not None else "absent"
        )
        to_state = str(obligation.get("status") or "")
        from_refs = _refs(
            previous.get("requirement_refs") if previous is not None else []
        )
        to_refs = _refs(obligation.get("requirement_refs"))
        if from_state == to_state and from_refs == to_refs:
            continue
        delta: dict[str, Any] = {
            "obligation_id": obligation_id,
            "from_state": from_state,
            "to_state": to_state,
        }
        if from_refs != to_refs:
            delta["from_requirement_refs"] = from_refs
            delta["to_requirement_refs"] = to_refs
        obligation_deltas.append(delta)
    return {
        "obligation_deltas": obligation_deltas,
        "claim_deltas": claim_deltas,
    }


def _by_id(value: Any, field: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    return {
        str(item.get(field) or ""): item
        for item in value
        if isinstance(item, dict) and item.get(field)
    }


def _refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(
        str(item) for item in value if isinstance(item, str) and item
    ))

"""Deterministic replay into one bounded Research Cycle checkpoint."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..protocol import (
    assert_no_skill_identity,
    json_hash,
    serialize_bounded_trace_evidence,
)
from .adjudication import validate_adjudication_proposal
from .closure import validate_search_exhaustion_proposal
from .contracts import (
    sha256,
    validate_research_claim,
)
from .obligations import validate_verification_obligation
from .events import apply_research_cycle_event


def validate_research_cycle_checkpoint(
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    """Validate the compact accepted state and pending proposals."""
    if not isinstance(checkpoint, dict):
        raise ValueError("research cycle checkpoint must be an object")
    if checkpoint.get("schema_version") != 1:
        raise ValueError("research cycle checkpoint schema_version must be 1")
    assert_no_skill_identity(checkpoint, location="research cycle checkpoint")
    value = deepcopy(checkpoint)
    declared_hash = value.pop("projection_hash", "")
    for field in ("contract_hash", "methodology_hash"):
        value[field] = sha256(value.get(field), field=field)
    trial_plan_hash = value.get("trial_plan_hash")
    value["trial_plan_hash"] = (
        ""
        if trial_plan_hash in (None, "")
        else sha256(trial_plan_hash, field="trial_plan_hash")
    )
    value["claims"] = _claims(
        value.get("claims"),
        contract_hash=value["contract_hash"],
    )
    value["obligations"] = _obligations(
        value.get("obligations"),
        contract_hash=value["contract_hash"],
        methodology_hash=value["methodology_hash"],
        claim_ids={item["claim_id"] for item in value["claims"]},
    )
    value["pending_adjudications"] = _pending_adjudications(
        value.get("pending_adjudications"),
        contract_hash=value["contract_hash"],
        trial_plan_hash=value["trial_plan_hash"],
        methodology_hash=value["methodology_hash"],
    )
    value["pending_closure"] = _closure_proposal(
        value.get("pending_closure"),
        contract_hash=value["contract_hash"],
        methodology_hash=value["methodology_hash"],
    )
    value["closure"] = _closure_proposal(
        value.get("closure"),
        contract_hash=value["contract_hash"],
        methodology_hash=value["methodology_hash"],
    )
    computed_hash = json_hash(value)
    if declared_hash and sha256(
        declared_hash,
        field="projection_hash",
    ) != computed_hash:
        raise ValueError("research cycle projection_hash mismatch")
    value["projection_hash"] = computed_hash
    serialize_bounded_trace_evidence(value)
    return value


def replay_research_cycle_events(
    checkpoint: dict[str, Any],
    *,
    events: list[dict[str, Any]],
    expected_base_hash: str,
    requirement_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay all events on a copy or fail without a partial projection."""
    current = validate_research_cycle_checkpoint(checkpoint)
    if current["projection_hash"] != sha256(
        expected_base_hash,
        field="expected_base_hash",
    ):
        raise ValueError("base projection hash is stale")
    if not isinstance(events, list):
        raise ValueError("research cycle events must be an array")
    candidate = deepcopy(current)
    for event in events:
        candidate = apply_research_cycle_event(
            candidate,
            event,
            requirement_catalog=requirement_catalog,
        )
    candidate.pop("projection_hash", None)
    return validate_research_cycle_checkpoint(candidate)


def _claims(value: Any, *, contract_hash: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("research cycle claims must be an array")
    claims = [validate_research_claim(item) for item in value]
    _unique_ids(claims, field="claim_id")
    if any(item["contract_hash"] != contract_hash for item in claims):
        raise ValueError("Claim contract_hash does not match checkpoint")
    return claims


def _obligations(
    value: Any,
    *,
    contract_hash: str,
    methodology_hash: str,
    claim_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("research cycle obligations must be an array")
    obligations = [validate_verification_obligation(item) for item in value]
    _unique_ids(obligations, field="obligation_id")
    for item in obligations:
        if (
            item["contract_hash"] != contract_hash
            or item["methodology_hash"] != methodology_hash
        ):
            raise ValueError("obligation identity does not match checkpoint")
        if not set(item["claim_ids"]).issubset(claim_ids):
            raise ValueError("obligation references an unknown Claim")
    return obligations


def _pending_adjudications(
    value: Any,
    *,
    contract_hash: str,
    trial_plan_hash: str,
    methodology_hash: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("pending_adjudications must be an array")
    proposals = [validate_adjudication_proposal(item) for item in value]
    _unique_ids(proposals, field="proposal_hash")
    for proposal in proposals:
        if (
            proposal["contract_hash"] != contract_hash
            or proposal["trial_plan_hash"] != trial_plan_hash
            or proposal["methodology_hash"] != methodology_hash
        ):
            raise ValueError("pending adjudication identity is stale")
    return proposals


def _closure_proposal(
    value: Any,
    *,
    contract_hash: str,
    methodology_hash: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    proposal = validate_search_exhaustion_proposal(value)
    if (
        proposal["contract_hash"] != contract_hash
        or proposal["methodology_hash"] != methodology_hash
    ):
        raise ValueError("search exhaustion proposal identity is stale")
    return proposal


def _unique_ids(items: list[dict[str, Any]], *, field: str) -> None:
    identifiers = [str(item[field]) for item in items]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"duplicate {field}")

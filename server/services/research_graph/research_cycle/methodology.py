"""Skill-neutral methodology-change protocol."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..protocol import (
    assert_no_skill_identity,
    json_hash,
    serialize_bounded_trace_evidence,
)
from .contracts import (
    object_value,
    required_text,
    sha256,
    string_array,
)


_COMPATIBILITY = {
    "implementation_only",
    "semantic_change",
}


def validate_methodology_change_proposal(
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Validate a bounded semantic diff without concrete Skill identity."""
    if not isinstance(proposal, dict):
        raise ValueError("methodology change proposal must be an object")
    if proposal.get("schema_version") != 1:
        raise ValueError("methodology change schema_version must be 1")
    assert_no_skill_identity(
        proposal,
        location="methodology change proposal",
    )
    value = deepcopy(proposal)
    declared_hash = value.pop("proposal_hash", "")
    declared_review_hash = value.pop("review_input_hash", "")
    required_text(value.get("proposal_id"), field="proposal_id")
    for field in (
        "current_descriptor_hash",
        "proposed_descriptor_hash",
        "rollback_descriptor_hash",
    ):
        value[field] = sha256(value.get(field), field=field)
    object_value(value.get("semantic_diff"), field="semantic_diff")
    value["affected_contract_predicate"] = _validate_predicate(
        value.get("affected_contract_predicate")
    )
    object_value(value.get("expected_cost"), field="expected_cost")
    for field in (
        "evidence_refs",
        "counterexample_refs",
        "validation_refs",
        "failed_case_refs",
        "implementation_validation_refs",
    ):
        string_array(value.get(field), field=field)
    if value.get("compatibility") not in _COMPATIBILITY:
        raise ValueError("invalid methodology compatibility")
    review_hash = json_hash({
        key: item
        for key, item in value.items()
        if key != "proposal_id"
    })
    if declared_review_hash and sha256(
        declared_review_hash,
        field="review_input_hash",
    ) != review_hash:
        raise ValueError("methodology review_input_hash mismatch")
    value["review_input_hash"] = review_hash
    computed_hash = json_hash(value)
    if declared_hash and sha256(
        declared_hash,
        field="proposal_hash",
    ) != computed_hash:
        raise ValueError("methodology proposal_hash mismatch")
    value["proposal_hash"] = computed_hash
    serialize_bounded_trace_evidence(value)
    return value


def build_methodology_impact_plan(
    proposal: dict[str, Any],
    contracts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Select affected Contracts without changing branches or Jobs."""
    value = validate_methodology_change_proposal(proposal)
    if not isinstance(contracts, list):
        raise ValueError("contracts must be an array")
    affected: list[str] = []
    unaffected: list[str] = []
    undetermined: list[str] = []
    for contract in contracts:
        item = object_value(contract, field="contract")
        contract_ref = required_text(
            item.get("contract_ref"),
            field="contract_ref",
        )
        matched = _evaluate_predicate(
            value["affected_contract_predicate"],
            item,
        )
        target = (
            affected
            if matched is True
            else unaffected
            if matched is False
            else undetermined
        )
        target.append(contract_ref)
    semantic = value["compatibility"] == "semantic_change"
    return {
        "proposal_hash": value["proposal_hash"],
        "review_input_hash": value["review_input_hash"],
        "affected_contract_refs": affected,
        "unaffected_contract_refs": unaffected,
        "undetermined_contract_refs": undetermined,
        "proposed_reopen_refs": affected if semantic else [],
        "unaffected_branches_and_jobs_action": "continue",
        "requires_maintenance_case": semantic,
    }


def _validate_predicate(value: Any) -> dict[str, Any]:
    predicate = object_value(value, field="affected_contract_predicate")
    combinators = [key for key in ("all", "any") if key in predicate]
    if combinators:
        if len(combinators) != 1 or len(predicate) != 1:
            raise ValueError("predicate combinator must be exclusive")
        children = predicate[combinators[0]]
        if not isinstance(children, list) or not children:
            raise ValueError("predicate combinator requires children")
        return {
            combinators[0]: [
                _validate_predicate(child) for child in children
            ]
        }
    field = required_text(predicate.get("field"), field="predicate.field")
    operators = [
        key for key in ("equals", "in", "contains_any")
        if key in predicate
    ]
    if len(operators) != 1 or len(predicate) != 2:
        raise ValueError("predicate requires one supported operator")
    operator = operators[0]
    expected = predicate[operator]
    if operator in {"in", "contains_any"} and (
        not isinstance(expected, list) or not expected
    ):
        raise ValueError(f"predicate {operator} requires a non-empty array")
    return {"field": field, operator: deepcopy(expected)}


def _evaluate_predicate(
    predicate: dict[str, Any],
    facts: dict[str, Any],
) -> bool | None:
    if "all" in predicate:
        results = [
            _evaluate_predicate(child, facts)
            for child in predicate["all"]
        ]
        return (
            False if False in results
            else None if None in results
            else True
        )
    if "any" in predicate:
        results = [
            _evaluate_predicate(child, facts)
            for child in predicate["any"]
        ]
        return (
            True if True in results
            else None if None in results
            else False
        )
    actual = _field_value(facts, str(predicate["field"]))
    if actual is _MISSING:
        return None
    if "equals" in predicate:
        return actual == predicate["equals"]
    if "in" in predicate:
        return actual in predicate["in"]
    expected = predicate["contains_any"]
    if not isinstance(actual, (list, tuple, set, str)):
        return False
    return any(item in actual for item in expected)


_MISSING = object()


def _field_value(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current

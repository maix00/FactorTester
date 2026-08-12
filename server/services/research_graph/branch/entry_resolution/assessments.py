"""Deterministic validation for orthogonal entry-requirement assessments."""

from __future__ import annotations

from typing import Any

from ..entry_requirements import (
    bare_requirement_ref,
    checkpoint_obligations,
    requirement_map,
)


_APPLICABILITY = {"applicable", "not_applicable", "undetermined"}
_COVERAGE = {"create_new", "map_existing", "no_material_issue"}
_RESOLUTION_ROUTES = {
    "existing_evidence",
    "cli_evidence",
    "trial",
    "capability_gap",
    "bounded_unknown",
}
_REUSE_STATUS = {"none", "exact", "partial", "stale", "incompatible"}
_ENTRY_EFFECT = {"pass", "pass_limited", "blocked", "deferred"}
_GATE_POLICIES = {
    "discover_before_exit",
    "plan_before_exit",
    "resolve_before_exit",
}
_GAP_TARGETS = {
    "capability_gap",
    "skill_candidate_review",
    "code_improvement_required",
}


def validate_entry_requirement_assessments(
    *,
    graph: dict[str, Any],
    node: dict[str, Any],
    checkpoint: dict[str, Any] | None,
    target_node: str,
    submitted: Any,
    required_requirement_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Require one four-dimensional decision per current requirement."""
    declared_ids = [
        str(item) for item in node.get("entry_requirement_refs") or []
    ]
    if required_requirement_ids is None:
        required_ids = declared_ids
    else:
        requested_ids = set(required_requirement_ids)
        unknown = sorted(requested_ids - set(declared_ids))
        if unknown:
            raise ValueError(
                "entry resolution references undeclared requirements: "
                + ", ".join(unknown)
            )
        required_ids = [
            requirement_id for requirement_id in declared_ids
            if requirement_id in requested_ids
        ]
    if int(graph.get("schema_version") or 1) < 2:
        if submitted not in (None, []):
            raise ValueError(
                "entry requirement assessments require Graph schema_version 2"
            )
        return []
    if not required_ids and submitted in (None, []):
        return []
    items = _exact_items(submitted, required_ids)
    catalog = requirement_map(graph)
    obligations = checkpoint_obligations(checkpoint)
    normalized = [
        _validate_item(
            item=item,
            requirement=catalog.get(str(item["requirement_id"])),
            obligations=obligations,
            target_node=target_node,
        )
        for item in items
    ]
    return sorted(normalized, key=lambda item: item["requirement_id"])


def _exact_items(submitted: Any, required_ids: list[str]) -> list[dict[str, Any]]:
    if not isinstance(submitted, list) or not all(
        isinstance(item, dict) for item in submitted
    ):
        raise ValueError("entry_requirement_assessments must be an array")
    ids = [str(item.get("requirement_id") or "") for item in submitted]
    if len(ids) != len(set(ids)):
        raise ValueError("entry requirement assessment IDs must be unique")
    if set(ids) != set(required_ids):
        missing = sorted(set(required_ids) - set(ids))
        extra = sorted(set(ids) - set(required_ids))
        raise ValueError(
            "entry requirement assessments must exactly cover current node: "
            f"missing={','.join(missing)}; extra={','.join(extra)}"
        )
    return submitted


def _validate_item(
    *,
    item: dict[str, Any],
    requirement: dict[str, Any] | None,
    obligations: list[dict[str, Any]],
    target_node: str,
) -> dict[str, Any]:
    requirement_id = str(item["requirement_id"])
    if requirement is None:
        raise ValueError(f"unknown entry requirement: {requirement_id}")
    gate_policy = str(requirement.get("gate_policy") or "")
    if gate_policy not in _GATE_POLICIES:
        raise ValueError(f"invalid requirement gate policy: {requirement_id}")
    applicability = _applicability(item, requirement_id)
    coverage = _coverage(item, requirement_id, obligations)
    resolution = _resolution(item, requirement_id)
    effect = _entry_effect(item, requirement_id)
    _validate_relationships(
        requirement_id=requirement_id,
        gate_policy=gate_policy,
        applicability=applicability,
        coverage=coverage,
        resolution=resolution,
        effect=effect,
        target_node=target_node,
    )
    return {
        "requirement_id": requirement_id,
        "requirement_revision": int(requirement.get("revision") or 0),
        "gate_policy": gate_policy,
        "applicability": applicability,
        "coverage": coverage,
        "resolution": resolution,
        "entry_effect": effect,
    }


def _applicability(item: dict[str, Any], requirement_id: str) -> dict[str, Any]:
    value = _object(item, "applicability", requirement_id)
    status = str(value.get("status") or "")
    if status not in _APPLICABILITY:
        raise ValueError(f"invalid applicability: {requirement_id}")
    reason = str(value.get("reason_zh") or "").strip()
    if not reason:
        raise ValueError(f"applicability reason_zh is required: {requirement_id}")
    return {
        "status": status,
        "reason_zh": reason,
        "fact_refs": _text_refs(
            value.get("fact_refs"),
            field=f"{requirement_id}.applicability.fact_refs",
        ),
    }


def _coverage(
    item: dict[str, Any],
    requirement_id: str,
    obligations: list[dict[str, Any]],
) -> dict[str, Any]:
    value = _object(item, "coverage", requirement_id)
    decision = str(value.get("decision") or "")
    if decision not in _COVERAGE:
        raise ValueError(f"invalid obligation coverage: {requirement_id}")
    refs = _text_refs(
        value.get("obligation_refs"),
        field=f"{requirement_id}.coverage.obligation_refs",
    )
    if decision in {"create_new", "map_existing"}:
        _validate_obligation_mapping(requirement_id, refs, obligations)
    elif refs:
        raise ValueError(
            f"no_material_issue cannot bind obligations: {requirement_id}"
        )
    return {"decision": decision, "obligation_refs": refs}


def _resolution(item: dict[str, Any], requirement_id: str) -> dict[str, Any]:
    value = _object(item, "resolution", requirement_id)
    route = str(value.get("route") or "")
    reuse_status = str(value.get("reuse_status") or "")
    if route not in _RESOLUTION_ROUTES:
        raise ValueError(f"invalid resolution route: {requirement_id}")
    if reuse_status not in _REUSE_STATUS:
        raise ValueError(f"invalid reuse status: {requirement_id}")
    refs = _text_refs(
        value.get("validation_refs"),
        field=f"{requirement_id}.resolution.validation_refs",
    )
    if (route == "existing_evidence" or reuse_status == "exact") and not refs:
        raise ValueError(f"evidence reuse needs validation refs: {requirement_id}")
    return {"route": route, "reuse_status": reuse_status, "validation_refs": refs}


def _entry_effect(item: dict[str, Any], requirement_id: str) -> dict[str, Any]:
    value = _object(item, "entry_effect", requirement_id)
    status = str(value.get("status") or "")
    if status not in _ENTRY_EFFECT:
        raise ValueError(f"invalid entry effect: {requirement_id}")
    return {
        "status": status,
        "limitation_refs": _text_refs(
            value.get("limitation_refs"),
            field=f"{requirement_id}.entry_effect.limitation_refs",
        ),
    }


def _validate_relationships(
    *, requirement_id: str, gate_policy: str,
    applicability: dict[str, Any], coverage: dict[str, Any],
    resolution: dict[str, Any], effect: dict[str, Any], target_node: str,
) -> None:
    if (
        applicability["status"] == "not_applicable"
        or coverage["decision"] == "no_material_issue"
    ) and not applicability["fact_refs"]:
        raise ValueError(f"non-material decision needs fact refs: {requirement_id}")
    if applicability["status"] == "undetermined" and effect["status"] in {
        "pass", "pass_limited",
    }:
        raise ValueError(f"undetermined requirement cannot pass: {requirement_id}")
    if resolution["route"] == "capability_gap":
        if target_node not in _GAP_TARGETS:
            raise ValueError(
                "capability-gap assessment must route to a coordination node"
            )
        if effect["status"] not in {"blocked", "deferred"}:
            raise ValueError(f"capability gap cannot pass entry: {requirement_id}")
    if gate_policy == "resolve_before_exit" and (
        effect["status"] == "deferred"
        and resolution["route"] != "capability_gap"
    ):
        raise ValueError(f"resolve-before-exit cannot be deferred: {requirement_id}")


def _validate_obligation_mapping(
    requirement_id: str,
    refs: list[str],
    obligations: list[dict[str, Any]],
) -> None:
    if not refs:
        raise ValueError(f"entry requirement needs an obligation ref: {requirement_id}")
    by_id = {str(item.get("obligation_id") or ""): item for item in obligations}
    for reference in refs:
        obligation = by_id.get(reference.removeprefix("obligation:"))
        if obligation is None or requirement_id not in {
            bare_requirement_ref(ref)
            for ref in obligation.get("requirement_refs") or []
        }:
            raise ValueError(
                f"obligation does not map to {requirement_id}: {reference}"
            )


def _text_refs(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be a text array")
    return list(dict.fromkeys(value))


def _object(
    value: dict[str, Any], field: str, requirement_id: str,
) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{requirement_id}.{field} must be an object")
    return item

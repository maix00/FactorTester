"""Validate one orthogonal Entry Requirement assessment."""

from __future__ import annotations

from typing import Any

from .fields import chinese_text, object_field, text_array


_APPLICABILITY = {"applicable", "not_applicable", "undetermined"}
_DECISIONS = {"create_new", "map_existing", "no_material_issue"}
_ROUTES = {
    "existing_evidence", "cli_evidence", "trial", "capability_gap",
    "bounded_unknown",
}
_REUSE = {"none", "exact", "partial", "stale", "incompatible"}
_EFFECTS = {"pass", "pass_limited", "blocked", "deferred"}
_ACTIONS = {
    "cli_evidence", "trial_candidate", "capability_gap",
    "bounded_unknown", "none",
}


def validate_assessment(
    item: dict[str, Any],
    *,
    factor_facts: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    requirement_id = str(item.get("requirement_id") or "")
    prefix = requirement_id or "assessment"
    if not requirement_id:
        raise ValueError("assessment.requirement_id is required")
    applicability = object_field(item, "applicability", prefix)
    app_status = str(applicability.get("status") or "")
    if app_status not in _APPLICABILITY:
        raise ValueError(f"{prefix}.applicability.status is invalid")
    reason = chinese_text(
        applicability.get("reason_zh"),
        f"{prefix}.applicability.reason_zh",
    )
    fact_refs = text_array(
        applicability.get("fact_refs"),
        f"{prefix}.applicability.fact_refs",
    )
    decision, obligation_refs = _coverage(item, prefix=prefix)
    if (
        app_status == "not_applicable"
        or decision == "no_material_issue"
    ) and not fact_refs:
        raise ValueError(f"{prefix} non-material decision needs fact_refs")
    route, reuse_status, validation_refs = _resolution(
        item,
        prefix=prefix,
    )
    effect_status, limitation_refs = _entry_effect(item, prefix=prefix)
    action = _first_action(item, prefix=prefix, decision=decision)
    normalized = {
        "requirement_id": requirement_id,
        "applicability": {
            "status": app_status,
            "reason_zh": reason,
            "fact_refs": fact_refs,
        },
        "coverage": {
            "decision": decision,
            "obligation_refs": obligation_refs,
        },
        "resolution": {
            "route": route,
            "reuse_status": reuse_status,
            "validation_refs": validation_refs,
        },
        "entry_effect": {
            "status": effect_status,
            "limitation_refs": limitation_refs,
        },
    }
    report_input = {
        "item": item,
        "prefix": prefix,
        "obligation_refs": obligation_refs,
        "fallback_fact_refs": (
            fact_refs or _factor_fact_refs(factor_facts)
        ),
        "action": action,
    }
    return normalized, report_input


def _coverage(
    item: dict[str, Any],
    *,
    prefix: str,
) -> tuple[str, list[str]]:
    coverage = object_field(item, "coverage", prefix)
    decision = str(coverage.get("decision") or "")
    if decision not in _DECISIONS:
        raise ValueError(f"{prefix}.coverage.decision is invalid")
    obligation_refs = text_array(
        coverage.get("obligation_refs"),
        f"{prefix}.coverage.obligation_refs",
    )
    if decision in {"create_new", "map_existing"} and not obligation_refs:
        raise ValueError(f"{prefix}.coverage needs obligation_refs")
    if decision == "no_material_issue" and obligation_refs:
        raise ValueError(
            f"{prefix}.no_material_issue cannot bind obligations"
        )
    return decision, obligation_refs


def _resolution(
    item: dict[str, Any],
    *,
    prefix: str,
) -> tuple[str, str, list[str]]:
    resolution = object_field(item, "resolution", prefix)
    route = str(resolution.get("route") or "")
    reuse_status = str(resolution.get("reuse_status") or "")
    if route not in _ROUTES:
        raise ValueError(f"{prefix}.resolution.route is invalid")
    if reuse_status not in _REUSE:
        raise ValueError(f"{prefix}.resolution.reuse_status is invalid")
    validation_refs = text_array(
        resolution.get("validation_refs"),
        f"{prefix}.resolution.validation_refs",
    )
    if (route == "existing_evidence" or reuse_status == "exact") and (
        not validation_refs
    ):
        raise ValueError(f"{prefix}.resolution needs validation_refs")
    return route, reuse_status, validation_refs


def _entry_effect(
    item: dict[str, Any],
    *,
    prefix: str,
) -> tuple[str, list[str]]:
    effect = object_field(item, "entry_effect", prefix)
    status = str(effect.get("status") or "")
    if status not in _EFFECTS:
        raise ValueError(f"{prefix}.entry_effect.status is invalid")
    limitations = text_array(
        effect.get("limitation_refs"),
        f"{prefix}.entry_effect.limitation_refs",
    )
    return status, limitations


def _first_action(
    item: dict[str, Any],
    *,
    prefix: str,
    decision: str,
) -> dict[str, str]:
    value = object_field(item, "first_resolution_action", prefix)
    kind = str(value.get("kind") or "")
    if kind not in _ACTIONS:
        raise ValueError(f"{prefix}.first_resolution_action.kind is invalid")
    action_ref = str(value.get("action_ref") or "").strip()
    trial_ref = str(value.get("trial_ref") or "").strip()
    description = chinese_text(
        value.get("description_zh"),
        f"{prefix}.first_resolution_action.description_zh",
    )
    if kind == "trial_candidate":
        if not trial_ref.startswith("trial:"):
            raise ValueError(
                f"{prefix}.first_resolution_action.trial_ref is required"
            )
    elif kind == "none":
        if decision != "no_material_issue" or action_ref or trial_ref:
            raise ValueError(
                f"{prefix}.first_resolution_action.none is invalid"
            )
    elif not action_ref:
        raise ValueError(
            f"{prefix}.first_resolution_action.action_ref is required"
        )
    return {
        "kind": kind,
        "action_ref": action_ref,
        "trial_ref": trial_ref,
        "description_zh": description,
    }


def _factor_fact_refs(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return text_array(value.get("fact_refs"), "factor_facts.fact_refs")

"""Canonical nested components for a TrialPlan contract."""

from __future__ import annotations

from typing import Any

from .fields import (
    array_field,
    identifier_field,
    identifier_list,
    json_value,
    object_field,
    sha256_field,
    sha256_list,
)


_SAMPLE_ROLES = frozenset({
    "diagnostic",
    "selection",
    "validation",
    "confirmation",
    "holdout",
})


def canonical_outcomes(
    value: Any,
) -> tuple[dict[str, list[str]], set[str]]:
    outcomes = object_field(
        value,
        "trial_plan.outcomes",
        fields=frozenset({"primary", "secondary"}),
    )
    primary = identifier_list(
        outcomes.get("primary"),
        "trial_plan.outcomes.primary",
        allow_empty=False,
    )
    secondary = identifier_list(
        outcomes.get("secondary"),
        "trial_plan.outcomes.secondary",
    )
    if set(primary).intersection(secondary):
        raise ValueError("primary and secondary outcomes must be distinct")
    return {
        "primary": primary,
        "secondary": secondary,
    }, set(primary + secondary)


def canonical_sample_roles(
    value: Any,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    items = array_field(value, "trial_plan.sample_roles", allow_empty=False)
    normalized: list[dict[str, Any]] = []
    sample_refs: set[str] = set()
    sample_hashes: set[str] = set()
    planned_samples: dict[str, str] = {}
    for index, raw in enumerate(items):
        path = f"trial_plan.sample_roles[{index}]"
        item = object_field(
            raw,
            path,
            fields=frozenset({
                "sample_ref",
                "sample_hash",
                "role",
                "run_spec_hashes",
            }),
        )
        sample_ref = identifier_field(
            item.get("sample_ref"),
            f"{path}.sample_ref",
        )
        sample_hash = sha256_field(
            item.get("sample_hash"),
            f"{path}.sample_hash",
        )
        role = identifier_field(item.get("role"), f"{path}.role")
        if role not in _SAMPLE_ROLES:
            raise ValueError(f"{path}.role is unsupported: {role}")
        if sample_ref in sample_refs:
            raise ValueError("sample_ref values must be unique")
        if sample_hash in sample_hashes:
            raise ValueError(
                "one sample identity cannot cross TrialPlan sample roles"
            )
        sample_refs.add(sample_ref)
        sample_hashes.add(sample_hash)
        hashes = sha256_list(
            item.get("run_spec_hashes"),
            f"{path}.run_spec_hashes",
        )
        for run_hash in hashes:
            if run_hash in planned_samples:
                raise ValueError(
                    "one RunSpec cannot cross TrialPlan sample roles"
                )
            planned_samples[run_hash] = role
        normalized.append({
            "sample_ref": sample_ref,
            "sample_hash": sample_hash,
            "role": role,
            "run_spec_hashes": hashes,
        })
    return normalized, planned_samples


def canonical_comparisons(
    value: Any,
    *,
    planned_samples: dict[str, str],
    enforce_sample_role: bool,
) -> list[dict[str, Any]]:
    items = array_field(value, "trial_plan.comparisons", allow_empty=False)
    normalized: list[dict[str, Any]] = []
    comparison_ids: set[str] = set()
    for index, raw in enumerate(items):
        path = f"trial_plan.comparisons[{index}]"
        item = object_field(
            raw,
            path,
            fields=frozenset({"comparison_id", "members"}),
        )
        comparison_id = identifier_field(
            item.get("comparison_id"),
            f"{path}.comparison_id",
        )
        if comparison_id in comparison_ids:
            raise ValueError("comparison_id values must be unique")
        comparison_ids.add(comparison_id)
        normalized.append({
            "comparison_id": comparison_id,
            "members": _comparison_members(
                item.get("members"),
                path=f"{path}.members",
                planned_samples=planned_samples,
                enforce_sample_role=enforce_sample_role,
            ),
        })
    return normalized


def _comparison_members(
    value: Any,
    *,
    path: str,
    planned_samples: dict[str, str],
    enforce_sample_role: bool,
) -> list[dict[str, str]]:
    items = array_field(value, path, allow_empty=False)
    normalized: list[dict[str, str]] = []
    identities: set[tuple[str, str]] = set()
    for index, raw in enumerate(items):
        item_path = f"{path}[{index}]"
        item = object_field(
            raw,
            item_path,
            fields=frozenset({"run_spec_hash", "trial_role"}),
        )
        run_hash = sha256_field(
            item.get("run_spec_hash"),
            f"{item_path}.run_spec_hash",
        )
        if run_hash not in planned_samples:
            raise ValueError(
                f"{item_path}.run_spec_hash has no declared sample role"
            )
        trial_role = identifier_field(
            item.get("trial_role"),
            f"{item_path}.trial_role",
        )
        if enforce_sample_role and trial_role != planned_samples[run_hash]:
            raise ValueError(
                f"{item_path}.trial_role does not match declared sample role"
            )
        identity = (run_hash, trial_role)
        if identity in identities:
            raise ValueError("comparison members must be unique")
        identities.add(identity)
        normalized.append({
            "run_spec_hash": run_hash,
            "trial_role": trial_role,
        })
    return normalized


def canonical_stopping(
    value: Any,
    *,
    outcome_ids: set[str],
) -> dict[str, Any]:
    item = object_field(
        value,
        "trial_plan.stopping",
        fields=frozenset({
            "rule_ref",
            "monitored_outcomes",
            "parameters",
        }),
    )
    monitored = identifier_list(
        item.get("monitored_outcomes"),
        "trial_plan.stopping.monitored_outcomes",
        allow_empty=False,
    )
    unknown = sorted(set(monitored) - outcome_ids)
    if unknown:
        raise ValueError(
            "stopping references undeclared outcomes: " + ", ".join(unknown)
        )
    parameters = json_value(
        item.get("parameters"),
        "trial_plan.stopping.parameters",
    )
    if not isinstance(parameters, dict):
        raise ValueError("trial_plan.stopping.parameters must be an object")
    return {
        "rule_ref": identifier_field(
            item.get("rule_ref"),
            "trial_plan.stopping.rule_ref",
        ),
        "monitored_outcomes": monitored,
        "parameters": parameters,
    }


def canonical_multiplicity(value: Any) -> dict[str, Any]:
    item = object_field(
        value,
        "trial_plan.multiplicity",
        fields=frozenset({
            "method_ref",
            "family_ref",
            "dependence_assumptions",
        }),
    )
    return {
        "method_ref": identifier_field(
            item.get("method_ref"),
            "trial_plan.multiplicity.method_ref",
        ),
        "family_ref": identifier_field(
            item.get("family_ref"),
            "trial_plan.multiplicity.family_ref",
        ),
        "dependence_assumptions": identifier_list(
            item.get("dependence_assumptions"),
            "trial_plan.multiplicity.dependence_assumptions",
        ),
    }


def canonical_criteria(value: Any) -> dict[str, str]:
    item = object_field(
        value,
        "trial_plan.criteria",
        fields=frozenset({
            "rejection_ref",
            "revision_ref",
            "continuation_ref",
        }),
    )
    return {
        key: identifier_field(
            item.get(key),
            f"trial_plan.criteria.{key}",
        )
        for key in (
            "rejection_ref",
            "revision_ref",
            "continuation_ref",
        )
    }

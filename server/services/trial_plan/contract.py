"""Compact, source-free TrialPlan schema for direct research experiments."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson

from .components import (
    canonical_comparisons,
    canonical_criteria,
    canonical_multiplicity,
    canonical_outcomes,
    canonical_sample_roles,
    canonical_stopping,
)
from .fields import integer_field, object_field, positive_integer


TRIAL_PLAN_SCHEMA_VERSION = 2
SUPPORTED_TRIAL_PLAN_SCHEMA_VERSIONS = frozenset({1, 2})
MAX_TRIAL_PLAN_BYTES = 4096
_ROOT_FIELDS = frozenset({
    "schema_version",
    "trial_plan_id",
    "version",
    "hypothesis_ref",
    "trial_family",
    "protocol_ref",
    "outcomes",
    "sample_roles",
    "comparisons",
    "stopping",
    "multiplicity",
    "criteria",
})


def canonical_trial_plan(value: Any) -> dict[str, Any]:
    """Return one canonical, bounded direct TrialPlan or fail closed."""
    if not isinstance(value, dict):
        raise ValueError("trial_plan must be an object")
    schema_version = integer_field(
        value.get("schema_version"), "trial_plan.schema_version",
    )
    if schema_version not in SUPPORTED_TRIAL_PLAN_SCHEMA_VERSIONS:
        raise ValueError(
            f"unsupported TrialPlan schema_version: {schema_version}"
        )
    plan = object_field(value, "trial_plan", fields=_ROOT_FIELDS)
    normalized = {
        "schema_version": schema_version,
        "trial_plan_id": _identifier(plan.get("trial_plan_id"), "trial_plan.trial_plan_id"),
        "version": positive_integer(plan.get("version"), "trial_plan.version"),
        "hypothesis_ref": _identifier(plan.get("hypothesis_ref"), "trial_plan.hypothesis_ref"),
        "trial_family": _identifier(plan.get("trial_family"), "trial_plan.trial_family"),
        "protocol_ref": _identifier(plan.get("protocol_ref"), "trial_plan.protocol_ref"),
    }
    outcomes, outcome_ids = canonical_outcomes(plan.get("outcomes"))
    sample_roles, planned_samples = canonical_sample_roles(
        plan.get("sample_roles"),
    )
    normalized.update({
        "outcomes": outcomes,
        "sample_roles": sample_roles,
        "comparisons": canonical_comparisons(
            plan.get("comparisons"),
            planned_samples=planned_samples,
            enforce_sample_role=schema_version < 2,
        ),
        "stopping": canonical_stopping(
            plan.get("stopping"), outcome_ids=outcome_ids,
        ),
        "multiplicity": canonical_multiplicity(plan.get("multiplicity")),
        "criteria": canonical_criteria(plan.get("criteria")),
    })
    encoded = _encode(normalized)
    if len(encoded) > MAX_TRIAL_PLAN_BYTES:
        raise ValueError(f"TrialPlan exceeds {MAX_TRIAL_PLAN_BYTES} bytes")
    return normalized


def trial_plan_hash(value: Any) -> str:
    return hashlib.sha256(_encode(canonical_trial_plan(value))).hexdigest()


def _identifier(value: Any, field: str) -> str:
    from .fields import identifier_field

    return identifier_field(value, field)


def _encode(value: dict[str, Any]) -> bytes:
    return orjson.dumps(deepcopy(value), option=orjson.OPT_SORT_KEYS)

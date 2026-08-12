"""Compact, source-free TrialPlan schema and deterministic validation."""

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
from .fields import (
    identifier_field,
    identifier_list,
    integer_field,
    object_field,
    positive_integer,
    sha256_field,
)
from .stage_policy import (
    canonical_stage_policy,
    validate_stage_samples,
)
from .v5_design import (
    canonical_v5_comparisons,
    canonical_v5_samples,
    canonical_v5_stage_policy,
)
from .v5_contract import canonical_v5_metadata


TRIAL_PLAN_SCHEMA_VERSION = 5
SUPPORTED_TRIAL_PLAN_SCHEMA_VERSIONS = frozenset({1, 2, 3, 4, 5})
MAX_TRIAL_PLAN_BYTES = 4096
MAX_TRIAL_PLAN_V5_BYTES = 8192
MAX_OBLIGATION_REFS = 32
_ROOT_FIELDS = {
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
}
_ROOT_FIELDS_BY_VERSION = {
    1: frozenset(_ROOT_FIELDS),
    2: frozenset(_ROOT_FIELDS),
    3: frozenset({
        *_ROOT_FIELDS,
        "decision_contract_hash",
        "methodology_hash",
        "obligation_refs",
    }),
    4: frozenset({
        *_ROOT_FIELDS,
        "decision_contract_hash",
        "methodology_hash",
        "obligation_refs",
        "parent_trial_plan_hash",
        "stage_policy",
    }),
    5: frozenset({
        "schema_version",
        "trial_plan_id",
        "version",
        "hypothesis_ref",
        "trial_family",
        "protocol_ref",
        "outcomes",
        "samples",
        "comparisons",
        "stopping",
        "multiplicity",
        "criteria",
        "decision_contract_hash",
        "methodology_hash",
        "parent_trial_plan_hash",
        "stage_policy",
        "primary_obligation_ref",
        "secondary_obligation_refs",
        "design_evidence_refs",
        "trial_ledger_ref",
        "holdout_access_ledger_ref",
        "reopen_predicate_refs",
        "evidence_actions",
    }),
}


def canonical_trial_plan(value: Any) -> dict[str, Any]:
    """Return one canonical, bounded TrialPlan or fail closed."""
    if not isinstance(value, dict):
        raise ValueError("trial_plan must be an object")
    schema_version = integer_field(
        value.get("schema_version"),
        "trial_plan.schema_version",
    )
    if schema_version not in SUPPORTED_TRIAL_PLAN_SCHEMA_VERSIONS:
        raise ValueError(
            f"unsupported TrialPlan schema_version: {schema_version}"
        )
    plan = object_field(
        value,
        "trial_plan",
        fields=_ROOT_FIELDS_BY_VERSION[schema_version],
    )
    normalized = {
        "schema_version": schema_version,
        "trial_plan_id": identifier_field(
            plan.get("trial_plan_id"),
            "trial_plan.trial_plan_id",
        ),
        "version": positive_integer(
            plan.get("version"),
            "trial_plan.version",
        ),
        "hypothesis_ref": identifier_field(
            plan.get("hypothesis_ref"),
            "trial_plan.hypothesis_ref",
        ),
        "trial_family": identifier_field(
            plan.get("trial_family"),
            "trial_plan.trial_family",
        ),
        "protocol_ref": identifier_field(
            plan.get("protocol_ref"),
            "trial_plan.protocol_ref",
        ),
    }
    outcomes, outcome_ids = canonical_outcomes(plan.get("outcomes"))
    if schema_version == 5:
        stage_policy = canonical_v5_stage_policy(plan.get("stage_policy"))
        sample_roles, planned_samples = canonical_v5_samples(
            plan.get("samples"),
            stage_ids=set(stage_policy["ordered_stage_ids"]),
        )
        comparisons = canonical_v5_comparisons(
            plan.get("comparisons"),
            run_bindings=planned_samples,
        )
    else:
        sample_roles, planned_samples = canonical_sample_roles(
            plan.get("sample_roles")
        )
        comparisons = canonical_comparisons(
            plan.get("comparisons"),
            planned_samples=planned_samples,
            enforce_sample_role=schema_version < 4,
        )
    normalized.update({
        "outcomes": outcomes,
        ("samples" if schema_version == 5 else "sample_roles"): sample_roles,
        "comparisons": comparisons,
        "stopping": canonical_stopping(
            plan.get("stopping"),
            outcome_ids=outcome_ids,
        ),
        "multiplicity": canonical_multiplicity(plan.get("multiplicity")),
        "criteria": canonical_criteria(plan.get("criteria")),
    })
    if 3 <= schema_version <= 4:
        normalized["decision_contract_hash"] = sha256_field(
            plan.get("decision_contract_hash"),
            "trial_plan.decision_contract_hash",
        )
        normalized["methodology_hash"] = sha256_field(
            plan.get("methodology_hash"),
            "trial_plan.methodology_hash",
        )
        obligation_refs = identifier_list(
            plan.get("obligation_refs"),
            "trial_plan.obligation_refs",
            allow_empty=False,
        )
        if len(obligation_refs) > MAX_OBLIGATION_REFS:
            raise ValueError(
                "trial_plan.obligation_refs must contain at most "
                f"{MAX_OBLIGATION_REFS} items"
            )
        normalized["obligation_refs"] = obligation_refs
    if schema_version == 4:
        parent_hash = plan.get("parent_trial_plan_hash")
        normalized["parent_trial_plan_hash"] = (
            None
            if parent_hash is None
            else sha256_field(
                parent_hash,
                "trial_plan.parent_trial_plan_hash",
            )
        )
        stage_policy = canonical_stage_policy(plan.get("stage_policy"))
        validate_stage_samples(
            policy=stage_policy,
            sample_roles=sample_roles,
        )
        normalized["stage_policy"] = stage_policy
    if schema_version == 5:
        normalized.update(canonical_v5_metadata(
            plan,
            stage_policy=stage_policy,
            samples=sample_roles,
            comparisons=comparisons,
        ))
    encoded = _encode(normalized)
    maximum = (
        MAX_TRIAL_PLAN_V5_BYTES
        if schema_version == 5
        else MAX_TRIAL_PLAN_BYTES
    )
    if len(encoded) > maximum:
        raise ValueError(
            f"TrialPlan exceeds {maximum} bytes"
        )
    return normalized


def trial_plan_hash(value: Any) -> str:
    return hashlib.sha256(_encode(canonical_trial_plan(value))).hexdigest()


def _encode(value: dict[str, Any]) -> bytes:
    return orjson.dumps(
        deepcopy(value),
        option=orjson.OPT_SORT_KEYS,
    )

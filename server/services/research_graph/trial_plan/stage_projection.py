"""Compact deterministic TrialPlan stage projection."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson

from .fields import (
    identifier_field,
    integer_field,
    object_field,
    positive_integer,
    sha256_field,
)
from .stage_policy import (
    TERMINAL_STAGES,
    canonical_stage_order,
)


_PROJECTION_FIELDS_V1 = frozenset({
    "schema_version",
    "trial_plan_id",
    "plan_version",
    "ordered_stages",
    "entry_stage",
    "current_stage",
    "completed_mask",
    "partition_commitment_hash",
    "frozen_design_hash",
})
_PROJECTION_FIELDS_V2 = frozenset({
    *_PROJECTION_FIELDS_V1,
    "execution_node",
})


def project_trial_plan_stage(
    *,
    trial_plan: dict[str, Any],
    trial_plan_hash: str,
    current_trial_plan_hash: str,
    current_projection: dict[str, Any],
    execution_node: str,
) -> dict[str, Any]:
    """Bind one v4 Plan to a compact O(1) branch stage projection."""
    if trial_plan.get("schema_version") != 4:
        if current_projection:
            raise ValueError("cannot replace a staged TrialPlan with legacy")
        return {}
    sha256_field(trial_plan_hash, "trial_plan_hash")
    current_hash = (
        sha256_field(current_trial_plan_hash, "current_trial_plan_hash")
        if current_trial_plan_hash
        else ""
    )
    partition_hash = _partition_commitment_hash(trial_plan)
    design_hash = _frozen_design_hash(trial_plan)
    parent_hash = trial_plan["parent_trial_plan_hash"]
    normalized_execution_node = identifier_field(
        execution_node,
        "trial_stage_projection.execution_node",
    )
    if not current_projection:
        if current_hash:
            raise ValueError(
                "initial staged TrialPlan requires an empty branch plan"
            )
        if trial_plan["version"] != 1 or parent_hash is not None:
            raise ValueError(
                "initial staged TrialPlan requires version 1 and null parent"
            )
        policy = trial_plan["stage_policy"]
        return {
            "schema_version": 2,
            "trial_plan_id": trial_plan["trial_plan_id"],
            "plan_version": 1,
            "ordered_stages": deepcopy(policy["ordered_stages"]),
            "entry_stage": policy["entry_stage"],
            "current_stage": policy["entry_stage"],
            "completed_mask": 0,
            "partition_commitment_hash": partition_hash,
            "frozen_design_hash": design_hash,
            "execution_node": normalized_execution_node,
        }
    current = validate_trial_stage_projection(current_projection)
    if parent_hash != current_hash:
        raise ValueError("TrialPlan parent hash does not match current plan")
    if trial_plan["trial_plan_id"] != current["trial_plan_id"]:
        raise ValueError("TrialPlan lineage changed trial_plan_id")
    if trial_plan["version"] != current["plan_version"] + 1:
        raise ValueError("TrialPlan lineage version must increment by one")
    policy = trial_plan["stage_policy"]
    if (
        policy["ordered_stages"] != current["ordered_stages"]
        or policy["entry_stage"] != current["entry_stage"]
    ):
        raise ValueError("TrialPlan lineage changed stage policy")
    if partition_hash != current["partition_commitment_hash"]:
        raise ValueError("TrialPlan lineage changed partition commitment")
    if design_hash != current["frozen_design_hash"]:
        raise ValueError("TrialPlan lineage changed frozen trial design")
    value = deepcopy(current)
    value["schema_version"] = 2
    value["plan_version"] = trial_plan["version"]
    value["execution_node"] = normalized_execution_node
    return value


def advance_trial_stage(projection: dict[str, Any]) -> dict[str, Any]:
    value = validate_trial_stage_projection(projection)
    index = value["ordered_stages"].index(value["current_stage"])
    if index + 1 >= len(value["ordered_stages"]):
        raise ValueError("TrialPlan has no next TrialPlan stage")
    result = deepcopy(value)
    result["completed_mask"] |= 1 << index
    result["current_stage"] = result["ordered_stages"][index + 1]
    return result


def trial_stage_guard_facts(
    *,
    projection: dict[str, Any],
    adjudication_action: str | None,
) -> dict[str, bool]:
    if not projection:
        if adjudication_action == "advance_trial_stage":
            raise ValueError("stage advancement requires a v4 TrialPlan")
        return {
            "current_trial_stage_executable": False,
            "current_trial_stage_allows_in_lineage_revision": False,
            "new_hypothesis_lineage_allowed": False,
            "next_trial_stage_required": False,
            "trial_stage_advance_authorized": False,
        }
    value = validate_trial_stage_projection(projection)
    current_stage = value["current_stage"]
    index = value["ordered_stages"].index(current_stage)
    has_next = index + 1 < len(value["ordered_stages"])
    advancing = adjudication_action == "advance_trial_stage"
    if advancing and not has_next:
        raise ValueError("TrialPlan has no next TrialPlan stage")
    return {
        "current_trial_stage_executable": True,
        "current_trial_stage_allows_in_lineage_revision": (
            current_stage not in TERMINAL_STAGES
        ),
        "new_hypothesis_lineage_allowed": True,
        "next_trial_stage_required": advancing,
        "trial_stage_advance_authorized": advancing and has_next,
    }


def agent_trial_stage_summary(
    projection: dict[str, Any],
) -> dict[str, Any] | None:
    if not projection:
        return None
    if projection.get("schema_version") == 3:
        from .execution_checkpoint import agent_action_summary
        from .execution_checkpoint_contract import validate_execution_checkpoint

        checkpoint = validate_execution_checkpoint(projection)
        index = checkpoint["ordered_stage_ids"].index(
            checkpoint["current_stage_id"]
        )
        return {
            "plan_version": checkpoint["plan_version"],
            "current_stage": checkpoint["current_stage_id"],
            "next_stage": (
                checkpoint["ordered_stage_ids"][index + 1]
                if index + 1 < len(checkpoint["ordered_stage_ids"])
                else None
            ),
            "current_action": agent_action_summary(checkpoint),
            "checkpoint_hash": checkpoint["projection_hash"],
        }
    value = validate_trial_stage_projection(projection)
    index = value["ordered_stages"].index(value["current_stage"])
    return {
        "plan_version": value["plan_version"],
        "current_stage": value["current_stage"],
        "next_stage": (
            value["ordered_stages"][index + 1]
            if index + 1 < len(value["ordered_stages"])
            else None
        ),
        "partition_commitment_hash": value[
            "partition_commitment_hash"
        ],
    }


def validate_trial_stage_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("trial_stage_projection must be an object")
    schema_version = integer_field(
        value.get("schema_version"),
        "trial_stage_projection.schema_version",
    )
    if schema_version not in {1, 2}:
        raise ValueError(
            "trial stage projection schema_version must be 1 or 2"
        )
    projection = object_field(
        value,
        "trial_stage_projection",
        fields=(
            _PROJECTION_FIELDS_V2
            if schema_version == 2
            else _PROJECTION_FIELDS_V1
        ),
    )
    stages = canonical_stage_order(
        projection.get("ordered_stages"),
        field="trial_stage_projection.ordered_stages",
    )
    current_stage = identifier_field(
        projection.get("current_stage"),
        "trial_stage_projection.current_stage",
    )
    entry_stage = identifier_field(
        projection.get("entry_stage"),
        "trial_stage_projection.entry_stage",
    )
    if current_stage not in stages or entry_stage != stages[0]:
        raise ValueError("trial stage projection stage identity is invalid")
    completed_mask = integer_field(
        projection.get("completed_mask"),
        "trial_stage_projection.completed_mask",
    )
    if completed_mask < 0 or completed_mask >= (1 << len(stages)):
        raise ValueError("trial stage projection completed_mask is invalid")
    return {
        "schema_version": schema_version,
        "trial_plan_id": identifier_field(
            projection.get("trial_plan_id"),
            "trial_stage_projection.trial_plan_id",
        ),
        "plan_version": positive_integer(
            projection.get("plan_version"),
            "trial_stage_projection.plan_version",
        ),
        "ordered_stages": stages,
        "entry_stage": entry_stage,
        "current_stage": current_stage,
        "completed_mask": completed_mask,
        "partition_commitment_hash": sha256_field(
            projection.get("partition_commitment_hash"),
            "trial_stage_projection.partition_commitment_hash",
        ),
        "frozen_design_hash": sha256_field(
            projection.get("frozen_design_hash"),
            "trial_stage_projection.frozen_design_hash",
        ),
        "execution_node": (
            identifier_field(
                projection.get("execution_node"),
                "trial_stage_projection.execution_node",
            )
            if schema_version == 2
            else None
        ),
    }


def _partition_commitment_hash(trial_plan: dict[str, Any]) -> str:
    payload = sorted(
        (
            item["sample_ref"],
            item["sample_hash"],
            item["role"],
        )
        for item in trial_plan["sample_roles"]
    )
    return _hash(payload)


def _frozen_design_hash(trial_plan: dict[str, Any]) -> str:
    return _hash({
        key: trial_plan[key]
        for key in (
            "trial_plan_id",
            "hypothesis_ref",
            "trial_family",
            "protocol_ref",
            "outcomes",
            "stopping",
            "multiplicity",
            "criteria",
            "decision_contract_hash",
            "methodology_hash",
            "stage_policy",
            "sample_roles",
            "comparisons",
        )
    })


def _hash(value: Any) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()

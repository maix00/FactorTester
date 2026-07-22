"""Validation and hashes for the TrialPlan v5 execution checkpoint."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson

from .contract import canonical_trial_plan
from .fields import (
    identifier_field,
    identifier_list,
    integer_field,
    object_field,
    positive_integer,
    sha256_field,
)


ACTION_STATUSES = frozenset({
    "unreleased", "released", "running", "evidence_ready",
    "admitted", "audited", "failed", "blocked",
})
QUALIFICATIONS = frozenset({
    "eligible", "limited", "pending", "reference_only", "rejected",
})
CHECKPOINT_FIELDS = frozenset({
    "schema_version", "trial_plan_id", "plan_version",
    "ordered_stage_ids", "current_stage_id", "completed_stage_mask",
    "partition_commitment_hash", "frozen_design_hash", "execution_node",
    "current_action_index", "current_action_id", "current_action_status",
    "current_action_input_hash", "current_action_output_evidence_refs",
    "current_action_qualification", "projection_hash",
})


def validate_execution_checkpoint(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("trial_execution_checkpoint must be an object")
    item = object_field(
        value,
        "trial_execution_checkpoint",
        fields=CHECKPOINT_FIELDS,
    )
    if integer_field(item.get("schema_version"), "checkpoint.schema_version") != 3:
        raise ValueError("trial execution checkpoint schema_version must be 3")
    ordered = identifier_list(
        item.get("ordered_stage_ids"),
        "checkpoint.ordered_stage_ids",
        allow_empty=False,
    )
    stage = identifier_field(item.get("current_stage_id"), "checkpoint.current_stage_id")
    if stage not in ordered:
        raise ValueError("current stage is not in ordered_stage_ids")
    status = identifier_field(
        item.get("current_action_status"), "checkpoint.current_action_status"
    )
    if status not in ACTION_STATUSES:
        raise ValueError("unsupported Evidence Action status")
    qualification = item.get("current_action_qualification")
    if qualification is not None and qualification not in QUALIFICATIONS:
        raise ValueError("unsupported Evidence qualification")
    refs = identifier_list(
        item.get("current_action_output_evidence_refs"),
        "checkpoint.current_action_output_evidence_refs",
    )
    if len(refs) > 16:
        raise ValueError("current action may reference at most 16 Evidence objects")
    normalized = {
        "schema_version": 3,
        "trial_plan_id": identifier_field(
            item.get("trial_plan_id"), "checkpoint.trial_plan_id"
        ),
        "plan_version": positive_integer(
            item.get("plan_version"), "checkpoint.plan_version"
        ),
        "ordered_stage_ids": ordered,
        "current_stage_id": stage,
        "completed_stage_mask": integer_field(
            item.get("completed_stage_mask"), "checkpoint.completed_stage_mask"
        ),
        "partition_commitment_hash": sha256_field(
            item.get("partition_commitment_hash"), "checkpoint.partition_hash"
        ),
        "frozen_design_hash": sha256_field(
            item.get("frozen_design_hash"), "checkpoint.design_hash"
        ),
        "execution_node": identifier_field(
            item.get("execution_node"), "checkpoint.execution_node"
        ),
        "current_action_index": integer_field(
            item.get("current_action_index"), "checkpoint.current_action_index"
        ),
        "current_action_id": identifier_field(
            item.get("current_action_id"), "checkpoint.current_action_id"
        ),
        "current_action_status": status,
        "current_action_input_hash": sha256_field(
            item.get("current_action_input_hash"), "checkpoint.action_input_hash"
        ),
        "current_action_output_evidence_refs": refs,
        "current_action_qualification": qualification,
    }
    if normalized["completed_stage_mask"] < 0:
        raise ValueError("completed_stage_mask must be non-negative")
    if normalized["completed_stage_mask"] >= (1 << len(ordered)):
        raise ValueError("completed_stage_mask exceeds the ordered stages")
    if normalized["current_action_index"] < 0:
        raise ValueError("current_action_index must be non-negative")
    if status in {"admitted", "audited"} and qualification is None:
        raise ValueError(f"{status} checkpoint requires qualification")
    if status not in {"admitted", "audited"} and qualification is not None:
        raise ValueError("qualification exists before Evidence admission")
    observed_hash = sha256_field(
        item.get("projection_hash"), "checkpoint.projection_hash"
    )
    if observed_hash != checkpoint_hash(normalized):
        raise ValueError("trial execution checkpoint hash is invalid")
    return {**normalized, "projection_hash": observed_hash}


def seal_checkpoint(value: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(value)
    normalized["projection_hash"] = checkpoint_hash(normalized)
    return validate_execution_checkpoint(normalized)


def without_checkpoint_hash(value: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(value)
    result.pop("projection_hash", None)
    return result


def partition_commitment_hash(plan: dict[str, Any]) -> str:
    return checkpoint_hash([
        (item["sample_ref"], item["sample_hash"], item["stage_id"])
        for item in plan["samples"]
    ])


def frozen_design_hash(plan: dict[str, Any]) -> str:
    return checkpoint_hash({
        key: plan[key]
        for key in (
            "outcomes", "samples", "comparisons", "stopping",
            "multiplicity", "criteria", "stage_policy",
            "primary_obligation_ref", "secondary_obligation_refs",
            "design_evidence_refs", "trial_ledger_ref",
            "holdout_access_ledger_ref", "reopen_predicate_refs",
            "evidence_actions",
        )
    })


def validate_checkpoint_plan_identity(
    checkpoint: dict[str, Any],
    trial_plan: dict[str, Any],
) -> dict[str, Any]:
    plan = canonical_trial_plan(trial_plan)
    if plan["schema_version"] != 5:
        raise ValueError("execution checkpoint requires TrialPlan schema v5")
    if (
        checkpoint["trial_plan_id"] != plan["trial_plan_id"]
        or checkpoint["plan_version"] != plan["version"]
        or checkpoint["ordered_stage_ids"] != plan["stage_policy"]["ordered_stage_ids"]
        or checkpoint["partition_commitment_hash"] != partition_commitment_hash(plan)
        or checkpoint["frozen_design_hash"] != frozen_design_hash(plan)
    ):
        raise ValueError("TrialPlan does not match execution checkpoint")
    index = checkpoint["current_action_index"]
    actions = plan["evidence_actions"]
    if index >= len(actions):
        raise ValueError("execution checkpoint action index exceeds TrialPlan")
    action = actions[index]
    if (
        checkpoint["current_action_id"] != action["action_id"]
        or checkpoint["current_action_input_hash"] != action["input_hash"]
        or checkpoint["current_stage_id"] != action["stage_id"]
    ):
        raise ValueError("current Evidence Action does not match TrialPlan")
    return plan


def checkpoint_hash(value: Any) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()

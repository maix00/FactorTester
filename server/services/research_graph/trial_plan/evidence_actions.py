"""Bounded Evidence Action definitions for TrialPlan schema v5."""

from __future__ import annotations

from typing import Any

import orjson

from .fields import (
    array_field,
    identifier_field,
    identifier_list,
    object_field,
    sha256_field,
)


MAX_EVIDENCE_ACTIONS = 8
MAX_ACTION_BYTES = 768
MAX_ACTION_OBLIGATIONS = 16
MAX_ACTION_PREDICATES = 16
EXECUTION_MODES = frozenset({"sync_cli", "job", "connector"})


def canonical_evidence_actions(
    value: Any,
    *,
    obligation_refs: set[str],
    stage_ids: set[str],
) -> list[dict[str, Any]]:
    items = array_field(
        value,
        "trial_plan.evidence_actions",
        allow_empty=False,
    )
    if len(items) > MAX_EVIDENCE_ACTIONS:
        raise ValueError(
            f"trial_plan.evidence_actions must contain at most "
            f"{MAX_EVIDENCE_ACTIONS} items"
        )
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(items):
        action = _canonical_action(
            raw,
            index=index,
            obligation_refs=obligation_refs,
            stage_ids=stage_ids,
            earlier_action_ids=seen,
        )
        action_id = action["action_id"]
        if action_id in seen:
            raise ValueError("evidence action IDs must be unique")
        if len(orjson.dumps(action)) > MAX_ACTION_BYTES:
            raise ValueError(
                f"trial_plan.evidence_actions[{index}] exceeds "
                f"{MAX_ACTION_BYTES} bytes"
            )
        seen.add(action_id)
        normalized.append(action)
    return normalized


def _canonical_action(
    value: Any,
    *,
    index: int,
    obligation_refs: set[str],
    stage_ids: set[str],
    earlier_action_ids: set[str],
) -> dict[str, Any]:
    path = f"trial_plan.evidence_actions[{index}]"
    item = object_field(
        value,
        path,
        fields=frozenset({
            "action_id",
            "stage_id",
            "obligation_refs",
            "capability_requirement_ref",
            "execution_mode",
            "input_hash",
            "expected_evidence_kind",
            "evidence_contract_ref",
            "prerequisite_action_ids",
            "cost_ref",
            "stop_predicate_refs",
        }),
    )
    action_id = identifier_field(item.get("action_id"), f"{path}.action_id")
    stage_id = identifier_field(item.get("stage_id"), f"{path}.stage_id")
    if stage_id not in stage_ids:
        raise ValueError(f"{path}.stage_id is not declared by stage_policy")
    action_obligations = identifier_list(
        item.get("obligation_refs"),
        f"{path}.obligation_refs",
        allow_empty=False,
    )
    _bounded(action_obligations, MAX_ACTION_OBLIGATIONS, f"{path}.obligation_refs")
    unknown = sorted(set(action_obligations) - obligation_refs)
    if unknown:
        raise ValueError(
            f"{path}.obligation_refs are not declared by TrialPlan: "
            + ", ".join(unknown)
        )
    prerequisites = identifier_list(
        item.get("prerequisite_action_ids"),
        f"{path}.prerequisite_action_ids",
    )
    if not set(prerequisites).issubset(earlier_action_ids):
        raise ValueError(
            f"{path}.prerequisite_action_ids must reference earlier actions"
        )
    stop_refs = identifier_list(
        item.get("stop_predicate_refs"),
        f"{path}.stop_predicate_refs",
    )
    _bounded(stop_refs, MAX_ACTION_PREDICATES, f"{path}.stop_predicate_refs")
    mode = identifier_field(
        item.get("execution_mode"),
        f"{path}.execution_mode",
    )
    if mode not in EXECUTION_MODES:
        raise ValueError(f"{path}.execution_mode is unsupported: {mode}")
    return {
        "action_id": action_id,
        "stage_id": stage_id,
        "obligation_refs": action_obligations,
        "capability_requirement_ref": identifier_field(
            item.get("capability_requirement_ref"),
            f"{path}.capability_requirement_ref",
        ),
        "execution_mode": mode,
        "input_hash": sha256_field(item.get("input_hash"), f"{path}.input_hash"),
        "expected_evidence_kind": identifier_field(
            item.get("expected_evidence_kind"),
            f"{path}.expected_evidence_kind",
        ),
        "evidence_contract_ref": identifier_field(
            item.get("evidence_contract_ref"),
            f"{path}.evidence_contract_ref",
        ),
        "prerequisite_action_ids": prerequisites,
        "cost_ref": identifier_field(item.get("cost_ref"), f"{path}.cost_ref"),
        "stop_predicate_refs": stop_refs,
    }


def _bounded(values: list[str], maximum: int, path: str) -> None:
    if len(values) > maximum:
        raise ValueError(f"{path} must contain at most {maximum} items")

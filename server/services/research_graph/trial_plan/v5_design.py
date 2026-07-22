"""Product-neutral design components for TrialPlan schema v5."""

from __future__ import annotations

from typing import Any

from .fields import (
    array_field,
    identifier_field,
    identifier_list,
    object_field,
    sha256_field,
    sha256_list,
)


SEMANTIC_ROLES = frozenset({
    "diagnostic",
    "selection",
    "validation",
    "confirmation",
    "holdout",
})


def canonical_v5_stage_policy(value: Any) -> dict[str, Any]:
    item = object_field(
        value,
        "trial_plan.stage_policy",
        fields=frozenset({
            "ordered_stage_ids",
            "entry_stage_id",
            "entry_basis_ref",
        }),
    )
    ordered = identifier_list(
        item.get("ordered_stage_ids"),
        "trial_plan.stage_policy.ordered_stage_ids",
        allow_empty=False,
    )
    entry = identifier_field(
        item.get("entry_stage_id"),
        "trial_plan.stage_policy.entry_stage_id",
    )
    if entry != ordered[0]:
        raise ValueError("TrialPlan entry_stage_id must be the first stage")
    return {
        "ordered_stage_ids": ordered,
        "entry_stage_id": entry,
        "entry_basis_ref": identifier_field(
            item.get("entry_basis_ref"),
            "trial_plan.stage_policy.entry_basis_ref",
        ),
    }


def canonical_v5_samples(
    value: Any,
    *,
    stage_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    items = array_field(value, "trial_plan.samples", allow_empty=False)
    normalized: list[dict[str, Any]] = []
    sample_refs: set[str] = set()
    sample_hashes: set[str] = set()
    run_bindings: dict[str, dict[str, str]] = {}
    observed_stages: set[str] = set()
    for index, raw in enumerate(items):
        path = f"trial_plan.samples[{index}]"
        item = object_field(
            raw,
            path,
            fields=frozenset({
                "sample_ref",
                "sample_hash",
                "stage_id",
                "semantic_role",
                "run_spec_hashes",
            }),
        )
        sample_ref = identifier_field(item.get("sample_ref"), f"{path}.sample_ref")
        sample_hash = sha256_field(item.get("sample_hash"), f"{path}.sample_hash")
        stage_id = identifier_field(item.get("stage_id"), f"{path}.stage_id")
        role = identifier_field(item.get("semantic_role"), f"{path}.semantic_role")
        if sample_ref in sample_refs or sample_hash in sample_hashes:
            raise ValueError("TrialPlan sample identities must be unique")
        if stage_id not in stage_ids:
            raise ValueError(f"{path}.stage_id is not declared by stage_policy")
        if role not in SEMANTIC_ROLES:
            raise ValueError(f"{path}.semantic_role is unsupported: {role}")
        hashes = sha256_list(item.get("run_spec_hashes"), f"{path}.run_spec_hashes")
        for run_hash in hashes:
            if run_hash in run_bindings:
                raise ValueError("one RunSpec cannot cross TrialPlan samples")
            run_bindings[run_hash] = {
                "stage_id": stage_id,
                "semantic_role": role,
            }
        sample_refs.add(sample_ref)
        sample_hashes.add(sample_hash)
        observed_stages.add(stage_id)
        normalized.append({
            "sample_ref": sample_ref,
            "sample_hash": sample_hash,
            "stage_id": stage_id,
            "semantic_role": role,
            "run_spec_hashes": hashes,
        })
    if observed_stages != stage_ids:
        raise ValueError("TrialPlan samples must cover every ordered stage")
    return normalized, run_bindings


def canonical_v5_comparisons(
    value: Any,
    *,
    run_bindings: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    items = array_field(value, "trial_plan.comparisons", allow_empty=False)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(items):
        path = f"trial_plan.comparisons[{index}]"
        item = object_field(
            raw,
            path,
            fields=frozenset({
                "comparison_id",
                "target_ref",
                "baseline_ref",
                "allowed_difference_refs",
                "members",
            }),
        )
        comparison_id = identifier_field(
            item.get("comparison_id"),
            f"{path}.comparison_id",
        )
        if comparison_id in seen:
            raise ValueError("comparison_id values must be unique")
        seen.add(comparison_id)
        members = _members(
            item.get("members"),
            path=f"{path}.members",
            run_bindings=run_bindings,
        )
        normalized.append({
            "comparison_id": comparison_id,
            "target_ref": identifier_field(
                item.get("target_ref"), f"{path}.target_ref"
            ),
            "baseline_ref": identifier_field(
                item.get("baseline_ref"), f"{path}.baseline_ref"
            ),
            "allowed_difference_refs": identifier_list(
                item.get("allowed_difference_refs"),
                f"{path}.allowed_difference_refs",
                allow_empty=False,
            ),
            "members": members,
        })
    return normalized


def _members(
    value: Any,
    *,
    path: str,
    run_bindings: dict[str, dict[str, str]],
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
        if run_hash not in run_bindings:
            raise ValueError(f"{item_path}.run_spec_hash has no declared sample")
        role = identifier_field(item.get("trial_role"), f"{item_path}.trial_role")
        identity = (run_hash, role)
        if identity in identities:
            raise ValueError("comparison members must be unique")
        identities.add(identity)
        normalized.append({"run_spec_hash": run_hash, "trial_role": role})
    return normalized

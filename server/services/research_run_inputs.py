"""Pure input normalization for immutable ResearchRun creation."""

from __future__ import annotations

from typing import Any

import orjson

from server.services.research_graph.trial_plan.binding import (
    normalize_run_binding,
)
from server.services.research_sample_exposure import (
    PROTECTED_SAMPLE_ROLES,
    require_exact_product_membership,
)
from server.services.research_sample_identity import (
    derive_sample_identity,
)


def normalize_trial_binding(
    value: dict[str, Any] | None,
    *,
    run_spec_hash: str,
    sample_identity: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("trial_binding must be an object")
    if value.get("binding_origin") is not None:
        binding = _normalize_direct_trial_binding(
            value,
            run_spec_hash=run_spec_hash,
            sample_identity=sample_identity,
        )
        return _require_protected_sample_scope(binding, sample_identity)
    required = {
        "instance_id", "branch_id", "trial_plan", "trial_plan_hash",
        "trial_plan_version", "trial_role", "comparison_id",
    }
    action_fields = {
        "evidence_action_id",
        "expected_checkpoint_hash",
        "expected_latest_trace_id",
    }
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required - action_fields)
    if missing:
        raise ValueError("trial_binding missing fields: " + ", ".join(missing))
    if extra:
        raise ValueError(
            "trial_binding has unsupported fields: " + ", ".join(extra)
        )
    instance_id = str(value["instance_id"] or "").strip()
    branch_id = str(value["branch_id"] or "").strip()
    if not instance_id or not branch_id:
        raise ValueError("trial_binding requires instance_id and branch_id")
    binding = normalize_run_binding(
        trial_plan=value["trial_plan"],
        expected_hash=str(value["trial_plan_hash"]),
        expected_version=value["trial_plan_version"],
        run_spec_hash=run_spec_hash,
        trial_role=str(value["trial_role"]),
        comparison_id=str(value["comparison_id"]),
        sample_identity=sample_identity,
        evidence_action_id=str(value.get("evidence_action_id") or ""),
    )
    schema_version = int(binding["trial_plan_schema_version"])
    if schema_version == 5:
        missing_action = sorted(
            field
            for field in action_fields
            if not str(value.get(field) or "").strip()
        )
        if missing_action:
            raise ValueError(
                "TrialPlan schema v5 trial_binding missing fields: "
                + ", ".join(missing_action)
            )
    elif any(str(value.get(field) or "").strip() for field in action_fields):
        raise ValueError("legacy TrialPlan cannot bind Evidence Action fields")
    binding = {
        "binding_origin": "research_graph",
        "instance_id": instance_id,
        "branch_id": branch_id,
        "trial_plan": value["trial_plan"],
        "expected_checkpoint_hash": str(
            value.get("expected_checkpoint_hash") or ""
        ),
        "expected_latest_trace_id": str(
            value.get("expected_latest_trace_id") or ""
        ),
        **binding,
    }
    return _require_protected_sample_scope(binding, sample_identity)


def _require_protected_sample_scope(
    binding: dict[str, Any],
    sample_identity: dict[str, Any] | None,
) -> dict[str, Any]:
    if str(binding.get("trial_stage") or "") in PROTECTED_SAMPLE_ROLES:
        require_exact_product_membership(sample_identity)
    return binding


def _normalize_direct_trial_binding(
    value: dict[str, Any],
    *,
    run_spec_hash: str,
    sample_identity: dict[str, Any] | None,
) -> dict[str, Any]:
    required = {
        "binding_origin", "trial_plan", "trial_plan_hash", "trial_plan_ref",
        "trial_plan_version", "trial_role", "comparison_id",
    }
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    if missing:
        raise ValueError(
            "direct trial_binding missing fields: " + ", ".join(missing)
        )
    if extra:
        raise ValueError(
            "direct trial_binding has unsupported fields: " + ", ".join(extra)
        )
    if str(value["binding_origin"]) != "agent_direct":
        raise ValueError("direct trial_binding origin must be agent_direct")
    plan = value["trial_plan"]
    if isinstance(plan, dict) and int(plan.get("schema_version") or 0) == 5:
        raise ValueError("TrialPlan schema v5 cannot be used outside Research Graph")
    binding = normalize_run_binding(
        trial_plan=plan,
        expected_hash=str(value["trial_plan_hash"]),
        expected_version=value["trial_plan_version"],
        run_spec_hash=run_spec_hash,
        trial_role=str(value["trial_role"]),
        comparison_id=str(value["comparison_id"]),
        sample_identity=sample_identity,
    )
    expected_ref = "trial-plan:sha256:" + str(binding["trial_plan_hash"])
    if str(value["trial_plan_ref"]) != expected_ref:
        raise ValueError("trial_plan_ref does not match TrialPlan hash")
    return {
        "binding_origin": "agent_direct",
        "instance_id": "",
        "branch_id": "",
        "trial_plan": plan,
        "trial_plan_ref": expected_ref,
        "expected_checkpoint_hash": "",
        "expected_latest_trace_id": "",
        **binding,
    }


def derive_sample_identity_or_none(
    run_spec: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        return derive_sample_identity(run_spec)
    except ValueError:
        return None


def persisted_sample_identity(
    *,
    binding: dict[str, Any] | None,
    sample_identity: dict[str, Any] | None,
) -> dict[str, str]:
    identity = sample_identity or {}
    exact_members = (
        identity.get("universe_membership_assurance")
        == "exact_frozen_product_scope"
    )
    members_json = (
        orjson.dumps(require_exact_product_membership(identity)).decode()
        if exact_members
        else ""
    )
    assurance = str(
        (binding or {}).get("sample_identity_assurance")
        or ("server_derived_unbound" if sample_identity else "unavailable")
    )
    return {
        "sample_identity_hash": str(identity.get("sample_hash") or ""),
        "sample_start": str(identity.get("sample_start") or ""),
        "sample_end": str(identity.get("sample_end") or ""),
        "sample_universe_hash": str(identity.get("universe_hash") or ""),
        "sample_universe_members_json": members_json,
        "sample_design_context_hash": str(
            identity.get("design_context_hash") or ""
        ),
        "sample_identity_assurance": assurance,
    }

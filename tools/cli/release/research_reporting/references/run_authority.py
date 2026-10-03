"""Validate immutable Run and TrialPlan report references."""

from __future__ import annotations

from typing import Any

from tools.cli.client import FactorTesterClient
from ..authoring.declared_links import DeclaredReportReference


def validate_run_reference(
    *, reference: DeclaredReportReference, client: FactorTesterClient,
) -> dict[str, Any]:
    kind, target_ref = reference.kind, reference.target_ref
    prefixes = {
        "run": "run:",
        "run_spec": "runspec:sha256:",
        "trial_plan": "trial-plan:",
    }
    prefix = prefixes.get(kind)
    if prefix is None or not target_ref.startswith(prefix) or target_ref == prefix:
        raise ValueError("invalid Run or TrialPlan reference")
    object_id = target_ref.removeprefix(prefix)
    if kind == "run":
        value = client.get_run(object_id)
        field, expected = "run_id", object_id
    elif kind == "run_spec":
        value = client.get_run_spec(object_id)
        field, expected = "run_spec_hash", object_id
    else:
        value = client.get_direct_trial_plan(target_ref)
        field, expected = (
            ("trial_plan_hash", object_id.removeprefix("sha256:"))
            if object_id.startswith("sha256:")
            else ("trial_plan_id", object_id)
        )
    if str(value.get(field) or "") != expected:
        raise ValueError("Run authority did not return the exact reference")
    fields = {
        "run_id", "run_spec_hash", "run_spec_version",
        "configuration_id", "configuration_revision",
        "trial_plan_id", "trial_plan_hash", "version",
        "status", "binding_origin",
    }
    return {
        **{key: value[key] for key in fields if key in value},
        "authority_scope": "owner_run_registry" if kind != "trial_plan" else "direct_registry",
    }

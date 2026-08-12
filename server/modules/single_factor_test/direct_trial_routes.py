"""HTTP contract for Graph-independent TrialPlan validation."""

from __future__ import annotations

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services.direct_trial_plans import create_binding
from server.services import direct_trial_plan_registry
from server.services.session_runtime import require_user


@sft_bp.post("/api/trial-plans/direct")
def create_direct_trial_plan():
    owner = require_user()
    payload = request.get_json(silent=True) or {}
    try:
        binding = create_binding(
            trial_plan=payload.get("trial_plan"),
            run_spec_hash=str(payload.get("run_spec_hash") or ""),
            trial_role=str(payload.get("trial_role") or ""),
            comparison_id=str(payload.get("comparison_id") or ""),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    direct_trial_plan_registry.save(owner=owner, binding=binding)
    return jsonify({"success": True, "trial_binding": binding})


@sft_bp.get("/api/trial-plans/direct/<trial_plan_hash>")
def get_direct_trial_plan(trial_plan_hash: str):
    value = direct_trial_plan_registry.load(
        owner=require_user(),
        trial_plan_hash=trial_plan_hash,
    )
    if value is None:
        return jsonify({"success": False, "error": "TrialPlan not found"}), 404
    return jsonify({"success": True, "trial_plan": value})

"""Read-only compatibility routes for historical TrialPlan records."""

from __future__ import annotations

from flask import jsonify

from server.modules.single_factor_test import sft_bp
from server.services import direct_trial_plan_registry
from server.services.session_runtime import require_user


@sft_bp.post("/api/trial-plans/direct")
def create_direct_trial_plan():
    require_user()
    return jsonify({
        "success": False,
        "error": (
            "TrialPlan creation is retired; declare sample_use on the Run "
            "submission instead"
        ),
    }), 410


@sft_bp.get("/api/trial-plans/direct/<trial_plan_hash>")
def get_direct_trial_plan(trial_plan_hash: str):
    value = direct_trial_plan_registry.load(
        owner=require_user(),
        trial_plan_hash=trial_plan_hash,
    )
    if value is None:
        return jsonify({"success": False, "error": "TrialPlan not found"}), 404
    return jsonify({"success": True, "trial_plan": value})

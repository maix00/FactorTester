"""HTTP boundary for safe supersession of an unused TrialPlan."""

from __future__ import annotations

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services.research_graph.trial_plan.revision import (
    revise_current_trial_plan,
)
from server.services.session_runtime import require_user


@sft_bp.post(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/trial-plan/revisions"
)
def revise_trial_plan(instance_id: str, branch_id: str):
    data = request.get_json(silent=True) or {}
    try:
        value = revise_current_trial_plan(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
            expected_latest_trace_id=str(
                data.get("expected_latest_trace_id") or ""
            ),
            expected_checkpoint_hash=str(
                data.get("expected_checkpoint_hash") or ""
            ),
            expected_trial_plan_hash=str(
                data.get("expected_trial_plan_hash") or ""
            ),
            trial_plan=data.get("trial_plan"),
            acting_profile_ref=str(
                data.get("acting_profile_ref") or ""
            ),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "revision": value}), 201

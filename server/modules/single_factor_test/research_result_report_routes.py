"""HTTP boundary for authoritative Action result reporting."""

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services.research_step.result_reporting import (
    backfill_result_audit,
    load_result_report_projection,
)
from server.services.session_runtime import require_user


@sft_bp.get(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/result-report-projection"
)
def get_result_report_projection(instance_id: str, branch_id: str):
    try:
        value = load_result_report_projection(
            instance_id=instance_id, branch_id=branch_id,
            owner=require_user(),
            action_id=str(request.args.get("action_id") or ""),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "projection": value})


@sft_bp.post(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/result-audit-backfills"
)
def backfill_result_audit_receipt(instance_id: str, branch_id: str):
    data = request.get_json(silent=True) or {}
    try:
        value = backfill_result_audit(
            instance_id=instance_id, branch_id=branch_id,
            owner=require_user(),
            audited_checkpoint=data.get("audited_checkpoint"),
            proposal=data.get("proposal"), decision=data.get("decision"),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "receipt": value}), 201

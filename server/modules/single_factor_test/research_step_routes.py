"""Authenticated routes for the bounded Research Step contracts."""

from __future__ import annotations

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services import research_graphs
from server.services.research_graph.trial_plan import execution_checkpoint_api
from server.services.research_step import (
    build_inspect_contract,
    build_prepare_contract,
)
from server.services.session_runtime import require_user


def _authoritative_reads(instance_id: str, branch_id: str):
    owner = require_user()
    next_packet = research_graphs.build_graph_branch_next(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    execution = execution_checkpoint_api.load_execution_checkpoint_contract(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    return next_packet, execution


@sft_bp.get(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/research-step"
)
def inspect_research_step(instance_id: str, branch_id: str):
    try:
        next_packet, execution = _authoritative_reads(instance_id, branch_id)
        value = build_inspect_contract(next_packet, execution)
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "research_step": value})


@sft_bp.post(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/research-step/prepare"
)
def prepare_research_step(instance_id: str, branch_id: str):
    data = request.get_json(silent=True) or {}
    payload = data.get("request")
    if not isinstance(payload, dict):
        return jsonify({
            "success": False,
            "error": "request must be a JSON object",
        }), 400
    if set(payload) != {
        "schema_version", "context_ref", "action_id", "configurations",
    }:
        return jsonify({
            "success": False,
            "error": "request fields are invalid",
        }), 400
    try:
        next_packet, execution = _authoritative_reads(instance_id, branch_id)
        inspect = build_inspect_contract(next_packet, execution)
        value = build_prepare_contract(inspect, payload)
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "contract": value})

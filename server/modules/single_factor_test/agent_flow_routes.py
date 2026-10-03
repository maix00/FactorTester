"""Authenticated HTTP Adapter for the provider-neutral Agent Flow Module."""

from __future__ import annotations

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services.agent_execution import get_store
from server.services.agent_flow.authorization import (
    require_execution_authority,
    require_resume_role,
)
from server.services.agent_flow.resume import build_agent_resume_packet
from server.services.session_runtime import require_user


@sft_bp.post("/api/agent-flow/agents/<agent_id>/resume")
def resume_agent(agent_id: str):
    data = request.get_json(silent=True) or {}
    role = str(data.get("role") or "")
    allowed = {
        "research": {"role", "workspace_id"},
        "planning": {"role", "workspace_id"},
        "server_maintenance": {"role"},
    }.get(role)
    if allowed is None:
        return jsonify({
            "success": False,
            "error": "unsupported Agent resume role",
        }), 400
    unexpected = sorted(set(data) - allowed)
    if unexpected:
        return jsonify({
            "success": False,
            "error": (
                "Agent resume contains unsupported fields: "
                + ", ".join(unexpected)
            ),
        }), 400
    owner = require_user()
    try:
        require_resume_role(username=owner, role=role)
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    try:
        packet = build_agent_resume_packet(
            owner=owner,
            agent_id=agent_id,
            role=role,
            workspace_id=str(data.get("workspace_id") or ""),
        )
    except (KeyError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "resume": packet})


@sft_bp.post("/api/research-agent-executions")
def register_research_agent_execution():
    data = request.get_json(silent=True) or {}
    owner = require_user()
    try:
        require_execution_authority(
            username=owner,
            actor_role=str(data.get("actor_role") or ""),
            authority_scope=str(data.get("authority_scope") or ""),
        )
        execution = get_store().register_execution(
            owner_user_id=owner,
            execution_id=str(data.get("execution_id") or ""),
            agent_id=str(data.get("agent_id") or ""),
            actor_role=str(data.get("actor_role") or ""),
            authority_scope=str(data.get("authority_scope") or ""),
            task_ref=str(data.get("task_ref") or ""),
            purpose=str(data.get("purpose") or ""),
            agent_principal_hash=str(
                data.get("agent_principal_hash") or ""
            ),
            lineage_hash=str(data.get("lineage_hash") or ""),
        )
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "execution": execution}), 201

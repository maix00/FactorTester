"""Authenticated HTTP Adapter for the provider-neutral Agent Flow Module."""

from __future__ import annotations

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services import agent_flow
from server.services.agent_flow.resume import build_agent_resume_packet
from server.services.session_runtime import require_user


@sft_bp.post("/api/agent-flow/agents/<agent_id>/resume")
def resume_agent(agent_id: str):
    data = request.get_json(silent=True) or {}
    role = str(data.get("role") or "")
    allowed = {
        "research": {"role", "instance_id", "branch_id"},
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
    store = agent_flow.get_store()
    try:
        packet = build_agent_resume_packet(
            owner=owner,
            agent_id=agent_id,
            role=role,
            budget_period=store.load_current_budget_period(
                owner_user_id=owner,
                agent_id=agent_id,
            ),
            instance_id=str(data.get("instance_id") or ""),
            branch_id=str(data.get("branch_id") or ""),
            workspace_id=str(data.get("workspace_id") or ""),
        )
    except (KeyError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "resume": packet})


@sft_bp.get("/api/agent-flow/agents/<agent_id>/budget")
def load_agent_budget(agent_id: str):
    period = agent_flow.get_store().load_current_budget_period(
        owner_user_id=require_user(),
        agent_id=agent_id,
    )
    if period is None:
        return jsonify({"success": False, "error": "budget not found"}), 404
    return jsonify({"success": True, "budget_period": period})


@sft_bp.put("/api/agent-flow/agents/<agent_id>/budget")
def configure_agent_budget(agent_id: str):
    data = request.get_json(silent=True) or {}
    try:
        period = agent_flow.get_store().configure_token_limit(
            owner_user_id=require_user(),
            agent_id=agent_id,
            token_limit=data.get("token_limit"),
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "budget_period": period})


@sft_bp.post("/api/agent-flow/agents/<agent_id>/budget/reset")
def reset_agent_budget(agent_id: str):
    data = request.get_json(silent=True) or {}
    try:
        period = agent_flow.get_store().reset_budget_period(
            owner_user_id=require_user(),
            agent_id=agent_id,
            token_limit=data.get("token_limit"),
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "budget_period": period})


@sft_bp.post("/api/agent-flow/invocations")
def reserve_agent_invocation():
    data = request.get_json(silent=True) or {}
    try:
        invocation = agent_flow.get_store().reserve_invocation(
            owner_user_id=require_user(),
            agent_id=str(data.get("agent_id") or ""),
            sponsor_agent_id=str(data.get("sponsor_agent_id") or ""),
            actor_role=str(data.get("actor_role") or ""),
            authority_scope=str(data.get("authority_scope") or ""),
            task_ref=str(data.get("task_ref") or ""),
            purpose=str(data.get("purpose") or ""),
            runtime_id=str(data.get("runtime_id") or ""),
            model_id=str(data.get("model_id") or ""),
            max_input_tokens=data.get("max_input_tokens"),
            max_output_tokens=data.get("max_output_tokens"),
            agent_principal_hash=str(
                data.get("agent_principal_hash") or ""
            ),
            lineage_hash=str(data.get("lineage_hash") or ""),
            input_hash=str(data.get("input_hash") or ""),
            context_cost=data.get("context_cost"),
            idempotency_key=str(data.get("idempotency_key") or ""),
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "invocation": invocation}), 201


@sft_bp.post("/api/agent-flow/invocations/<invocation_id>/settle")
def settle_agent_invocation(invocation_id: str):
    data = request.get_json(silent=True) or {}
    try:
        invocation = agent_flow.get_store().settle_invocation(
            owner_user_id=require_user(),
            invocation_id=invocation_id,
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
            cache_read_tokens=data.get("cache_read_tokens", 0),
            provider_request_id=str(
                data.get("provider_request_id") or ""
            ),
            provider_attestation=str(
                data.get("provider_attestation") or ""
            ),
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "invocation": invocation})


@sft_bp.post("/api/agent-flow/invocations/<invocation_id>/release")
def release_agent_invocation(invocation_id: str):
    try:
        invocation = agent_flow.get_store().release_invocation(
            owner_user_id=require_user(),
            invocation_id=invocation_id,
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "invocation": invocation})

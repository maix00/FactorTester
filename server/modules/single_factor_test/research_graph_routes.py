"""Authenticated API for immutable research graph versions and activation."""

from __future__ import annotations

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services import research_graphs
from server.services.session_runtime import require_user


@sft_bp.post("/api/research-graphs/versions")
def create_research_graph_version():
    data = request.get_json(silent=True) or {}
    try:
        graph = research_graphs.register_graph(
            data.get("graph"),
            actor=require_user(),
        )
    except (TypeError, ValueError) as exc:
        status = 409 if isinstance(
            exc, research_graphs.GraphVersionConflict
        ) else 400
        return jsonify({"success": False, "error": str(exc)}), status
    return jsonify({"success": True, "graph": graph}), 201


@sft_bp.get("/api/research-graphs/<graph_id>/versions")
def list_research_graph_versions(graph_id: str):
    require_user()
    return jsonify({
        "success": True,
        "versions": research_graphs.list_graph_versions(graph_id=graph_id),
    })


@sft_bp.get("/api/research-graphs/<graph_id>/active")
def get_active_research_graph(graph_id: str):
    require_user()
    graph = research_graphs.load_active_graph(graph_id=graph_id)
    if graph is None:
        return jsonify({"success": False, "error": "active graph not found"}), 404
    return jsonify({"success": True, "graph": graph})


@sft_bp.post(
    "/api/research-graphs/<graph_id>/versions/<int:version>/proposals"
)
def propose_research_graph_version(graph_id: str, version: int):
    data = request.get_json(silent=True) or {}
    owner = require_user()
    try:
        proposal = research_graphs.record_proposal(
            graph_id=graph_id,
            version=version,
            owner_user_id=owner,
            actor_agent_id=str(data.get("agent_execution_id") or ""),
            risk_level=str(data.get("risk_level") or ""),
            change_diff=data.get("change_diff") or {},
            evidence_refs=data.get("evidence_refs") or [],
            token_estimate=data.get("token_estimate", 0),
            conversation_ref=str(data.get("conversation_ref") or ""),
            pointer_action=str(
                data.get("pointer_action") or "activate_graph"
            ),
            pointer_from_version=int(
                data.get("pointer_from_version") or 0
            ),
            pointer_reason=str(data.get("pointer_reason") or ""),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "proposal": proposal}), 201


@sft_bp.post("/api/research-graph-proposals/<proposal_id>/reviews")
def review_research_graph_proposal(proposal_id: str):
    data = request.get_json(silent=True) or {}
    owner = require_user()
    try:
        review = research_graphs.record_proposal_review(
            proposal_id=proposal_id,
            owner_user_id=owner,
            actor_agent_id=str(data.get("agent_execution_id") or ""),
            disposition=str(data.get("disposition") or ""),
            scope_drift=data.get("scope_drift", False),
            semantic_uncertainty=data.get("semantic_uncertainty", False),
            evidence_refs=data.get("evidence_refs") or [],
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "review": review}), 201


@sft_bp.post("/api/research-capability-approvals")
def approve_research_capability():
    require_user()
    return jsonify({
        "success": False,
        "error": (
            "server capability approvals are retired; approve Skill execution "
            "in the Agent conversation and retain actual-use audit locally"
        ),
    }), 410


@sft_bp.post("/api/research-capability-receipts")
def attest_research_capabilities():
    data = request.get_json(silent=True) or {}
    try:
        receipt = research_graphs.issue_capability_receipt(
            owner_user_id=require_user(),
            graph_id=str(data.get("graph_id") or ""),
            graph_version=int(data.get("graph_version") or 0),
            node_id=str(data.get("node_id") or ""),
            product_group=str(data.get("product_group") or ""),
            catalog_hash=str(data.get("catalog_hash") or ""),
            product_profile_hash=str(data.get("product_profile_hash") or ""),
            resolver_version=str(data.get("resolver_version") or ""),
            semantic_resolution=data.get("semantic_resolution") or {},
            approval_refs=data.get("approval_refs") or {},
            provider_conformance_hash=str(
                data.get("provider_conformance_hash") or ""
            ),
            shadow_mode=bool(data.get("shadow_mode", False)),
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "receipt": receipt}), 201


@sft_bp.post(
    "/api/research-graphs/<graph_id>/versions/<int:version>/validation"
)
def validate_research_graph_version(graph_id: str, version: int):
    data = request.get_json(silent=True) or {}
    owner = require_user()
    try:
        validation = research_graphs.record_validation(
            graph_id=graph_id,
            version=version,
            actor=owner,
            owner_user_id=owner,
            proposal_id=str(data.get("proposal_id") or ""),
            evidence={
                key: value for key, value in data.items()
                if key != "proposal_id"
            },
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "validation": validation}), 201


@sft_bp.post("/api/research-graphs/<graph_id>/versions/<int:version>/audit")
def audit_research_graph_version(graph_id: str, version: int):
    data = request.get_json(silent=True) or {}
    owner = require_user()
    try:
        audit = research_graphs.record_audit(
            graph_id=graph_id,
            version=version,
            actor=owner,
            owner_user_id=owner,
            proposal_id=str(data.get("proposal_id") or ""),
            disposition=str(data.get("disposition") or ""),
            grill_evidence=data.get("grill_evidence") or [],
            grill_ref=str(data.get("grill_ref") or ""),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "audit": audit}), 201


@sft_bp.post(
    "/api/research-graphs/<graph_id>/versions/<int:version>/activate"
)
def activate_research_graph_version(graph_id: str, version: int):
    data = request.get_json(silent=True) or {}
    try:
        graph = research_graphs.activate_graph(
            graph_id=graph_id,
            source_version=version,
            actor=require_user(),
            human_authorization_id=str(
                data.get("human_authorization_id") or ""
            ),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except research_graphs.GraphActivationBlocked as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "graph": graph}), 201


@sft_bp.post("/api/research-human-activation-authorizations")
def authorize_research_graph_activation():
    data = request.get_json(silent=True) or {}
    owner = require_user()
    try:
        authorization = research_graphs.authorize_graph_activation(
            owner_user_id=owner,
            graph_id=str(data.get("graph_id") or ""),
            graph_version=int(data.get("graph_version") or 0),
            proposal_id=str(data.get("proposal_id") or ""),
            graph_hash=str(data.get("graph_hash") or ""),
            diff_hash=str(data.get("diff_hash") or ""),
            conversation_ref=str(data.get("conversation_ref") or ""),
            approval_ref=str(data.get("approval_ref") or ""),
            pointer_action=str(
                data.get("pointer_action") or "activate_graph"
            ),
            pointer_from_version=int(
                data.get("pointer_from_version") or 0
            ),
            pointer_reason=str(data.get("pointer_reason") or ""),
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({
        "success": True,
        "authorization": authorization,
    }), 201


@sft_bp.post("/api/research-backend-assurance/evaluate")
def retired_research_backend_assurance():
    return _retired_backend_assurance_response()


@sft_bp.post(
    "/api/research-backend-assurance/<receipt_id>/verification"
)
def verify_research_backend_assurance(receipt_id: str):
    del receipt_id
    return _retired_backend_assurance_response()


def _retired_backend_assurance_response():
    require_user()
    return jsonify({
        "success": False,
        "error": (
            "Graph backend assurance receipts are retired; terminal "
            "assurance is Job-owned and review is MaintenanceCase-owned."
        ),
        "replacement": {
            "job_evidence": (
                "GET /api/jobs/<job_id> -> evidence.terminal_assurance"
            ),
            "verification": "MaintenanceCase",
        },
    }), 410


@sft_bp.post("/api/research-graphs/<graph_id>/rollback")
def rollback_research_graph(graph_id: str):
    data = request.get_json(silent=True) or {}
    try:
        rollback = research_graphs.rollback_active_graph(
            graph_id=graph_id,
            target_version=int(data.get("target_version") or 0),
            actor=require_user(),
            reason=str(data.get("reason") or ""),
            human_authorization_id=str(
                data.get("human_authorization_id") or ""
            ),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "rollback": rollback}), 201


@sft_bp.post("/api/research-graph-instances")
def create_research_graph_instance():
    data = request.get_json(silent=True) or {}
    try:
        instance = research_graphs.create_graph_instance(
            graph_id=str(data.get("graph_id") or ""),
            owner=require_user(),
            product_group=str(data.get("product_group") or ""),
            workspace_id=str(data.get("workspace_id") or ""),
            capability_receipt=data.get("capability_receipt") or {},
            shadow_graph_version=data.get("shadow_graph_version"),
            shadow_run_id=str(data.get("shadow_run_id") or ""),
        )
    except (ValueError, research_graphs.GraphActivationBlocked) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "instance": instance}), 201


@sft_bp.post(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>/fork"
)
def fork_research_graph_branch(instance_id: str, branch_id: str):
    data = request.get_json(silent=True) or {}
    try:
        branch = research_graphs.fork_graph_branch(
            instance_id=instance_id,
            source_branch_id=branch_id,
            owner=require_user(),
            label=str(data.get("label") or "fork"),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "branch": branch}), 201


@sft_bp.get(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
)
def get_research_graph_branch(instance_id: str, branch_id: str):
    branch = research_graphs.load_graph_branch(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=require_user(),
    )
    if branch is None:
        return jsonify({"success": False, "error": "graph branch not found"}), 404
    return jsonify({"success": True, "branch": branch})


@sft_bp.get(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>/context"
)
def get_research_graph_branch_context(instance_id: str, branch_id: str):
    try:
        context = research_graphs.build_graph_branch_context(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "context": context})


@sft_bp.get(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>/next"
)
def get_research_graph_branch_next(instance_id: str, branch_id: str):
    try:
        packet = research_graphs.build_graph_branch_next(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "next": packet})


@sft_bp.post(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>/advance"
)
def advance_research_graph_branch(instance_id: str, branch_id: str):
    data = request.get_json(silent=True) or {}
    try:
        branch = research_graphs.advance_graph_branch(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
            edge_id=str(data.get("edge_id") or ""),
            evidence=data.get("evidence") or {},
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "branch": branch})

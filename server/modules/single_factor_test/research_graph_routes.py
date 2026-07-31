"""Authenticated API for immutable research graph versions and activation."""

from __future__ import annotations

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services import research_graphs
from server.services.session_runtime import require_user
from tools.data.account_manage import get_account, is_super_admin_account


@sft_bp.post("/api/research-graphs/versions")
def create_research_graph_version():
    data = request.get_json(silent=True) or {}
    graph = data.get("graph")
    if not isinstance(graph, dict):
        return jsonify({
            "success": False,
            "error": "graph must be a JSON object",
        }), 400
    try:
        graph = research_graphs.register_graph(
            graph,
            actor=require_user(),
        )
    except (TypeError, ValueError) as exc:
        status = 409 if isinstance(
            exc, research_graphs.GraphVersionConflict
        ) else 400
        return jsonify({"success": False, "error": str(exc)}), status
    return jsonify({"success": True, "graph": graph}), 201


@sft_bp.put(
    "/api/research-graphs/<graph_id>/versions/<int:version>/unused-draft"
)
def revise_unused_research_graph_draft(graph_id: str, version: int):
    actor = require_user()
    if not is_super_admin_account(get_account(actor)):
        return jsonify({
            "success": False,
            "error": "only a super administrator may revise an unused draft",
        }), 403
    data = request.get_json(silent=True) or {}
    graph = data.get("graph")
    if not isinstance(graph, dict):
        return jsonify({
            "success": False,
            "error": "graph must be a JSON object",
        }), 400
    if (
        str(graph.get("graph_id") or "") != graph_id
        or int(graph.get("version") or 0) != version
    ):
        return jsonify({
            "success": False,
            "error": "draft revision route identity does not match graph",
        }), 400
    try:
        graph = research_graphs.revise_unused_draft(graph, actor=actor)
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "graph": graph})


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


@sft_bp.get(
    "/api/research-graphs/<graph_id>/versions/<int:version>/activation"
)
def get_research_graph_activation_preflight(graph_id: str, version: int):
    owner = require_user()
    try:
        activation = research_graphs.activation_preflight(
            graph_id=graph_id,
            version=version,
            owner_user_id=owner,
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except research_graphs.GraphActivationBlocked as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "activation": activation})


@sft_bp.get("/api/research-graph-proposals/<proposal_id>")
def get_research_graph_proposal_review_packet(proposal_id: str):
    owner = require_user()
    try:
        proposal_review = research_graphs.load_proposal_review_packet(
            owner_user_id=owner,
            proposal_id=proposal_id,
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({
        "success": True,
        "proposal_review": proposal_review,
    })


@sft_bp.post(
    "/api/research-graphs/<graph_id>/versions/<int:version>/activation"
)
def orchestrate_research_graph_activation(graph_id: str, version: int):
    owner = require_user()
    data = request.get_json(silent=True) or {}
    try:
        activation = research_graphs.activate_reviewed_graph(
            graph_id=graph_id,
            version=version,
            owner_user_id=owner,
            approval_ref=str(data.get("approval_ref") or ""),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (
        ValueError,
        research_graphs.GraphActivationBlocked,
    ) as exc:
        return jsonify({
            "success": False,
            "error": str(exc),
            "activation": research_graphs.activation_preflight(
                graph_id=graph_id,
                version=version,
                owner_user_id=owner,
            ),
        }), 409
    return jsonify({"success": True, "activation": activation}), 201


@sft_bp.get("/api/research-runtime-budget-profiles/active")
def get_active_research_runtime_budget_profile():
    require_user()
    return jsonify({
        "success": True,
        "profile": (
            research_graphs.active_runtime_packet_budget_configuration()
        ),
    })


@sft_bp.post("/api/research-runtime-budget-profiles")
def configure_research_runtime_budget_profile():
    actor = require_user()
    if not is_super_admin_account(get_account(actor)):
        return jsonify({
            "success": False,
            "error": "only a super administrator may configure runtime budget",
        }), 403
    data = request.get_json(silent=True) or {}
    try:
        profile = research_graphs.configure_runtime_packet_budget_profile(
            ceiling_bytes=int(data.get("ceiling_bytes") or 0),
            actor=actor,
            provider_id=str(data.get("provider_id") or ""),
            model_id=str(data.get("model_id") or ""),
            tokenizer_id=str(data.get("tokenizer_id") or ""),
            tokenizer_revision=str(
                data.get("tokenizer_revision") or ""
            ),
            calibration_receipt_ref=str(
                data.get("calibration_receipt_ref") or ""
            ),
            calibration_receipt_hash=str(
                data.get("calibration_receipt_hash") or ""
            ),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "profile": profile}), 201


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
            title=str(data.get("title") or ""),
            capability_resolution=data.get("capability_resolution") or {},
            profile_ref=str(
                data.get("profile_ref")
                or data.get("created_by_profile_ref")
                or ""
            ),
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
            acting_profile_ref=str(
                data.get("acting_profile_ref")
                or data.get("profile_ref")
                or ""
            ),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (PermissionError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "branch": branch}), 201


@sft_bp.post(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/handoff"
)
def handoff_research_graph_branch(instance_id: str, branch_id: str):
    data = request.get_json(silent=True) or {}
    try:
        handoff = research_graphs.handoff_graph_branch(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
            source_profile_ref=str(data.get("source_profile_ref") or ""),
            destination_profile_ref=str(
                data.get("destination_profile_ref") or ""
            ),
            expected_checkpoint_ref=str(
                data.get("expected_checkpoint_ref") or ""
            ),
            expected_checkpoint_hash=str(
                data.get("expected_checkpoint_hash") or ""
            ),
            authorization_ref=str(data.get("authorization_ref") or ""),
            source_display_name=str(data.get("source_display_name") or ""),
            destination_display_name=str(
                data.get("destination_display_name") or ""
            ),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (PermissionError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "handoff": handoff}), 201


@sft_bp.post(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/continuation-preview"
)
def preview_research_graph_continuation(instance_id: str, branch_id: str):
    data = request.get_json(silent=True) or {}
    try:
        preview = research_graphs.preview_graph_continuation(
            source_instance_id=instance_id,
            source_branch_id=branch_id,
            owner=require_user(),
            target_graph_version=int(
                data.get("target_graph_version") or 0
            ),
            job_id=str(data.get("job_id") or ""),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "preview": preview})


@sft_bp.post(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/continuations"
)
def continue_research_graph_branch(instance_id: str, branch_id: str):
    data = request.get_json(silent=True) or {}
    try:
        instance = research_graphs.continue_graph_branch(
            source_instance_id=instance_id,
            source_branch_id=branch_id,
            owner=require_user(),
            target_graph_version=int(
                data.get("target_graph_version") or 0
            ),
            job_id=str(data.get("job_id") or ""),
            expected_target_hash=str(
                data.get("expected_target_hash") or ""
            ),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "instance": instance}), 201


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
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>/node"
)
def get_research_graph_node_info(instance_id: str, branch_id: str):
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
    return jsonify({"success": True, "node": packet})


@sft_bp.get(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/edges/<edge_id>"
)
def get_research_graph_edge_info(
    instance_id: str,
    branch_id: str,
    edge_id: str,
):
    """Read one available edge and its report requirements."""
    try:
        value = research_graphs.build_graph_branch_edge_info(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
            edge_id=edge_id,
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "edge": value})


@sft_bp.get(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/requirements/<requirement_id>"
)
def get_current_graph_requirement(
    instance_id: str,
    branch_id: str,
    requirement_id: str,
):
    """Lazy-load one active requirement contract, never the full catalog."""
    try:
        value = research_graphs.load_current_graph_requirement(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
            requirement_id=requirement_id,
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "requirement": value})


@sft_bp.post(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/current-report-checkpoints"
)
def append_current_report_checkpoint(instance_id: str, branch_id: str):
    """Append report-item hashes for the current node without advancing it."""
    from server.services.research_graph.current_report_checkpoint import (
        append_current_report_checkpoint as append_checkpoint,
    )

    data = request.get_json(silent=True) or {}
    try:
        checkpoint = append_checkpoint(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
            node_id=str(data.get("node_id") or ""),
            report_submission=data.get("report_submission"),
            report_artifact_ref=str(
                data.get("report_artifact_ref") or ""
            ),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "checkpoint": checkpoint}), 201


@sft_bp.get(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/cycle-objects/<object_type>/<object_id>"
)
def get_research_cycle_object(
    instance_id: str,
    branch_id: str,
    object_type: str,
    object_id: str,
):
    try:
        value = research_graphs.load_research_cycle_object(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
            object_type=object_type,
            object_id=object_id,
            trace_id=str(request.args.get("trace_id") or "") or None,
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "object": value})


@sft_bp.get(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/trial-execution-checkpoint"
)
def get_trial_execution_checkpoint(instance_id: str, branch_id: str):
    from server.services.research_graph.trial_plan.execution_checkpoint_api import (
        load_execution_checkpoint_contract,
    )

    try:
        value = load_execution_checkpoint_contract(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "execution": value})


@sft_bp.post(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/trial-execution-checkpoint/operations"
)
def operate_trial_execution_checkpoint(instance_id: str, branch_id: str):
    from server.services.research_graph.trial_plan.execution_checkpoint_api import (
        operate_execution_checkpoint,
    )

    data = request.get_json(silent=True) or {}
    try:
        value = operate_execution_checkpoint(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
            expected_latest_trace_id=str(
                data.get("expected_latest_trace_id") or ""
            ),
            expected_checkpoint_hash=str(
                data.get("expected_checkpoint_hash") or ""
            ),
            operation=str(data.get("operation") or ""),
            payload=data.get("payload"),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "result": value})


@sft_bp.post(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/trial-execution-checkpoint/recover"
)
def recover_trial_execution_checkpoint(instance_id: str, branch_id: str):
    from server.services.research_graph.trial_plan.execution_checkpoint_api import (
        recover_missing_execution_checkpoint,
    )

    data = request.get_json(silent=True) or {}
    try:
        value = recover_missing_execution_checkpoint(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
            expected_latest_trace_id=str(
                data.get("expected_latest_trace_id") or ""
            ),
            expected_execution_node=str(
                data.get("expected_execution_node") or ""
            ),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "recovery": value})


@sft_bp.get(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/trial-execution-binding"
)
def get_trial_execution_binding(instance_id: str, branch_id: str):
    from server.services.research_graph.trial_plan.execution_checkpoint_api import (
        current_action_trial_binding,
    )

    try:
        value = current_action_trial_binding(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
            run_spec_hash=str(request.args.get("run_spec_hash") or ""),
            trial_role=str(request.args.get("trial_role") or ""),
            comparison_id=str(request.args.get("comparison_id") or ""),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "trial_binding": value})


@sft_bp.post(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>/node/advance"
)
def advance_research_graph_node(instance_id: str, branch_id: str):
    data = request.get_json(silent=True) or {}
    try:
        branch = research_graphs.advance_graph_branch(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=require_user(),
            edge_id=str(data.get("edge_id") or ""),
            evidence=data.get("evidence") or {},
            acting_profile_ref=str(
                data.get("acting_profile_ref")
                or data.get("profile_ref")
                or ""
            ),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "branch": branch})

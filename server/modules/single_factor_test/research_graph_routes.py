"""Authenticated API for Research Graph runtime state.

Immutable Graph catalogs are Manager-owned under
``/api/catalog/research-graphs``.  This execution service intentionally only
hosts mutable Graph instances and their branches.
"""

from __future__ import annotations

from flask import jsonify, request

from server.auth import verify_current_user_password
from server.modules.single_factor_test import sft_bp
from server.services import research_graphs
from server.services.session_runtime import require_user


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


@sft_bp.get(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/human-gate-override"
)
def get_human_gate_override(instance_id: str, branch_id: str):
    try:
        value = research_graphs.load_human_gate_override(
            owner=require_user(),
            instance_id=instance_id,
            branch_id=branch_id,
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "override": value})


@sft_bp.put(
    "/api/research-graph-instances/<instance_id>/branches/<branch_id>"
    "/human-gate-override"
)
def put_human_gate_override(instance_id: str, branch_id: str):
    if request.headers.get("X-FactorTester-Interactive-Authorization") != (
        "macos-native-user-presence-v1"
    ):
        return jsonify({
            "success": False,
            "error": "human gate override requires native interaction",
        }), 403
    data = request.get_json(silent=True) or {}
    if type(data.get("enabled")) is not bool:
        return jsonify({
            "success": False,
            "error": "enabled must be boolean",
        }), 400
    if not verify_current_user_password(str(data.get("password") or "")):
        return jsonify({
            "success": False,
            "error": "当前登录账户密码错误",
        }), 403
    try:
        value = research_graphs.authorize_human_gate_override(
            owner=require_user(),
            instance_id=instance_id,
            branch_id=branch_id,
            expected_node=str(data.get("expected_node") or ""),
            expected_checkpoint_ref=str(
                data.get("expected_checkpoint_ref") or ""
            ),
            enabled=bool(data["enabled"]),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "override": value})

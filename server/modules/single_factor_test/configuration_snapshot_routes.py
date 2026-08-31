"""Thin HTTP routes for immutable Run Configuration Snapshots."""

from __future__ import annotations

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services import research_configuration_snapshots
from server.services.session_runtime import require_user


@sft_bp.post("/api/test-authoring/workspaces/<workspace_id>/configuration-snapshots")
def create_workspace_configuration_snapshot(workspace_id: str):
    data = request.get_json(silent=True) or {}
    try:
        source_revision = int(data.get("source_configuration_revision"))
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "source_configuration_revision is required",
        }), 400
    try:
        value = research_configuration_snapshots.create_snapshot(
            owner=require_user(),
            workspace_id=workspace_id,
            source_workspace_id=str(
                data.get("source_workspace_id") or workspace_id
            ),
            source_configuration_id=str(
                data.get("source_configuration_id") or ""
            ),
            source_configuration_revision=source_revision,
            name=str(data.get("name") or ""),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, "snapshot": value}), 201


@sft_bp.get("/api/test-authoring/workspaces/<workspace_id>/configuration-snapshots")
def list_workspace_configuration_snapshots(workspace_id: str):
    return jsonify({
        "success": True,
        "snapshots": research_configuration_snapshots.list_snapshots(
            owner=require_user(),
            workspace_id=workspace_id,
        ),
    })

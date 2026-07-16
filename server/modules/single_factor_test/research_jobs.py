"""HTTP interface for durable research workspaces and runs."""

from __future__ import annotations

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services import research_workspaces
from server.services.session_runtime import require_user


@sft_bp.post("/api/workspaces")
def create_research_workspace():
    data = request.get_json(silent=True) or {}
    kind = str(data.get("kind") or "single_factor").strip()
    if kind != "single_factor":
        return jsonify({"success": False, "error": "unsupported workspace kind"}), 400
    draft = data.get("draft")
    if draft is not None and not isinstance(draft, dict):
        return jsonify({"success": False, "error": "draft must be an object"}), 400
    workspace = research_workspaces.create_workspace(
        owner=require_user(),
        kind=kind,
        title=str(data.get("title") or "Single factor research").strip(),
        factor_family_alias=str(data.get("factor_family_alias") or "").strip(),
        draft=draft,
    )
    return jsonify({"success": True, "workspace": workspace}), 201


@sft_bp.get("/api/workspaces/<workspace_id>")
def get_research_workspace(workspace_id: str):
    workspace = research_workspaces.load_workspace(
        workspace_id=workspace_id,
        owner=require_user(),
    )
    if workspace is None:
        return jsonify({"success": False, "error": "workspace not found"}), 404
    return jsonify({"success": True, "workspace": workspace})

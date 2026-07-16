"""HTTP interface for durable research workspaces and runs."""

from __future__ import annotations

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services import research_runs, research_workspaces
from server.services.session_runtime import require_user


SUPPORTED_ANALYSES = {"backtest", "ic", "factor_evaluation", "factor_type_analysis"}


def _submit_kind(kind: str, payload: dict):
    from server.modules.single_factor_test.backtest_jobs import _submit_by_kind

    return _submit_by_kind(kind, payload)


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


@sft_bp.patch("/api/workspaces/<workspace_id>")
def update_research_workspace(workspace_id: str):
    data = request.get_json(silent=True) or {}
    draft = data.get("draft")
    if not isinstance(draft, dict):
        return jsonify({"success": False, "error": "draft must be an object"}), 400
    try:
        expected_revision = int(data.get("expected_revision"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "expected_revision is required"}), 400
    try:
        workspace = research_workspaces.update_workspace(
            workspace_id=workspace_id,
            owner=require_user(),
            expected_revision=expected_revision,
            draft=draft,
            title=str(data["title"]).strip() if "title" in data else None,
            factor_family_alias=(
                str(data["factor_family_alias"]).strip()
                if "factor_family_alias" in data else None
            ),
        )
    except research_workspaces.WorkspaceRevisionConflict as exc:
        return jsonify({
            "success": False,
            "error": str(exc),
            "current_revision": exc.current_revision,
        }), 409
    if workspace is None:
        return jsonify({"success": False, "error": "workspace not found"}), 404
    return jsonify({"success": True, "workspace": workspace})


@sft_bp.post("/api/runs")
def submit_research_run():
    data = request.get_json(silent=True) or {}
    owner = require_user()
    workspace_id = str(data.get("workspace_id") or "").strip()
    try:
        workspace_revision = int(data.get("workspace_revision"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "workspace_revision is required"}), 400
    analyses = data.get("analyses")
    if not isinstance(analyses, list) or not analyses:
        return jsonify({"success": False, "error": "analyses must be a non-empty list"}), 400
    analyses = [str(item).strip() for item in analyses]
    unsupported = sorted(set(analyses) - SUPPORTED_ANALYSES)
    if unsupported:
        return jsonify({"success": False, "error": f"unsupported analyses: {unsupported}"}), 400
    lifecycle_policy = str(data.get("lifecycle_policy") or "durable").strip()
    if lifecycle_policy not in {"durable", "observer_bound", "pause_on_detach"}:
        return jsonify({"success": False, "error": "unsupported lifecycle_policy"}), 400

    revision = research_workspaces.load_workspace_revision(
        workspace_id=workspace_id,
        owner=owner,
        revision=workspace_revision,
    )
    if revision is None:
        return jsonify({"success": False, "error": "workspace revision not found"}), 404
    run_spec = {
        "schema_version": revision["schema_version"],
        "run_spec_version": research_runs.RUN_SPEC_VERSION,
        "workspace_id": workspace_id,
        "workspace_revision": workspace_revision,
        "factor_family_alias": revision["factor_family_alias"],
        "analyses": analyses,
        "lifecycle_policy": lifecycle_policy,
        "configuration": revision["draft"],
    }
    run = research_runs.create_run(
        owner=owner,
        workspace_id=workspace_id,
        workspace_revision=workspace_revision,
        lifecycle_policy=lifecycle_policy,
        run_spec=run_spec,
    )

    jobs = []
    for kind in analyses:
        run_token = f"{run['run_id']}:{kind}"
        payload = {
            **revision["draft"],
            "run_id": run["run_id"],
            "run_token": run_token,
            "workspace_id": workspace_id,
            "workspace_revision": workspace_revision,
            "lifecycle_policy": lifecycle_policy,
            "run_spec": run_spec,
        }
        job = _submit_kind(kind, payload)
        jobs.append(job.summary())
    return jsonify({"success": True, "run_id": run["run_id"], "run": run, "jobs": jobs}), 202


@sft_bp.get("/api/runs/<run_id>")
def get_research_run(run_id: str):
    run = research_runs.load_run(run_id=run_id, owner=require_user())
    if run is None:
        return jsonify({"success": False, "error": "run not found"}), 404
    return jsonify({"success": True, "run": run})

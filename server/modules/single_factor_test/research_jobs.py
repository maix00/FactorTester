"""HTTP interface for research contexts, configurations, templates, and runs."""

from __future__ import annotations

from copy import deepcopy
import os
import uuid

from flask import jsonify, request
import settings as Settings

from server.modules.single_factor_test import sft_bp
from server.services import (
    external_factor_artifacts,
    factor_revisions,
    research_configurations,
    research_runs,
    research_workspaces,
)
from server.jobs.ipc import DaemonUnavailable, JobDaemonClient
from server.jobs.artifacts import default_user_quota_bytes
from server.jobs.entitlements import entitlement_for_owner
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.services.session_runtime import require_user
from server.services.research_graph.trial_plan.sample_identity import (
    derive_sample_identity,
)


SUPPORTED_ANALYSES = {"backtest", "ic", "factor_evaluation", "factor_type_analysis"}


class _RunRequestError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


def _prepare_research_run_request(data: dict, *, owner: str) -> dict:
    workspace_id = str(data.get("workspace_id") or "").strip()
    try:
        configuration_revision = int(data.get("configuration_revision"))
    except (TypeError, ValueError) as exc:
        raise _RunRequestError(
            "configuration_revision is required"
        ) from exc
    analyses = data.get("analyses")
    if not isinstance(analyses, list) or not analyses:
        raise _RunRequestError("analyses must be a non-empty list")
    analyses = [str(item).strip() for item in analyses]
    unsupported = sorted(set(analyses) - SUPPORTED_ANALYSES)
    if unsupported:
        raise _RunRequestError(f"unsupported analyses: {unsupported}")
    retention_mode = str(data.get("retention_mode") or "summary").strip()
    if retention_mode not in {"summary", "full"}:
        raise _RunRequestError("unsupported retention_mode")
    step_mode = bool(data.get("step_mode"))
    if step_mode and analyses != ["backtest"]:
        raise _RunRequestError(
            "step mode requires exactly one backtest analysis"
        )
    configuration = research_configurations.load_workspace_configuration(
        workspace_id=workspace_id,
        owner=owner,
    )
    if configuration is None:
        raise _RunRequestError(
            "workspace configuration not found",
            status_code=404,
        )
    if configuration["revision"] != configuration_revision:
        raise _RunRequestError(
            "configuration revision changed",
            status_code=409,
            details={"current_revision": configuration["revision"]},
        )
    missing = [
        kind for kind in analyses
        if not isinstance(
            configuration["payload"]["analyses"].get(kind),
            dict,
        )
    ]
    if missing:
        raise _RunRequestError(
            f"configuration missing analyses: {missing}"
        )
    try:
        frozen_configuration = _freeze_product_selections(
            configuration,
            owner=owner,
            analyses=analyses,
        )
        frozen_configuration = _freeze_external_factor_artifacts(
            frozen_configuration
        )
        frozen_configuration = factor_revisions.freeze_factor_revisions(
            frozen_configuration,
            owner=owner,
        )
    except ValueError as exc:
        raise _RunRequestError(str(exc)) from exc
    run_spec = {
        "run_spec_version": research_runs.RUN_SPEC_VERSION,
        "workspace_id": workspace_id,
        "configuration_id": configuration["configuration_id"],
        "configuration_revision": configuration["revision"],
        "configuration_fingerprint": configuration["fingerprint"],
        "analyses": analyses,
        "retention_mode": retention_mode,
        "step_mode": step_mode,
        "configuration": deepcopy(frozen_configuration["payload"]),
    }
    return {
        "workspace_id": workspace_id,
        "configuration": configuration,
        "frozen_configuration": frozen_configuration,
        "analyses": analyses,
        "retention_mode": retention_mode,
        "step_mode": step_mode,
        "run_spec": run_spec,
    }


def _run_request_error_response(exc: _RunRequestError):
    return jsonify({
        "success": False,
        "error": str(exc),
        **exc.details,
    }), exc.status_code


def _selection_id(group: dict) -> str:
    raw = group.get("product_path_selection")
    if isinstance(raw, dict):
        return str(
            raw.get("product_path_selection_id")
            or raw.get("selection_id")
            or raw.get("id")
            or ""
        )
    return str(group.get("product_path_selection_id") or group.get("testerId") or "")


def _freeze_product_selections(configuration: dict, *, owner: str, analyses: list[str]) -> dict:
    frozen = deepcopy(configuration)
    if "backtest" not in analyses:
        return frozen
    backtest = frozen["payload"]["analyses"].get("backtest")
    if not isinstance(backtest, dict):
        return frozen
    selections = deepcopy(backtest.get("product_selections") or {})
    if isinstance(selections, list):
        selections = {
            str(item.get("product_path_selection_id") or item.get("selection_id") or item.get("id") or ""): item
            for item in selections if isinstance(item, dict)
        }
    if not isinstance(selections, dict):
        selections = {}
    from server.modules.products.product_group_store import load_product_groups

    product_groups = {
        str(item.get("id") or ""): item
        for item in load_product_groups(owner) if isinstance(item, dict)
    }
    unresolved: set[str] = set()
    for group in backtest.get("groups") or []:
        if not isinstance(group, dict):
            continue
        selection_id = _selection_id(group)
        if not selection_id:
            continue
        raw = selections.get(selection_id)
        if not isinstance(raw, dict):
            group_selection = group.get("product_path_selection")
            raw = deepcopy(group_selection) if isinstance(group_selection, dict) else {}
        paths = raw.get("selected_paths") or raw.get("paths")
        if not isinstance(paths, list) or not paths:
            product_group = product_groups.get(selection_id)
            if product_group is None:
                unresolved.add(selection_id)
                continue
            paths = deepcopy(product_group.get("paths") or [])
            raw.update({
                "label": str(product_group.get("name") or selection_id),
                "product_group": str(product_group.get("name") or selection_id),
                "product_group_template_id": selection_id,
            })
        raw["product_path_selection_id"] = selection_id
        raw["selected_paths"] = deepcopy(paths)
        selections[selection_id] = raw
    if unresolved:
        raise ValueError(
            "configuration references product selections unavailable to owner: "
            + ", ".join(sorted(unresolved))
        )
    backtest["product_selections"] = selections
    return frozen


def _freeze_external_factor_artifacts(configuration: dict) -> dict:
    frozen = deepcopy(configuration)
    shared = frozen["payload"]["shared"]
    artifacts = external_factor_artifacts.freeze_configured_artifacts(shared)
    if artifacts:
        shared["external_factor_artifacts"] = artifacts
    return frozen


def _deployment_id() -> str:
    return str(os.environ.get("GTHT_DEPLOYMENT_ID") or "factortester-local")


def _daemon_client() -> JobDaemonClient:
    socket_path = os.environ.get(
        "GTHT_JOB_DAEMON_SOCKET",
        str(Settings.CACHE_DIR / "runtime" / f"research-jobs-{_deployment_id()}.sock"),
    )
    return JobDaemonClient(socket_path)


def _submit_kind(kind: str, payload: dict, *, run_spec_hash: str):
    process_runners = {
        "backtest": "server.modules.single_factor_test.process_runners:run_group",
        "ic": "server.modules.single_factor_test.process_runners:run_ic",
        "factor_evaluation": "server.modules.single_factor_test.process_runners:run_factor_evaluation",
        "factor_type_analysis": "server.modules.single_factor_test.process_runners:run_factor_type_analysis",
    }
    runner = process_runners.get(kind)
    if runner is None:
        raise ValueError(f"unsupported research job kind: {kind}")
    repository = JobRepository()
    job = repository.create(JobRecord(
        job_id=uuid.uuid4().hex,
        kind=kind,
        run_id=str(payload["run_id"]),
        workspace_id=str(payload["workspace_id"]),
        owner=str(payload["_owner"]),
        status=JobStatus.SUBMITTED,
        retry_of=str(payload.pop("_retry_of", "") or ""),
        attempt=max(1, int(payload.pop("_attempt", 1) or 1)),
        step_mode=bool(payload.get("step_mode")),
        retention_mode=str(payload.get("retention_mode") or "summary"),
        deployment_id=_deployment_id(),
        source_revision=str(os.environ.get("GTHT_SOURCE_REVISION") or ""),
        runner_path=runner,
        job_spec=deepcopy(payload),
        run_spec_hash=run_spec_hash,
        entitlement=entitlement_for_owner(str(payload["_owner"])),
    ))
    try:
        _daemon_client().wake()
    except DaemonUnavailable:
        pass
    return job


def _execution_payload(configuration: dict, kind: str) -> dict:
    payload = configuration["payload"]
    analysis = payload["analyses"].get(kind)
    if not isinstance(analysis, dict):
        raise ValueError(f"configuration has no {kind} analysis payload")
    shared = deepcopy(payload["shared"])
    execution = {**shared, **deepcopy(analysis)}
    families = shared.get("factor_families")
    if isinstance(families, list) and len(families) == 1 and isinstance(families[0], dict):
        execution.setdefault("factor_family_alias", str(families[0].get("alias") or ""))
    execution["research_configuration"] = {
        "configuration_id": configuration["configuration_id"],
        "revision": configuration["revision"],
        "fingerprint": configuration["fingerprint"],
    }
    return execution


@sft_bp.post("/api/workspaces")
def create_research_workspace():
    data = request.get_json(silent=True) or {}
    factor_families = data.get("factor_families") or []
    factors = data.get("factors") or []
    if not isinstance(factor_families, list) or not all(isinstance(item, dict) for item in factor_families):
        return jsonify({"success": False, "error": "factor_families must be an array of objects"}), 400
    if not isinstance(factors, list) or not all(isinstance(item, dict) for item in factors):
        return jsonify({"success": False, "error": "factors must be an array of objects"}), 400
    workspace = research_workspaces.create_workspace(
        owner=require_user(),
        title=str(data.get("title") or "Factor research").strip(),
        factor_families=factor_families,
        factors=factors,
    )
    return jsonify({"success": True, "workspace": workspace}), 201


@sft_bp.get("/api/workspaces")
def list_research_workspaces():
    return jsonify({
        "success": True,
        "workspaces": research_workspaces.list_workspaces(owner=require_user()),
    })


@sft_bp.get("/api/workspaces/<workspace_id>")
def get_research_workspace(workspace_id: str):
    workspace = research_workspaces.load_workspace(
        workspace_id=workspace_id, owner=require_user(),
    )
    if workspace is None:
        return jsonify({"success": False, "error": "workspace not found"}), 404
    return jsonify({"success": True, "workspace": workspace})


@sft_bp.get("/api/workspaces/<workspace_id>/configuration")
def get_workspace_configuration(workspace_id: str):
    value = research_configurations.load_workspace_configuration(
        workspace_id=workspace_id, owner=require_user(),
    )
    if value is None:
        return jsonify({"success": False, "error": "workspace configuration not found"}), 404
    return jsonify({"success": True, "configuration": value})


@sft_bp.post("/api/external-factor-artifacts/validate")
def validate_external_factor_artifact():
    require_user()
    data = request.get_json(silent=True) or {}
    manifest_path = str(data.get("manifest_path") or "").strip()
    if not manifest_path:
        return jsonify({"success": False, "error": "manifest_path is required"}), 400
    try:
        artifact = external_factor_artifacts.validate_and_freeze(manifest_path)
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "artifact": artifact})


@sft_bp.put("/api/workspaces/<workspace_id>/configuration")
def update_workspace_configuration(workspace_id: str):
    data = request.get_json(silent=True) or {}
    try:
        expected_revision = int(data.get("expected_revision"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "expected_revision is required"}), 400
    try:
        value = research_configurations.update_workspace_configuration(
            workspace_id=workspace_id,
            owner=require_user(),
            expected_revision=expected_revision,
            payload=data.get("payload"),
        )
    except research_configurations.ConfigurationRevisionConflict as exc:
        return jsonify({
            "success": False,
            "error": str(exc),
            "current_revision": exc.current_revision,
        }), 409
    except KeyError:
        return jsonify({"success": False, "error": "workspace configuration not found"}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "configuration": value})


@sft_bp.get("/api/configuration-templates")
def list_configuration_templates():
    return jsonify({
        "success": True,
        "templates": research_configurations.list_templates(owner=require_user()),
    })


@sft_bp.post("/api/workspaces/<workspace_id>/configuration/templates")
def save_configuration_template(workspace_id: str):
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "template name is required"}), 400
    try:
        template = research_configurations.save_template(
            workspace_id=workspace_id, owner=require_user(), name=name,
        )
    except KeyError:
        return jsonify({"success": False, "error": "workspace configuration not found"}), 404
    return jsonify({"success": True, "template": template}), 201


@sft_bp.post("/api/workspaces/<workspace_id>/configuration/load-template")
def load_configuration_template(workspace_id: str):
    data = request.get_json(silent=True) or {}
    configuration_id = str(data.get("configuration_id") or "").strip()
    try:
        expected_revision = int(data.get("expected_revision"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "expected_revision is required"}), 400
    try:
        value = research_configurations.load_template_into_workspace(
            configuration_id=configuration_id,
            workspace_id=workspace_id,
            owner=require_user(),
            expected_revision=expected_revision,
        )
    except research_configurations.ConfigurationRevisionConflict as exc:
        return jsonify({
            "success": False, "error": str(exc), "current_revision": exc.current_revision,
        }), 409
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "configuration": value})


@sft_bp.put("/api/configuration-templates/<configuration_id>")
def overwrite_configuration_template(configuration_id: str):
    workspace_id = str((request.get_json(silent=True) or {}).get("workspace_id") or "").strip()
    if not workspace_id:
        return jsonify({"success": False, "error": "workspace_id is required"}), 400
    try:
        value = research_configurations.overwrite_template_from_workspace(
            configuration_id=configuration_id,
            workspace_id=workspace_id,
            owner=require_user(),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "template": value})


@sft_bp.delete("/api/configuration-templates/<configuration_id>")
def delete_configuration_template(configuration_id: str):
    if not research_configurations.delete_template(
        configuration_id=configuration_id, owner=require_user(),
    ):
        return jsonify({"success": False, "error": "template not found"}), 404
    return jsonify({"success": True, "configuration_id": configuration_id})


@sft_bp.post("/api/runs")
def submit_research_run():
    data = request.get_json(silent=True) or {}
    owner = require_user()
    repository = JobRepository()
    quota = repository.storage_quota(
        owner=owner, default_bytes=default_user_quota_bytes()
    )
    usage = repository.storage_usage(owner=owner)
    if usage > quota:
        return jsonify({
            "success": False,
            "error": "retained result quota exceeded; delete full results before submitting",
            "code": "storage_quota_exceeded",
            "usage_bytes": usage,
            "quota_bytes": quota,
        }), 507
    try:
        prepared = _prepare_research_run_request(data, owner=owner)
    except _RunRequestError as exc:
        return _run_request_error_response(exc)
    workspace_id = prepared["workspace_id"]
    configuration = prepared["configuration"]
    frozen_configuration = prepared["frozen_configuration"]
    analyses = prepared["analyses"]
    retention_mode = prepared["retention_mode"]
    step_mode = prepared["step_mode"]
    run_spec = prepared["run_spec"]
    try:
        run = research_runs.create_run(
            owner=owner,
            workspace_id=workspace_id,
            configuration_id=configuration["configuration_id"],
            configuration_revision=configuration["revision"],
            run_spec=run_spec,
            trial_binding=data.get("trial_binding"),
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    jobs = []
    for kind in analyses:
        payload = {
            **_execution_payload(frozen_configuration, kind),
            "run_id": run["run_id"],
            "run_token": f"{run['run_id']}:{kind}",
            "workspace_id": workspace_id,
            "configuration_id": configuration["configuration_id"],
            "configuration_revision": configuration["revision"],
            "_owner": owner,
            "retention_mode": retention_mode,
            "step_mode": step_mode,
            "run_spec": run_spec,
        }
        job = _submit_kind(
            kind,
            payload,
            run_spec_hash=str(run["run_spec_hash"]),
        )
        jobs.append(job.summary())
    return jsonify({"success": True, "run_id": run["run_id"], "run": run, "jobs": jobs}), 202


@sft_bp.post("/api/runs/preview")
def preview_research_run():
    """Derive the exact frozen RunSpec identity without creating state."""
    data = request.get_json(silent=True) or {}
    owner = require_user()
    try:
        prepared = _prepare_research_run_request(data, owner=owner)
    except _RunRequestError as exc:
        return _run_request_error_response(exc)
    run_spec = prepared["run_spec"]
    configuration = prepared["configuration"]
    try:
        sample_identity = derive_sample_identity(run_spec)
    except ValueError as exc:
        sample_identity = {
            "authority": "unavailable",
            "error": str(exc),
        }
    return jsonify({
        "success": True,
        "run_spec_hash": research_runs.hash_run_spec(run_spec),
        "run_spec_version": research_runs.RUN_SPEC_VERSION,
        "configuration_id": configuration["configuration_id"],
        "configuration_revision": configuration["revision"],
        "configuration_fingerprint": configuration["fingerprint"],
        "analyses": prepared["analyses"],
        "retention_mode": prepared["retention_mode"],
        "step_mode": prepared["step_mode"],
        "sample_identity": sample_identity,
        "factor_revision_manifests": deepcopy(
            run_spec["configuration"]["shared"].get(
                "factor_revision_manifests"
            ) or []
        ),
    })


@sft_bp.get("/api/runs/<run_id>")
def get_research_run(run_id: str):
    owner = require_user()
    run = research_runs.load_run(run_id=run_id, owner=owner)
    if run is None:
        return jsonify({"success": False, "error": "run not found"}), 404
    jobs = JobRepository().list(owner=owner, run_id=run_id, limit=200)
    return jsonify({"success": True, "run": run, "jobs": [job.summary() for job in jobs]})


@sft_bp.post("/api/runs/<run_id>/clone-workspace")
def clone_research_run_workspace(run_id: str):
    owner = require_user()
    run = research_runs.load_run(run_id=run_id, owner=owner)
    if run is None:
        return jsonify({"success": False, "error": "run not found"}), 404
    payload = run["run_spec"].get("configuration")
    if not isinstance(payload, dict):
        return jsonify({"success": False, "error": "run has no restorable configuration"}), 409
    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or f"Restored run {run_id[:8]}").strip()
    workspace = research_workspaces.create_workspace(
        owner=owner, title=title, payload=deepcopy(payload),
    )
    return jsonify({
        "success": True,
        "workspace": workspace,
        "source_run_id": run_id,
        "source_run_spec_hash": run["run_spec_hash"],
    }), 201

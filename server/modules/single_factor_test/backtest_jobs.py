"""Mutation controls for durable research jobs."""

from __future__ import annotations

from copy import deepcopy
import time
import uuid

from flask import jsonify, request

from server.jobs.ipc import DaemonUnavailable
from server.jobs.artifacts import artifact_root, default_user_quota_bytes
from server.jobs.models import JobRecord
from server.jobs.states import JobStatus, TERMINAL_STATUSES
from server.modules.single_factor_test import sft_bp
from server.modules.single_factor_test.backtest_job_support import (
    job_urls,
    repository,
    require_job,
)
from server.modules.single_factor_test.research_jobs import (
    _daemon_client,
    _deployment_id,
)
from server.services.session_runtime import require_user


@sft_bp.delete("/api/jobs")
def delete_terminal_test_job_history():
    owner = require_user()
    workspace_id = str(request.args.get("workspace_id") or "").strip()
    if not workspace_id:
        return jsonify({
            "success": False,
            "error": "workspace_id is required when deleting job history",
        }), 400
    job_repository = repository()
    job_ids, artifacts = job_repository.delete_terminal_history(
        owner=owner,
        workspace_id=workspace_id,
    )
    root = artifact_root()
    deleted_files = 0
    for metadata in artifacts:
        path = (root / str(metadata["relative_path"])).resolve()
        if root in path.parents and path.is_file():
            path.unlink()
            deleted_files += 1
    return jsonify({
        "success": True,
        "workspace_id": workspace_id,
        "deleted_jobs": len(job_ids),
        "deleted_job_ids": job_ids,
        "deleted_artifacts": len(artifacts),
        "deleted_files": deleted_files,
        "usage_bytes": job_repository.storage_usage(owner=owner),
    })


@sft_bp.delete("/api/jobs/artifacts")
def delete_user_test_job_artifacts():
    owner = require_user()
    workspace_id = str(request.args.get("workspace_id") or "").strip()
    job_repository = repository()
    artifacts = job_repository.mark_owner_artifacts_deleted(
        owner=owner, workspace_id=workspace_id,
    )
    root = artifact_root()
    deleted_files = 0
    for metadata in artifacts:
        path = (root / str(metadata["relative_path"])).resolve()
        if root in path.parents and path.is_file():
            path.unlink()
            deleted_files += 1
    return jsonify({
        "success": True,
        "workspace_id": workspace_id,
        "deleted_files": deleted_files,
        "deleted_artifacts": len(artifacts),
        "usage_bytes": job_repository.storage_usage(owner=owner),
    })


@sft_bp.delete("/api/jobs/<job_id>/artifacts")
def delete_test_job_artifacts(job_id: str):
    job, error = require_job(job_id)
    if error:
        return error
    job_repository = repository()
    artifacts = job_repository.mark_artifacts_deleted(
        job_id=job.job_id,
        owner=job.owner,
    )
    root = artifact_root()
    deleted = 0
    for metadata in artifacts:
        path = (root / str(metadata["relative_path"])).resolve()
        if root in path.parents and path.is_file():
            path.unlink()
            deleted += 1
    return jsonify({"success": True, "job_id": job_id, "deleted_files": deleted})


@sft_bp.post("/api/jobs/<job_id>/cancel")
def cancel_test_job(job_id: str):
    try:
        job = repository().request_cancel(
            job_id, owner=require_user(), reason="explicit_cancel"
        )
    except KeyError:
        return jsonify({"success": False, "error": "research job not found"}), 404
    try:
        _daemon_client().cancel(job_id)
    except DaemonUnavailable:
        pass
    return jsonify({"success": True, "job_id": job_id, "status": job.status.value})


@sft_bp.post("/api/jobs/<job_id>/approve")
def approve_test_job(job_id: str):
    try:
        job = repository().approve_plan(job_id, owner=require_user())
    except KeyError:
        return jsonify({"success": False, "error": "research job not found"}), 404
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    try:
        _daemon_client().wake()
    except DaemonUnavailable:
        pass
    return jsonify({
        "success": True,
        **job.summary(),
        **job_urls(job.job_id),
    })


@sft_bp.post("/api/jobs/<job_id>/pin")
def pin_test_job(job_id: str):
    try:
        job = repository().pin(job_id, owner=require_user())
    except KeyError:
        return jsonify({"success": False, "error": "research job not found"}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    return jsonify({"success": True, **job.summary(pinned=True)})


@sft_bp.delete("/api/jobs/pin")
def unpin_test_job():
    repository().unpin(owner=require_user())
    return jsonify({"success": True})


@sft_bp.post("/api/jobs/<job_id>/retry")
def retry_test_job(job_id: str):
    old, error = require_job(job_id)
    if error:
        return error
    if old.status not in TERMINAL_STATUSES:
        return jsonify({"success": False, "error": "only terminal jobs can be retried"}), 409
    job = repository().create(JobRecord(
        job_id=uuid.uuid4().hex,
        run_id=old.run_id,
        owner=old.owner,
        workspace_id=old.workspace_id,
        kind=old.kind,
        status=JobStatus.SUBMITTED,
        retry_of=old.job_id,
        attempt=old.attempt + 1,
        step_mode=old.step_mode,
        retention_mode=old.retention_mode,
        deployment_id=_deployment_id(),
        source_revision=old.source_revision,
        runner_path=old.runner_path,
        job_spec=deepcopy(old.job_spec),
        run_spec_hash=old.run_spec_hash,
        entitlement=old.entitlement,
        created_at=time.time(),
    ))
    try:
        _daemon_client().wake()
    except DaemonUnavailable:
        pass
    return jsonify({
        "success": True,
        **job.summary(),
        **job_urls(job.job_id),
    }), 202


@sft_bp.post("/api/jobs/<job_id>/continue")
def continue_test_job(job_id: str):
    job, error = require_job(job_id)
    if error:
        return error
    if job.status is not JobStatus.PAUSED or not job.step_mode:
        return jsonify({"success": False, "error": "job is not a paused step job"}), 409
    job_repository = repository()
    quota = job_repository.storage_quota(
        owner=job.owner, default_bytes=default_user_quota_bytes()
    )
    if job_repository.storage_usage(owner=job.owner) > quota:
        return jsonify({
            "success": False,
            "error": "retained result quota exceeded; paused job cannot continue",
            "code": "storage_quota_exceeded",
        }), 507
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "continue").strip()
    if action not in {"continue", "end"}:
        return jsonify({"success": False, "error": "unsupported step action"}), 400
    command = {"action": action}
    until = str(data.get("until") or "").strip()
    if until:
        command["until"] = until
    try:
        continued = _daemon_client().continue_step(job_id, command)
    except DaemonUnavailable as exc:
        return jsonify({"success": False, "error": str(exc)}), 503
    if not continued:
        return jsonify({"success": False, "error": "paused worker is unavailable"}), 409
    current = job_repository.require(job_id, owner=job.owner)
    return jsonify({
        "success": True,
        **current.summary(),
        **job_urls(job_id),
    })

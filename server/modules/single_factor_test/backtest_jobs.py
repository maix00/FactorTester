"""Mutation controls for durable research jobs."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
import time
import uuid

from flask import jsonify, request

from server.jobs.ipc import DaemonUnavailable
from server.jobs.artifacts import artifact_root, default_user_quota_bytes
from server.jobs.artifacts import load_json_artifact
from server.jobs.report_outputs import (
    build_report_artifacts,
    normalize_output_requests,
    source_artifacts_for,
)
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


@sft_bp.post("/api/jobs/<job_id>/artifacts/generate")
def generate_test_job_artifacts(job_id: str):
    """Generate declared reports from this Job's retained source artifacts."""
    job, error = require_job(job_id)
    if error:
        return error
    if job.status not in TERMINAL_STATUSES:
        return jsonify({
            "success": False,
            "error": "artifacts can be generated only after the job is terminal",
        }), 409
    data = request.get_json(silent=True) or {}
    try:
        requested = normalize_output_requests(data.get("output_requests"))
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    if not requested:
        return jsonify({"success": False, "error": "output_requests is required"}), 400
    source_names = source_artifacts_for(requested)
    job_repository = repository()
    source: dict[str, object] = {}
    missing: list[str] = []
    for name in sorted(source_names | {"result"}):
        metadata = job_repository.load_artifact(
            job_id=job.job_id, name=name, owner=job.owner,
        )
        if metadata is None or metadata["state"] != "active":
            if name in source_names:
                missing.append(name)
            continue
        try:
            source[name] = load_json_artifact(
                str(metadata["relative_path"]),
                str(metadata["content_hash"]),
            )
        except (FileNotFoundError, RuntimeError, ValueError):
            return jsonify({
                "success": False,
                "error": f"source artifact {name!r} is unavailable or corrupt",
            }), 410
    if missing:
        return jsonify({
            "success": False,
            "error": "requested output requires source artifacts that were not retained",
            "missing_sources": missing,
        }), 409
    result = source.get("result")
    if not isinstance(result, dict):
        result = job.result_summary or {}
    reports = build_report_artifacts(
        result,
        source=source,
        requested=requested,
    )
    if not reports:
        return jsonify({
            "success": False,
            "error": "the retained result does not contain data for the requested outputs",
        }), 409
    planned: list[tuple[object, str, bytes]] = []
    for report in reports:
        receipt_name = (
            "equity_curve_receipt"
            if report.name == "equity_curve_report"
            else f"{report.name}_receipt"
        )
        receipt_raw = json.dumps(
            report.receipt, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        planned.append((report, receipt_name, receipt_raw))
    existing = {
        str(item["name"]): int(item.get("size_bytes") or 0)
        for item in job_repository.list_artifacts(job_id=job.job_id, owner=job.owner)
        if item.get("state") == "active"
    }
    replacement_names = {
        name
        for report, receipt_name, _ in planned
        for name in (report.name, receipt_name)
    }
    planned_bytes = sum(
        len(report.raw) + len(receipt_raw)
        for report, _receipt_name, receipt_raw in planned
    )
    retained_after = (
        job_repository.storage_usage(owner=job.owner)
        - sum(existing.get(name, 0) for name in replacement_names)
        + planned_bytes
    )
    quota = job_repository.storage_quota(
        owner=job.owner, default_bytes=default_user_quota_bytes()
    )
    if retained_after > quota:
        return jsonify({
            "success": False,
            "error": "generated outputs would exceed the user's artifact quota",
            "code": "storage_quota_exceeded",
            "usage_bytes": job_repository.storage_usage(owner=job.owner),
            "planned_bytes": planned_bytes,
            "quota_bytes": quota,
        }), 507
    root = artifact_root()
    generated: list[dict[str, object]] = []
    for report, receipt_name, receipt_raw in planned:
        target_dir = root / job.job_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{report.name}.{report.extension}"
        staging = target_dir / f".{target.name}.{os.getpid()}.tmp"
        staging.write_bytes(report.raw)
        staging.replace(target)
        metadata = job_repository.record_derived_artifact(
            job_id=job.job_id,
            name=report.name,
            relative_path=f"{job.job_id}/{target.name}",
            content_type=report.content_type,
            content_hash=hashlib.sha256(report.raw).hexdigest(),
            size_bytes=len(report.raw),
        )
        generated.append(metadata)
        receipt_target = target_dir / f"{receipt_name}.json"
        receipt_staging = target_dir / f".{receipt_target.name}.{os.getpid()}.tmp"
        receipt_staging.write_bytes(receipt_raw)
        receipt_staging.replace(receipt_target)
        generated.append(job_repository.record_derived_artifact(
            job_id=job.job_id,
            name=receipt_name,
            relative_path=f"{job.job_id}/{receipt_target.name}",
            content_type="application/json",
            content_hash=hashlib.sha256(receipt_raw).hexdigest(),
            size_bytes=len(receipt_raw),
        ))
    return jsonify({
        "success": True,
        "job_id": job.job_id,
        "output_requests": requested,
        "artifacts": generated,
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
        # A retry is a new JobAttempt executed by the currently deployed
        # backend.  Keep the immutable RunSpec/job_spec below, but attest the
        # code that will actually execute this attempt rather than copying the
        # previous attempt's runtime revision.
        source_revision=str(os.environ.get("GTHT_SOURCE_REVISION") or ""),
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

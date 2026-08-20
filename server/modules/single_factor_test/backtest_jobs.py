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
from server.jobs.input_artifacts import (
    load_retained_factor_sources,
    load_retained_run_dependencies,
    load_retained_strategy_sources,
    retain_factor_sources,
    retain_run_dependencies,
    retain_strategy_specs,
    retain_strategy_sources,
    strategy_spec_input_bytes,
)
from server.jobs.run_input_dependencies import dependency_input_bytes
from server.jobs.report_outputs import (
    build_report_artifacts,
    bundle_reports,
    normalize_output_requests,
    source_artifacts_for,
)
from server.jobs.models import JobRecord
from server.jobs.ports import detect_port
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
from server.services.transient_factor_sources import (
    cleanup_scope as cleanup_factor_source_scope,
    create_scope as create_factor_source_scope,
)
from server.services.transient_strategy_sources import (
    cleanup_scope as cleanup_strategy_source_scope,
    create_scope as create_strategy_source_scope,
)


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
    bundles = bundle_reports(reports)
    receipt_bytes = {
        bundle.receipt_name: json.dumps(
            bundle.receipt, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        for bundle in bundles
    }
    existing = {
        str(item["name"]): int(item.get("size_bytes") or 0)
        for item in job_repository.list_artifacts(job_id=job.job_id, owner=job.owner)
        if item.get("state") == "active"
    }
    replacement_names = {
        *(report.name for report in reports),
        *receipt_bytes,
    }
    planned_bytes = sum(
        len(report.raw) for report in reports
    ) + sum(len(raw) for raw in receipt_bytes.values())
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
    target_dir = root / job.job_id
    target_dir.mkdir(parents=True, exist_ok=True)
    generated: list[dict[str, object]] = []
    for report in reports:
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
    for receipt_name, receipt_raw in receipt_bytes.items():
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


@sft_bp.route(
    "/api/jobs/<job_id>/artifacts/<artifact_name>",
    methods=["GET", "DELETE"],
)
def delete_test_job_artifact(job_id: str, artifact_name: str):
    # Artifact bytes are always served by the Manager data plane (7997).
    # Keep direct business-port GETs indistinguishable from an absent route.
    if request.method != "DELETE":
        return jsonify({"success": False, "error": "not found"}), 404
    job, error = require_job(job_id)
    if error:
        return error
    job_repository = repository()
    current = job_repository.load_artifact(
        job_id=job.job_id, owner=job.owner, name=artifact_name,
    )
    if current is None or current.get("state") == "deleted":
        return jsonify({"success": False, "error": "artifact was not found"}), 404
    if str(current.get("artifact_role") or "output") == "input":
        return jsonify({
            "success": False,
            "error": "submitted inputs cannot be deleted individually",
        }), 409
    metadata = job_repository.mark_artifact_deleted(
        job_id=job.job_id, owner=job.owner, name=artifact_name,
    )
    if metadata is None:
        return jsonify({"success": False, "error": "artifact was not found"}), 404
    root = artifact_root()
    path = (root / str(metadata["relative_path"])).resolve()
    deleted = 0
    if root in path.parents and path.is_file():
        path.unlink()
        deleted = 1
    return jsonify({
        "success": True,
        "job_id": job_id,
        "artifact_name": artifact_name,
        "deleted_files": deleted,
    })


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
    factor_scope_id = str(
        old.job_spec.get("transient_factor_source_scope_id") or ""
    )
    strategy_scope_id = str(
        old.job_spec.get("transient_strategy_source_scope_id") or ""
    )
    data = request.get_json(silent=True) or {}
    job_spec = deepcopy(old.job_spec)
    run_spec = job_spec.get("run_spec") if isinstance(job_spec, dict) else {}
    factor_policy = (
        run_spec.get("factor_source_policy")
        if isinstance(run_spec, dict) else {}
    )
    factor_manifest = (
        list(factor_policy.get("files") or [])
        if isinstance(factor_policy, dict) else []
    )
    factor_sources: list[dict] = []
    if factor_scope_id:
        factor_sources = load_retained_factor_sources(
            repository(),
            job_id=old.job_id,
            owner=old.owner,
            manifest=factor_manifest,
        )
        if not factor_sources:
            return jsonify({
                "success": False,
                "error": (
                    "retained factor source inputs were cleared; "
                    "resubmit the Run"
                ),
                "code": "retained_job_input_unavailable",
            }), 409
    strategy_sources: list[dict] = []
    if strategy_scope_id:
        strategy_sources = load_retained_strategy_sources(
            repository(), job_id=old.job_id, owner=old.owner,
        )
        if not strategy_sources:
            return jsonify({
                "success": False,
                "error": (
                    "retained strategy source inputs were cleared; "
                    "resubmit the Run"
                ),
                "code": "retained_job_input_unavailable",
            }), 409
    strategy_specs = (
        list(job_spec.get("strategy_specs") or [])
        if old.kind == "backtest" else []
    )
    dependency_policy = (
        run_spec.get("run_input_dependency_policy")
        if isinstance(run_spec, dict) else {}
    )
    dependency_manifest = (
        list(dependency_policy.get("files") or [])
        if isinstance(dependency_policy, dict) else []
    )
    expected_dependencies = [
        item for item in dependency_manifest
        if old.kind in (item.get("analyses") or ())
    ]
    run_input_dependencies = load_retained_run_dependencies(
        repository(),
        job_id=old.job_id,
        owner=old.owner,
        manifest=expected_dependencies,
    )
    if expected_dependencies and len(run_input_dependencies) != len(
        expected_dependencies
    ):
        return jsonify({
            "success": False,
            "error": (
                "retained Run input dependencies were cleared; "
                "resubmit the Run"
            ),
            "code": "retained_job_input_unavailable",
        }), 409
    if (
        factor_sources or strategy_sources or strategy_specs
        or run_input_dependencies
    ):
        job_repository = repository()
        additional_bytes = sum(
            int(item.get("source_bytes") or 0) for item in factor_sources
        )
        additional_bytes += sum(
            len(str(item.get("source_code") or "").encode("utf-8"))
            for item in strategy_sources
        )
        additional_bytes += strategy_spec_input_bytes(strategy_specs)
        additional_bytes += dependency_input_bytes(run_input_dependencies)
        quota = job_repository.storage_quota(
            owner=old.owner, default_bytes=default_user_quota_bytes(),
        )
        if job_repository.storage_usage(owner=old.owner) + additional_bytes > quota:
            return jsonify({
                "success": False,
                "error": "retained result quota exceeded; Job cannot be retried",
                "code": "storage_quota_exceeded",
            }), 507
    if "performance_profile" in data:
        if old.kind != "backtest":
            return jsonify({
                "success": False,
                "error": "performance_profile is only available for backtest jobs",
            }), 400
        try:
            from tools.testers.backtest.engines.native.performance_profile import (
                normalize_performance_profile,
            )
            performance_profile = normalize_performance_profile(
                data.get("performance_profile")
            )
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        if performance_profile is None:
            job_spec.pop("performance_profile", None)
        else:
            job_spec["performance_profile"] = performance_profile
    if "margin_execution_profile" in data:
        if old.kind != "backtest":
            return jsonify({
                "success": False,
                "error": "margin_execution_profile is only available for backtest jobs",
            }), 400
        try:
            from tools.testers.backtest.modules.margin_budget_impl.observability import (
                normalize_margin_execution_profile,
            )
            margin_execution_profile = normalize_margin_execution_profile(
                data.get("margin_execution_profile")
            )
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        if margin_execution_profile is None:
            job_spec.pop("margin_execution_profile", None)
        else:
            job_spec["margin_execution_profile"] = margin_execution_profile
    retry_factor_scope_id = ""
    retry_strategy_scope_id = ""
    job: JobRecord | None = None
    try:
        if factor_sources:
            portable_sources = [
                item for item in factor_sources
                if item.get("canonical_family_ref")
            ]
            transient_sources = [
                item for item in factor_sources
                if not item.get("canonical_family_ref")
            ]
            retry_scope = create_factor_source_scope(
                owner=old.owner,
                entries=transient_sources,
                portable_entries=portable_sources,
            )
            retry_factor_scope_id = str(retry_scope.get("scope_id") or "")
            job_spec["transient_factor_source_scope_id"] = (
                retry_factor_scope_id
            )
        if strategy_sources:
            retry_scope = create_strategy_source_scope(
                owner=old.owner, entries=strategy_sources,
            )
            retry_strategy_scope_id = str(retry_scope.get("scope_id") or "")
            job_spec["transient_strategy_source_scope_id"] = (
                retry_strategy_scope_id
            )
        job_repository = repository()
        job = job_repository.create(JobRecord(
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
            service_port=detect_port(request.environ),
            # A retry is a new JobAttempt executed by the currently deployed
            # backend. Keep the immutable RunSpec, but attest the code that
            # will execute this attempt.
            source_revision=str(os.environ.get("GTHT_SOURCE_REVISION") or ""),
            runner_path=old.runner_path,
            job_spec=job_spec,
            run_spec_hash=old.run_spec_hash,
            entitlement=old.entitlement,
            created_at=time.time(),
        ))
        retain_factor_sources(
            job_repository,
            job_id=job.job_id,
            owner=job.owner,
            entries=factor_sources,
        )
        retain_strategy_sources(
            job_repository,
            job_id=job.job_id,
            owner=job.owner,
            entries=strategy_sources,
        )
        retain_strategy_specs(
            job_repository,
            job_id=job.job_id,
            owner=job.owner,
            entries=strategy_specs,
        )
        retain_run_dependencies(
            job_repository,
            job_id=job.job_id,
            owner=job.owner,
            entries=run_input_dependencies,
        )
        _daemon_client().wake()
    except DaemonUnavailable:
        pass
    except Exception as exc:
        if job is not None:
            try:
                job_repository.transition(
                    job.job_id,
                    JobStatus.FAILED,
                    expected=JobStatus.SUBMITTED,
                    error={
                        "code": "job_input_retention_failed",
                        "message": str(exc),
                    },
                )
            except (KeyError, RuntimeError):
                pass
        cleanup_factor_source_scope(retry_factor_scope_id)
        cleanup_strategy_source_scope(retry_strategy_scope_id)
        raise
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

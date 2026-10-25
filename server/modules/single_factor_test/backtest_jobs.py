"""Mutation controls for durable research jobs."""

from __future__ import annotations

from copy import deepcopy
import os
import time
import uuid
from pathlib import Path

from flask import jsonify, request

from server.jobs.artifacts import artifact_root, default_user_quota_bytes
from server.jobs.product_scope_inputs import retain_product_scope, product_scope_content
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


def _remove_retained_files(root: Path, rows: list[dict]) -> dict[str, int]:
    """Remove only paths below the artifact root and report filesystem reality.

    Metadata tombstones remain available for an explicit retry if unlink fails.
    `disk_removed_bytes` is logical file length, not reclaimed filesystem blocks.
    """
    resolved_root = root.resolve()
    removed = 0
    removed_bytes = 0
    failed = 0
    for metadata in rows:
        if metadata.get("active_reference"):
            continue
        try:
            path = (resolved_root / str(metadata["relative_path"])).resolve()
            if resolved_root not in path.parents:
                failed += 1
                continue
            if not path.is_file():
                continue
            path.unlink()
        except (OSError, RuntimeError):
            failed += 1
            continue
        removed += 1
        removed_bytes += int(metadata["size_bytes"])
    return {
        "deleted_files": removed,
        "disk_removed_bytes": removed_bytes,
        "failed_files": failed,
    }


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
    cleanup = str(request.args.get("cleanup") or "").strip()
    if cleanup:
        if cleanup == "retry-files":
            try:
                after = int(request.args.get("after") or 0)
                rows = repository().deleted_artifact_files(
                    owner=owner, after_rowid=after,
                )
            except ValueError as exc:
                return jsonify({"success": False, "error": str(exc)}), 400
            files = _remove_retained_files(artifact_root(), rows)
            return jsonify({
                "success": True, **files, "scanned": len(rows),
                "next_after": rows[-1]["cleanup_rowid"] if len(rows) == 1000 else None,
            })
        if cleanup != "eligible":
            return jsonify({"success": False, "error": "invalid cleanup mode"}), 400
        category = str(request.args.get("category") or "").strip()
        group = str(request.args.get("group") or "").strip()
        job_id = str(request.args.get("job_id") or "").strip()
        try:
            expected_count = int(request.args["expected_count"])
            expected_bytes = int(request.args["expected_bytes"])
            expected_token = str(request.args["expected_token"])
            job_repository = repository()
            artifacts = job_repository.mark_cleanup_outputs_deleted(
                owner=owner, category=category, group=group, job_id=job_id,
                expected_count=expected_count, expected_bytes=expected_bytes,
                expected_token=expected_token,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"success": False, "error": str(exc)}), 409
        files = _remove_retained_files(artifact_root(), artifacts)
        return jsonify({
            "success": True, "category": category or group or "all_eligible_outputs",
            "deleted_artifacts": len(artifacts),
            **files,
            "freed_bytes": sum(int(item["size_bytes"]) for item in artifacts),
            "quota_released_bytes": sum(int(item["size_bytes"]) for item in artifacts),
            "usage_bytes": job_repository.storage_usage(owner=owner),
        })
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
    return jsonify({"success": True, "job_id": job_id, "status": job.status.value})


@sft_bp.post("/api/jobs/<job_id>/approve")
def approve_test_job(job_id: str):
    try:
        owner = require_user()
        existing = repository().require(job_id, owner=owner)
        if existing.kind == "backtest":
            return jsonify({
                "success": False,
                "error": "historical backtest Jobs are read-only and cannot be approved",
                "code": "legacy_backtest_approve_unavailable",
            }), 409
        job = repository().approve_plan(job_id, owner=owner)
    except KeyError:
        return jsonify({"success": False, "error": "research job not found"}), 404
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
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
    if old.kind == "backtest":
        return jsonify({
            "success": False,
            "error": "historical backtest Jobs are read-only and cannot be retried",
            "code": "legacy_backtest_retry_unavailable",
        }), 409
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
        or run_input_dependencies or old.job_spec.get("product_selections")
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
        additional_bytes += len(product_scope_content(old.job_spec))
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
        retain_product_scope(job_repository, job_id=job.job_id, owner=job.owner,
                             job_spec=job_spec)
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
    """Step continuation belonged to the retired in-process worker pool."""
    job, error = require_job(job_id)
    if error:
        return error
    if job.kind == "backtest":
        return jsonify({
            "success": False,
            "error": "historical backtest Jobs are read-only and cannot continue",
            "code": "legacy_backtest_continue_unavailable",
        }), 409
    return jsonify({
        "success": False,
        "error": "step continuation is not supported by Celery workers",
        "code": "step_continuation_retired",
    }), 409

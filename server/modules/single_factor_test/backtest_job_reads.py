"""Read-only HTTP projections for durable research jobs."""

from __future__ import annotations

import base64
import binascii
import time
from copy import deepcopy
from pathlib import Path

import orjson
from flask import Response, jsonify, request, session, stream_with_context

from server.jobs.artifacts import default_user_quota_bytes
from server.jobs.product_scope_inputs import product_scope_snapshot
from server.jobs.input_artifacts import FACTOR_SOURCE_PREFIX, artifact_role
from server.jobs.ipc import DaemonUnavailable
from server.jobs.ports import detect_port
from server.jobs.report_outputs import (
    artifact_description,
    output_declarations,
    output_requests_for_artifacts,
)
from server.jobs.repository import JobRepository
from server.jobs.states import TERMINAL_STATUSES, JobStatus
from server.modules.single_factor_test import sft_bp
from server.modules.single_factor_test.backtest_job_support import (
    job_evidence,
    job_owner_for_gateway,
    job_research_binding,
    job_urls,
    repository,
    require_job,
    require_job_detail,
)
from server.modules.single_factor_test.research_jobs import _daemon_client
from server.services.session_runtime import require_user


def _statuses() -> set[JobStatus] | None:
    raw = str(request.args.get("status") or "").strip()
    try:
        return {
            JobStatus(item.strip())
            for item in raw.split(",")
            if item.strip()
        } or None
    except ValueError as exc:
        raise ValueError("unsupported job status") from exc


def _after_seq() -> int:
    raw = request.args.get("after")
    if raw in (None, ""):
        raw = request.headers.get("Last-Event-ID", "0")
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _port_filter() -> int | None:
    raw = request.args.get("port")
    if raw is None:
        return _server_port() or None
    if str(raw).strip().lower() in {"all", "*"}:
        return None
    port = int(raw)
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return port


def _sse(event: str, data: dict, *, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append("data: " + orjson.dumps(data).decode())
    return "\n".join(lines) + "\n\n"


def _server_port() -> int:
    """Expose the listening port when the app is behind a simple launcher."""
    return detect_port(request.environ)


def _global_job_cursor() -> tuple[float | None, str]:
    """Decode the stable cursor used by the global job projection."""
    raw = str(request.args.get("cursor") or "").strip()
    if not raw:
        return None, ""
    try:
        decoded = orjson.loads(
            base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        )
        updated_at = float(decoded["updated_at"])
        job_id = str(decoded["job_id"] or "")
    except (
        binascii.Error, KeyError, TypeError, ValueError,
        orjson.JSONDecodeError,
    ) as exc:
        raise ValueError("cursor 无效") from exc
    if not job_id:
        raise ValueError("cursor 无效")
    return updated_at, job_id


def _next_global_job_cursor(
    jobs: list[dict[str, object]], has_more: bool,
) -> str | None:
    if not has_more or not jobs:
        return None
    last = jobs[-1]
    return base64.urlsafe_b64encode(orjson.dumps({
        "updated_at": last["updated_at"],
        "job_id": last["job_id"],
    })).rstrip(b"=").decode()


def _subordinate_users(owner: str) -> list[dict[str, str]]:
    """Return the current user's direct account descendants."""
    from tools.data.account_manage import (
        direct_subordinate_accounts_for,
    )

    result = []
    for account in direct_subordinate_accounts_for(owner):
        username = str(account.get("username") or "")
        if not username:
            continue
        alias = str(account.get("alias") or "").strip()
        result.append({
            "username": username,
            "alias": alias,
            "title": alias or username,
            "organization_name": str(account.get("organization_name") or ""),
            "role": str(account.get("role") or "user"),
        })
    return sorted(result, key=lambda item: (item["title"].lower(), item["username"]))


def _page_summary(total: int, page: int, limit: int) -> dict[str, int]:
    page_size = max(1, int(limit))
    total_pages = max(1, (max(0, int(total)) + page_size - 1) // page_size)
    return {
        "page": max(1, int(page)),
        "page_size": page_size,
        "total": max(0, int(total)),
        "total_pages": total_pages,
    }


def _server_context(job) -> dict[str, object]:
    run_spec = job.job_spec.get("run_spec") if isinstance(job.job_spec, dict) else None
    binding = run_spec.get("research_binding") if isinstance(run_spec, dict) else None
    submission = job.job_spec.get("submission_context")
    submission = submission if isinstance(submission, dict) else {}
    profile_ref = (
        job.job_spec.get("acting_profile_ref")
        or submission.get("acting_profile_ref")
        or ""
    )
    profile = (
        job.job_spec.get("acting_profile_name")
        or submission.get("acting_profile_name")
        or job.job_spec.get("profile")
        or job.job_spec.get("profile_name")
        or job.job_spec.get("profile_ref")
        or job.job_spec.get("profile_id")
        or submission.get("profile")
        or submission.get("profile_name")
        or submission.get("profile_id")
        or profile_ref
        or (binding or {}).get("profile_ref")
    )
    if isinstance(profile, str) and profile.startswith("profile:"):
        profile = profile.split(":", 1)[1]
    return {
        "port": job.service_port or _server_port(),
        "profile": str(profile or ""),
        "profile_ref": str(profile_ref or ""),
        "profile_name": str(
            job.job_spec.get("acting_profile_name")
            or submission.get("acting_profile_name")
            or ""
        ),
        "owner": str(job.owner or ""),
    }


def _submission_context(job) -> dict[str, object]:
    value = job.job_spec.get("submission_context")
    if not isinstance(value, dict):
        value = {}
    return {
        "channel": str(value.get("channel") or "unknown"),
        "client": str(value.get("client") or "unknown"),
        "user_agent": str(value.get("user_agent") or "")[:200],
        "trigger": str(value.get("trigger") or ""),
        "api_route": str(value.get("api_route") or ""),
        "acting_profile_ref": str(
            job.job_spec.get("acting_profile_ref")
            or value.get("acting_profile_ref")
            or ""
        ),
        "acting_profile_name": str(
            job.job_spec.get("acting_profile_name")
            or value.get("acting_profile_name")
            or ""
        ),
    }


_PRIVATE_JOB_KEYS = frozenset({
    "run_token", "_owner", "password", "secret", "api_key",
    "source_code", "transient_factor_source_scope_id",
    "transient_strategy_source_scope_id",
})


def _public_value(value):
    """Recursively remove credentials and executable source from projections."""
    if isinstance(value, dict):
        return {
            str(key): _public_value(item)
            for key, item in value.items()
            if str(key) not in _PRIVATE_JOB_KEYS
        }
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    if isinstance(value, tuple):
        return [_public_value(item) for item in value]
    return value


def _public_job_spec(job) -> dict[str, object]:
    """Return the stored spec without credentials/internal owner markers."""
    return _public_value(job.job_spec) if isinstance(job.job_spec, dict) else {}


def _compatibility(job) -> dict[str, object]:
    run_spec = job.job_spec.get("run_spec") if isinstance(job.job_spec, dict) else None
    version = run_spec.get("run_spec_version") if isinstance(run_spec, dict) else None
    missing = [
        field for field, value in (
            ("job_spec", job.job_spec),
            ("execution_plan", job.execution_plan),
            ("result_summary", job.result_summary),
        ) if value is None or value == {}
    ]
    return {
        "source": "research_jobs",
        "stored_format": str(version or "legacy-read-through"),
        "migration": "read-through",
        "original_fields_available": True,
        "missing_fields": missing,
        "note": "历史任务保留原始 job_spec；当前接口只对外隐藏凭证字段并补齐兼容投影。",
    }


def _list_research_binding(
    job_repository, job, owner: str,
) -> dict[str, object]:
    detail = job_repository.load_detail(job.job_id, owner=owner)
    return dict(detail.get("report_binding") or {}) if detail else {}


def _artifact_manifest(
    job,
    *,
    include_inputs: bool = True,
) -> list[dict[str, object]]:
    """Return the stable artifact metadata used by every job-detail client."""
    artifacts = [
        {
            **item,
            "role": artifact_role(item),
            "description": (
                str(item.get("title_zh") or "")
                or artifact_description(str(item.get("name") or ""))
            ),
            "file_name": _artifact_file_name(item),
        }
        for item in repository().list_artifacts(
            job_id=job.job_id,
            owner=job.owner,
        )
    ]
    if include_inputs:
        return artifacts
    return [item for item in artifacts if item.get("role") != "input"]


def _artifact_file_name(metadata: dict[str, object], path: Path | None = None) -> str:
    """Return a safe downloadable name with an extension for old artifacts."""
    raw_name = Path(str(metadata.get("name") or "artifact")).name or "artifact"
    stored_file_name = Path(str(metadata.get("file_name") or "")).name
    if stored_file_name:
        return stored_file_name
    if raw_name.startswith(FACTOR_SOURCE_PREFIX):
        return f"{raw_name.removeprefix(FACTOR_SOURCE_PREFIX)}.py"
    if Path(raw_name).suffix:
        return raw_name
    path_suffix = (path or Path(str(metadata.get("relative_path") or ""))).suffix
    if path_suffix:
        return f"{raw_name}{path_suffix}"
    mime = str(metadata.get("content_type") or "").split(";", 1)[0].lower()
    extension = {
        "application/json": ".json",
        "text/csv": ".csv",
        "text/plain": ".txt",
        "image/svg+xml": ".svg",
        "image/png": ".png",
        "application/pdf": ".pdf",
        "application/zip": ".zip",
        "application/x-parquet": ".parquet",
    }.get(mime, "")
    return f"{raw_name}{extension}" if extension else raw_name


def _artifact_storage_summary(
    artifacts: list[dict[str, object]],
) -> dict[str, int]:
    """Summarize active submitted inputs and generated outputs for one Job."""
    result = {
        "artifact_count": 0,
        "artifact_bytes": 0,
        "output_artifact_count": 0,
        "output_artifact_bytes": 0,
        "input_artifact_count": 0,
        "input_artifact_bytes": 0,
    }
    for item in artifacts:
        if str(item.get("state") or "") != "active":
            continue
        size = max(0, int(item.get("size_bytes") or 0))
        role = artifact_role(item)
        result["artifact_count"] += 1
        result["artifact_bytes"] += size
        prefix = "input" if role == "input" else "output"
        result[f"{prefix}_artifact_count"] += 1
        result[f"{prefix}_artifact_bytes"] += size
    return result


def _task_detail(
    detail: dict,
    *,
    declarations: list[dict[str, object]],
    evidence: dict | None,
    artifacts: list[dict[str, object]],
    generated_output_requests: list[str],
) -> dict[str, object]:
    """Canonical structured task detail shared by CLI and desktop clients.

    The historical top-level fields remain in the response for compatibility,
    but new clients should consume this object instead of joining several
    endpoints and guessing research/caller relationships locally.
    """
    job = detail["job"]
    report_binding = detail.get("report_binding") or {}
    binding = report_binding
    caller = _submission_context(job)
    run_spec = job.job_spec.get("run_spec") if isinstance(job.job_spec, dict) else None
    configuration = (
        _public_value(run_spec.get("configuration"))
        if isinstance(run_spec, dict) else None
    )
    summary = job.summary(pinned=detail["pinned"])
    storage = _artifact_storage_summary(artifacts)
    visible_inputs = [
        item for item in artifacts if item.get("role") == "input"
    ]
    dependency_policy = (
        _public_value(run_spec.get("run_input_dependency_policy"))
        if visible_inputs and isinstance(run_spec, dict) else None
    )
    return {
        "job": {
            **summary,
            "server_context": _server_context(job),
        },
        "factor_source_policy": summary.get("factor_source_policy"),
        "strategy_specs": summary.get("strategy_specs") or [],
        "strategy_source_policy": summary.get("strategy_source_policy"),
        "run_input_dependency_policy": dependency_policy,
        "research_binding": binding,
        "report_binding": report_binding,
        "caller": caller,
        "configuration": configuration,
        "product_scope_snapshot": product_scope_snapshot(job.job_spec),
        "output_requests": list(job.job_spec.get("output_requests") or ()),
        "generated_output_requests": generated_output_requests,
        "results": {
            "status": job.status.value,
            "summary": job.result_summary,
            "error": job.error,
            "evidence": evidence,
        },
        "output_declarations": declarations,
        "input_artifacts": visible_inputs,
        "artifacts": artifacts,
        "storage": storage,
    }


@sft_bp.get("/api/jobs")
def list_test_jobs():
    try:
        statuses = _statuses()
        gateway = bool(
            session.get("manager_gateway_public_jobs")
            or session.get("manager_gateway")
        )
        service_port = None if gateway else _port_filter()
        limit = min(100, max(1, int(request.args.get("limit", "20") or 20)))
        page = max(1, int(request.args.get("page", "1") or 1))
        object_filter = {
            "object_kind": str(request.args.get("object_kind") or "").strip(),
            "object_ref": str(request.args.get("object_ref") or "").strip(),
            "object_owner_ref": str(
                request.args.get("object_owner_ref") or ""
            ).strip(),
            "object_alias": str(request.args.get("object_alias") or "").strip(),
        }
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    scope = str(request.args.get("scope") or "").strip().lower()
    public = bool(session.get("manager_gateway_public_jobs"))
    visitor_gateway = bool(session.get("manager_gateway_visitor_id"))
    if not scope:
        scope = "server" if public else "mine"
    if public and scope != "server" and not (
        visitor_gateway and scope == "mine"
    ):
        return jsonify({
            "success": True,
            "scope": scope,
            "requires_login": True,
            "jobs": [],
            **_page_summary(0, page, min(limit, 20)),
        })

    if scope == "server":
        # Anonymous requests and ordinary accounts receive the same bounded
        # public projection.  A super admin may page through the full store.
        current_owner = None if public else require_user()
        if current_owner:
            from tools.data.account_manage import (
                get_account,
                is_super_admin_account,
            )
            full_server_view = is_super_admin_account(get_account(current_owner))
        else:
            full_server_view = False
        effective_limit = limit if full_server_view else min(limit, 20)
        if full_server_view:
            try:
                before_updated_at, before_job_id = _global_job_cursor()
            except ValueError as exc:
                return jsonify({"success": False, "error": str(exc)}), 400
        else:
            # The public projection is a fixed newest-20 snapshot; cursors
            # are intentionally ignored instead of exposing another page.
            before_updated_at, before_job_id = None, ""
        public_rows, has_more = JobRepository().list_global_summaries(
            limit=effective_limit,
            before_updated_at=before_updated_at,
            before_job_id=before_job_id,
            include_artifacts=True,
            **object_filter,
        )
        total = JobRepository().count_global_summaries(**object_filter)
        jobs = []
        for summary in public_rows:
            record = JobRepository().load(str(summary["job_id"]))
            if record is None:
                continue
            identity = record.summary()
            jobs.append({
                **summary,
                "task_name": identity.get("task_name") or "",
                "acting_profile_ref": identity.get("acting_profile_ref") or "",
                "acting_profile_name": identity.get("acting_profile_name") or "",
                "object_subjects": identity.get("object_subjects") or [],
                "port": record.service_port or _server_port(),
                "server_context": _server_context(record),
                "artifact_count": int(summary.get("artifact_count") or 0),
                "artifact_bytes": int(summary.get("artifact_bytes") or 0),
                "output_artifact_count": int(
                    summary.get("output_artifact_count") or 0
                ),
                "output_artifact_bytes": int(
                    summary.get("output_artifact_bytes") or 0
                ),
                "input_artifact_count": int(
                    summary.get("input_artifact_count") or 0
                ),
                "input_artifact_bytes": int(
                    summary.get("input_artifact_bytes") or 0
                ),
                "public_artifacts": False,
                **job_urls(record.job_id),
            })
        if not full_server_view:
            # Public and ordinary-account views are deliberately a fixed
            # newest-20 snapshot.  They must not expose a cursor that lets a
            # caller page through the remainder of the server history.
            jobs = jobs[:20]
            public_total = len(jobs)
            public_has_more = False
            public_cursor = None
        else:
            public_total = total
            public_has_more = has_more
            public_cursor = _next_global_job_cursor(jobs, has_more)
        return jsonify({
            "success": True,
            "public": not full_server_view,
            "scope": "server",
            "jobs": jobs,
            **_page_summary(public_total, 1 if not full_server_view else page, effective_limit),
            "has_more": public_has_more,
            "next_cursor": public_cursor,
        })
    owner = job_owner_for_gateway()
    if not owner:
        return jsonify({
            "success": False,
            "error": "visitor job owner is unavailable",
        }), 401
    visible_owners: list[str] | None = None
    if scope == "subordinates":
        users = _subordinate_users(owner)
        requested_user = str(
            request.args.get("username")
            or request.args.get("user")
            or ""
        ).strip()
        base = {
            "success": True,
            "scope": "subordinates",
            "users": users,
        }
        if not requested_user:
            return jsonify({
                **base,
                "selection_required": True,
                "jobs": [],
                **_page_summary(0, page, limit),
                "has_more": False,
                "next_cursor": None,
            })
        if requested_user not in {item["username"] for item in users}:
            return jsonify({"success": False, "error": "无权查看该下级用户任务"}), 403
        job_owner = requested_user
    elif scope == "visible":
        visible_owners = [
            owner,
            *[item["username"] for item in _subordinate_users(owner)],
        ]
        job_owner = owner
    elif scope == "mine":
        job_owner = owner
    else:
        return jsonify({"success": False, "error": "不支持的任务范围"}), 400
    job_repository = repository()
    rows = job_repository.list_with_metadata(
        owner=job_owner,
        kind=str(request.args.get("kind") or "").strip(),
        workspace_id=str(
            request.args.get("workspace_id") or ""
        ).strip(),
        run_id=str(request.args.get("run_id") or "").strip(),
        statuses=statuses,
        service_port=service_port,
        owners=visible_owners,
        **object_filter,
        limit=limit,
        offset=(page - 1) * limit,
    )
    total = job_repository.count_with_metadata(
        owner=job_owner,
        kind=str(request.args.get("kind") or "").strip(),
        workspace_id=str(request.args.get("workspace_id") or "").strip(),
        run_id=str(request.args.get("run_id") or "").strip(),
        statuses=statuses,
        service_port=service_port,
        owners=visible_owners,
        **object_filter,
    )
    return jsonify({
        "success": True,
        "scope": scope,
        "jobs": [
            {
                **item["job"].summary(pinned=item["pinned"]),
                "artifact_count": item["artifact_count"],
                "artifact_bytes": item["artifact_bytes"],
                "output_artifact_count": item["output_artifact_count"],
                "output_artifact_bytes": item["output_artifact_bytes"],
                "input_artifact_count": item["input_artifact_count"],
                "input_artifact_bytes": item["input_artifact_bytes"],
                "updated_at": item["effective_updated_at"],
                "parent_updated_at": item["job"].updated_at,
                "supplemental_count": item["supplemental_count"],
                "supplemental_active_count": item["supplemental_active_count"],
                "supplemental_failed_count": item["supplemental_failed_count"],
                "supplemental_updated_at": item["supplemental_updated_at"],
                "server_context": _server_context(item["job"]),
                "research_binding": _list_research_binding(
                    job_repository, item["job"], item["job"].owner,
                ),
                **job_urls(item["job"].job_id),
            }
            for item in rows
        ],
        **_page_summary(total, page, limit),
        "has_more": len(rows) >= limit and len(rows) < total,
        "next_cursor": None,
    })


@sft_bp.get("/api/jobs/<job_id>")
def get_test_job(job_id: str):
    detail, error = require_job_detail(job_id)
    if error:
        return error
    job = detail["job"]
    artifacts = _artifact_manifest(
        job,
        include_inputs=not bool(session.get("manager_gateway_public_jobs")),
    )
    generated_output_requests = output_requests_for_artifacts(
        item.get("name", "")
        for item in artifacts
        if item.get("state") == "active"
    )
    declaration_requests = list(dict.fromkeys([
        *list(job.job_spec.get("output_requests") or ()),
        *generated_output_requests,
    ]))
    try:
        declarations = output_declarations(declaration_requests)
    except Exception as exc:
        declarations = []
        declaration_error = f"{type(exc).__name__}: {exc}"
    else:
        declaration_error = None
    try:
        evidence = job_evidence(detail)
    except Exception as exc:
        evidence = None
        evidence_error = f"{type(exc).__name__}: {exc}"
    else:
        evidence_error = None
    task_detail = _task_detail(
        detail,
        declarations=declarations,
        evidence=evidence,
        artifacts=artifacts,
        generated_output_requests=generated_output_requests,
    )
    payload = {
        "success": True,
        **job.summary(pinned=detail["pinned"]),
        "execution_plan": _public_value(job.execution_plan),
        "job_spec": _public_job_spec(job),
        "compatibility": _compatibility(job),
        "result_summary": job.result_summary,
        "error": job.error,
        "run_spec_hash": job.run_spec_hash,
        "output_requests": list(job.job_spec.get("output_requests") or ()),
        "output_declarations": declarations,
        "configuration": (
            _public_value(job.job_spec.get("run_spec", {}).get("configuration"))
            if isinstance(job.job_spec.get("run_spec"), dict)
            else None
        ),
        "server_context": _server_context(job),
        "research_binding": (
            detail.get("report_binding") or {}
        ),
        "report_binding": detail.get("report_binding") or {},
        "submission_context": _submission_context(job),
        "caller": task_detail["caller"],
        "task_detail": task_detail,
        "evidence": evidence,
        **job_urls(job.job_id),
    }
    warnings = [item for item in (declaration_error, evidence_error) if item]
    if warnings:
        payload["detail_warning"] = "；".join(warnings)
    return jsonify(payload)


@sft_bp.get("/api/jobs/<job_id>/stream")
def stream_test_job(job_id: str):
    job, error = require_job(job_id)
    if error:
        return error
    owner = require_user()
    after = _after_seq()

    @stream_with_context
    def generate():
        nonlocal after
        while True:
            current = repository().load(job_id, owner=owner)
            if current is None:
                yield _sse(
                    "error",
                    {"error": "research job not found"},
                )
                return
            try:
                snapshot = _daemon_client().events(
                    job_id,
                    after=after,
                    timeout=2.0,
                )
            except DaemonUnavailable:
                yield _sse("reset", {
                    "reason": "daemon_unavailable",
                    "status": current.status.value,
                    "result_summary": current.result_summary,
                    "error": current.error,
                })
                return
            if not snapshot.get("known", True):
                yield _sse("reset", {
                    "reason": "event_state_unavailable",
                    "status": current.status.value,
                    "latest_progress": None,
                    "manifest": None,
                    "result_summary": current.result_summary,
                    "error": current.error,
                })
                if current.status in TERMINAL_STATUSES or after > 0:
                    return
            gap = snapshot.get("gap")
            if gap:
                yield _sse("reset", {
                    "reason": "event_gap",
                    "gap": gap,
                    "status": current.status.value,
                    "latest_progress": snapshot.get("latest_progress"),
                    "manifest": snapshot.get("manifest"),
                })
            for event in snapshot.get("events") or []:
                after = max(after, int(event["seq"]))
                yield _sse(
                    event["event"],
                    event["data"],
                    event_id=after,
                )
            if (
                current.status in TERMINAL_STATUSES
                or snapshot.get("closed")
            ):
                return
            if not snapshot.get("events"):
                yield _sse("heartbeat", {
                    "status": current.status.value,
                    "latest_progress": snapshot.get("latest_progress"),
                    "server_time": time.time(),
                })

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@sft_bp.get("/api/jobs/<job_id>/result")
def get_test_job_result(job_id: str):
    detail, error = require_job_detail(job_id)
    if error:
        return error
    job = detail["job"]
    try:
        evidence = job_evidence(detail)
    except Exception as exc:
        evidence = None
        evidence_warning = f"{type(exc).__name__}: {exc}"
    else:
        evidence_warning = None
    base = {
        "job_id": job.job_id,
        "kind": job.kind,
        "run_id": job.run_id,
        "status": job.status.value,
        "evidence": evidence,
        "compatibility": _compatibility(job),
    }
    if evidence_warning:
        base["detail_warning"] = evidence_warning
    if job.status is JobStatus.SUCCEEDED:
        result = deepcopy(job.result_summary)
        if job.kind == "ic" and isinstance(result, dict):
            provenance = result.get("provenance")
            if isinstance(provenance, dict):
                provenance["run_spec_hash"] = str(job.run_spec_hash or "")
        return jsonify({
            "success": True,
            **base,
            "result": result,
        })
    if job.status is JobStatus.PAUSED:
        return jsonify({"success": True, **base, "paused": True})
    if job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
        return jsonify({
            "success": False,
            **base,
            "error": job.error,
            "cancel_reason": job.cancel_reason,
        })
    return jsonify({
        "success": False,
        **base,
        "error": "job is not complete",
    }), 202


@sft_bp.get("/api/jobs/storage")
def get_job_storage():
    owner = job_owner_for_gateway()
    if not owner:
        return jsonify({
            "success": False,
            "error": "visitor job owner is unavailable",
        }), 401
    job_repository = repository()
    breakdown = job_repository.storage_breakdown(owner=owner)
    usage = breakdown["artifact_bytes"]
    quota = job_repository.storage_quota(
        owner=owner,
        default_bytes=default_user_quota_bytes(),
    )
    return jsonify({
        "success": True,
        "usage_bytes": usage,
        "quota_bytes": quota,
        "over_quota": usage > quota,
        **breakdown,
    })


@sft_bp.get("/api/jobs/<job_id>/artifacts")
def list_test_job_artifacts(job_id: str):
    job, error = require_job(job_id)
    if error:
        return error
    artifacts = repository().list_artifacts(
        job_id=job.job_id,
        owner=job.owner,
    )
    if session.get("manager_gateway_public_jobs"):
        artifacts = [
            item for item in artifacts if artifact_role(item) != "input"
        ]
    return jsonify({
        "success": True,
        "job_id": job_id,
        "artifacts": [
            {
                **item,
                "role": artifact_role(item),
                "description": (
                    str(item.get("title_zh") or "")
                    or artifact_description(str(item.get("name") or ""))
                ),
                "file_name": _artifact_file_name(item),
            }
            for item in artifacts
        ],
    })

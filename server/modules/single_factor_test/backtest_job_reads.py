"""Read-only HTTP projections for durable research jobs."""

from __future__ import annotations

import os

import base64
import binascii
import time
from copy import deepcopy
from pathlib import Path

import orjson
from flask import Response, jsonify, make_response, request, session, stream_with_context

from server.jobs.artifacts import default_user_quota_bytes
from server.jobs.product_scope_inputs import product_scope_snapshot
from server.jobs.input_artifacts import FACTOR_SOURCE_PREFIX, artifact_role
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
        "progress": detail.get("progress"),
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
        "progress": detail.get("progress"),
        "evidence": evidence,
        **job_urls(job.job_id),
    }
    warnings = [item for item in (declaration_error, evidence_error) if item]
    if warnings:
        payload["detail_warning"] = "；".join(warnings)
    return jsonify(payload)


def _can_read_report(actor: str, document: dict, report_ref: str) -> bool:
    if document.get("owner") == actor:
        return True
    from tools.data.account_manage import get_account, is_super_admin_account

    if is_super_admin_account(get_account(actor)):
        return True
    import os
    from server.permissions.entries import PermissionStore

    db = os.environ.get("TRADERESEARCH_PERMISSIONS_DB", "") or os.environ.get(
        "FACTORTESTER_PERMISSIONS_DB", ""
    )
    if not db:
        return False
    from server.permissions.subjects import subjects_for_user

    subjects = subjects_for_user(actor)
    store = PermissionStore(db)
    return any(store.allows(
        subject=subject, resource_type="report",
        resource_ref=report_ref, action="read",
    ) for subject in subjects)


@sft_bp.get("/api/auth/oidc/start")
def oidc_start():
    """Begin the Keycloak authorization-code flow for browser clients."""
    import secrets
    from flask import session, url_for
    from server import branding
    from server.identity.auth_mode import keycloak_enabled
    from server.identity.keycloak import oidc_authorization_url

    if not keycloak_enabled():
        return jsonify({"success": False, "error": "Keycloak login is disabled"}), 503
    base_url = branding.env("KEYCLOAK_URL")
    realm = branding.env("KEYCLOAK_REALM")
    client_id = branding.env("KEYCLOAK_CLIENT_ID")
    if not (base_url and realm and client_id):
        return jsonify({"success": False, "error": "OIDC is not configured"}), 503
    state = secrets.token_urlsafe(24)
    session["oidc_state"] = state
    redirect_uri = url_for("sft.oidc_callback", _external=True)
    return jsonify({"success": True, "authorization_url": oidc_authorization_url(
        base_url=base_url, realm=realm, client_id=client_id,
        redirect_uri=redirect_uri, state=state,
    )})


@sft_bp.get("/api/auth/oidc/logout")
def oidc_logout():
    from flask import redirect, session, url_for
    from server import branding
    from server.identity.auth_mode import keycloak_enabled
    from server.identity.keycloak import oidc_logout_url

    session.clear()
    if not keycloak_enabled():
        return redirect("/")
    url = oidc_logout_url(
        base_url=branding.env("KEYCLOAK_URL"), realm=branding.env("KEYCLOAK_REALM"),
        client_id=branding.env("KEYCLOAK_CLIENT_ID"),
        post_logout_redirect_uri=url_for("sft.oidc_logout", _external=True),
    )
    return redirect(url)


@sft_bp.get("/api/auth/oidc/callback")
def oidc_callback():
    """Complete the authorization-code flow and establish the session."""
    from flask import redirect, request, session
    from server import branding
    from server.identity.auth_mode import keycloak_enabled
    from server.identity.keycloak import OIDCClient, oidc_userinfo

    if not keycloak_enabled():
        return jsonify({"success": False, "error": "Keycloak login is disabled"}), 503
    code = str(request.args.get("code") or "")
    state = str(request.args.get("state") or "")
    expected = str(session.pop("oidc_state", "") or "")
    if not code or not state or state != expected:
        return jsonify({"success": False, "error": "invalid OIDC state"}), 400
    redirect_uri = request.url_root.rstrip("/") + "/api/auth/oidc/callback"
    client = OIDCClient(
        branding.env("KEYCLOAK_URL"), branding.env("KEYCLOAK_REALM"),
        branding.env("KEYCLOAK_CLIENT_ID"),
        client_secret=branding.env("KEYCLOAK_CLIENT_SECRET"),
    )
    tokens = client.exchange_code(code, redirect_uri)
    try:
        profile = oidc_userinfo(
            base_url=branding.env("KEYCLOAK_URL"), realm=branding.env("KEYCLOAK_REALM"),
            access_token=str(tokens.get("access_token") or ""),
        )
    except Exception:
        from server.identity.keycloak import jwt_claims

        profile = jwt_claims(
            str(tokens.get("id_token") or tokens.get("access_token") or "")
        )
    username = str(profile.get("preferred_username") or profile.get("sub") or "")
    if not username:
        return jsonify({"success": False, "error": "OIDC profile has no username"}), 401
    # Keycloak lowercases usernames; retain the legacy spelling when available.
    try:
        from server.identity.keycloak import KeycloakAdminAdapter
        identity = KeycloakAdminAdapter(
            branding.env("KEYCLOAK_URL"), branding.env("KEYCLOAK_REALM"),
            client_id=branding.env("KEYCLOAK_ADMIN_CLIENT_ID", "admin-cli"),
            client_secret=branding.env("KEYCLOAK_ADMIN_CLIENT_SECRET", ""),
        ).user(username)
        legacy = (getattr(identity, "attributes", {}) or {}).get("legacy_username") if identity else None
        if legacy:
            username = legacy[0] if isinstance(legacy, (tuple, list)) else str(legacy)
    except Exception:
        pass
    role = "user"
    try:
        from tools.data.account_manage import get_account
        account = get_account(username)
        if account is not None:
            role = str(account.role or "user")
    except Exception:
        pass
    session["username"] = username
    session["role"] = role
    return redirect("/")


@sft_bp.post("/api/objects")
def put_versioned_object():
    actor = require_user()
    import os
    from flask import request
    from server.jobs.storage.couchdb_objects import VersionedObject, put_object
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    body = request.get_json(silent=True) or {}
    kind = str(body.get("kind") or "")
    ref = str(body.get("ref") or "")
    payload = body.get("payload")
    if kind not in {"factor_version", "strategy_version"}:
        return jsonify({"success": False, "error": "unsupported object kind"}), 400
    if not ref or not isinstance(payload, dict):
        return jsonify({"success": False, "error": "ref and payload are required"}), 400
    expected = "factor:v2:" if kind == "factor_version" else "strategy:"
    if not ref.startswith(expected):
        return jsonify({"success": False, "error": "object ref does not match kind"}), 400
    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "object store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        put_object(store, VersionedObject(
            ref=ref, kind=kind, owner=actor, payload=payload,
            links=dict(body.get("links") or {}),
        ))
    except Exception:
        return jsonify({"success": False, "error": "object already exists or write failed"}), 409
    try:
        from server.jobs.dispatch.audit import append_audit
        import settings as Settings

        append_audit(Settings.CACHE_DB_PATH, action="object_write", actor=actor,
                     job_id=ref, detail=kind)
    except Exception:
        pass
    return jsonify({"success": True, "ref": ref, "owner": actor})


@sft_bp.get("/api/objects/<path:object_ref>")
def get_versioned_object(object_ref: str):
    actor = require_user()
    import os
    from server.jobs.storage.couchdb_objects import get_object
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "object store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = get_object(store, object_ref)
    except Exception:
        return jsonify({"success": False, "error": "object not found"}), 404
    if document.get("owner") != actor:
        from server.permissions.subjects import subjects_for_user
        from server.permissions.entries import PermissionStore

        db = os.environ.get("TRADERESEARCH_PERMISSIONS_DB", "") or os.environ.get("FACTORTESTER_PERMISSIONS_DB", "")
        if not (db and any(PermissionStore(db).allows(
            subject=subject, resource_type=str(document.get("kind") or ""),
            resource_ref=object_ref, action="read",
        ) for subject in subjects_for_user(actor))):
            return jsonify({"success": False, "error": "object access denied"}), 403
    return jsonify({"success": True, "document": document})


@sft_bp.get("/api/reports/<report_ref>/conflicts")
def get_report_conflicts(report_ref: str):
    actor = require_user()
    import os
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "report store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = store.get_report(report_ref)
    except Exception:
        return jsonify({"success": False, "error": "report not found"}), 404
    if not _can_read_report(actor, document, report_ref):
        return jsonify({"success": False, "error": "report access denied"}), 403
    return jsonify({"success": True, "conflicts": store.conflicts(report_ref)})


@sft_bp.post("/api/reports/<report_ref>/conflicts/resolve")
def resolve_report_conflicts(report_ref: str):
    actor = require_user()
    import os
    from flask import request
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "report store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = store.get_report(report_ref)
    except Exception:
        return jsonify({"success": False, "error": "report not found"}), 404
    if document.get("owner") != actor:
        from tools.data.account_manage import get_account, is_super_admin_account
        if not is_super_admin_account(get_account(actor)):
            import os as _os
            from server.permissions.entries import PermissionStore
            db = _os.environ.get("TRADERESEARCH_PERMISSIONS_DB", "") or _os.environ.get("FACTORTESTER_PERMISSIONS_DB", "")
            from server.permissions.subjects import subjects_for_user

            if not (db and any(PermissionStore(db).allows(
                subject=subject, resource_type="admin_console",
                resource_ref="dispatch", action="manage",
            ) for subject in subjects_for_user(actor))):
                return jsonify({"success": False, "error": "report owner or admin manage permission required"}), 403
    keep_rev = str((request.get_json(silent=True) or {}).get("keep_rev") or "")
    if not keep_rev:
        return jsonify({"success": False, "error": "keep_rev is required"}), 400
    remaining = store.resolve_conflicts(report_ref, keep_rev=keep_rev)
    try:
        from server.jobs.dispatch.audit import append_audit
        import settings as Settings

        append_audit(
            Settings.CACHE_DB_PATH, action="report_conflict_resolve",
            actor=actor, job_id=report_ref, detail=keep_rev,
        )
    except Exception:
        pass
    return jsonify({"success": True, "conflicts": remaining})


@sft_bp.get("/api/job-test-reports/<report_ref>/attachments")
@sft_bp.get("/api/reports/<report_ref>/attachments")
def list_report_attachments(report_ref: str):
    actor = require_user()
    import os
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "report store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = store.get_report(report_ref)
    except Exception:
        return jsonify({"success": False, "error": "report not found"}), 404
    if not _can_read_report(actor, document, report_ref):
        return jsonify({"success": False, "error": "report access denied"}), 403
    attachments = document.get("_attachments") if isinstance(document.get("_attachments"), dict) else {}
    return jsonify({"success": True, "attachments": [
        {"name": name, "content_type": str(meta.get("content_type") or ""),
         "length": int(meta.get("length") or 0)}
        for name, meta in sorted(attachments.items())
    ]})


@sft_bp.get("/api/job-test-reports/<report_ref>/attachments/<path:name>")
@sft_bp.get("/api/reports/<report_ref>/attachments/<path:name>")
def get_report_attachment(report_ref: str, name: str):
    """Stream one content-addressed CouchDB report attachment."""
    actor = require_user()
    import os
    from flask import Response
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "report store unavailable"}), 503
    store = CouchDBObjectStore(
        url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip(),
        username=os.environ.get("FACTORTESTER_COUCHDB_USER", ""),
        password=os.environ.get("FACTORTESTER_COUCHDB_PASSWORD", ""),
    )
    try:
        document = store.get_report(report_ref)
    except Exception:
        return jsonify({"success": False, "error": "report not found"}), 404
    if not _can_read_report(actor, document, report_ref):
        return jsonify({"success": False, "error": "report access denied"}), 403
    attachment = (document.get("attachments") or {}).get(name)
    if not attachment:
        return jsonify({"success": False, "error": "attachment not found"}), 404
    data = store.get_attachment(report_ref, attachment)
    mime = "text/html" if name.endswith(".html") else "text/csv" if name.endswith(".csv") else "application/octet-stream"
    return Response(data, mimetype=mime, headers={"Content-Disposition": f'inline; filename="{name}"'})


@sft_bp.post("/api/research-reports/<publication_id>/operations")
def apply_research_report_operation(publication_id: str):
    actor = require_user()
    import os
    from flask import request
    from server.jobs.storage.couchdb_research_reports import get_research_report
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore
    from server.jobs.storage.research_report_operations import apply_index_operation

    payload = request.get_json(silent=True) or {}
    base_rev = str(payload.get("base_rev") or "")
    operation = payload.get("operation") if isinstance(payload.get("operation"), dict) else payload
    if not base_rev:
        return jsonify({"success": False, "error": "base_rev is required"}), 400
    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "research report store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = get_research_report(store, publication_id)
    except Exception:
        return jsonify({"success": False, "error": "research report not found"}), 404
    if document.get("owner_ref") != actor:
        return jsonify({"success": False, "error": "only the research report owner may edit"}), 403
    try:
        result = apply_index_operation(store, document, base_rev=base_rev, operation=operation)
    except ValueError as exc:
        code = 409 if "conflict" in str(exc) else 400
        return jsonify({"success": False, "error": str(exc)}), code
    try:
        from server.jobs.dispatch.audit import append_audit
        import settings as Settings

        append_audit(Settings.CACHE_DB_PATH, action="research_report_operation",
                     actor=actor, job_id=publication_id,
                     detail=str(operation.get("op") or ""))
    except Exception:
        pass
    return jsonify({"success": True, "rev": result["rev"],
                    "attachment": result["attachment"],
                    "chapters": result["index"].get("chapters") or []})


@sft_bp.get("/api/research-reports/<publication_id>/conflicts")
def get_research_report_conflicts(publication_id: str):
    actor = require_user()
    import os
    from server.jobs.storage.couchdb_research_reports import document_id, get_research_report
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "research report store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = get_research_report(store, publication_id)
    except Exception:
        return jsonify({"success": False, "error": "research report not found"}), 404
    if document.get("owner_ref") != actor:
        return jsonify({"success": False, "error": "only the research report owner may inspect conflicts"}), 403
    return jsonify({"success": True, "conflicts": store.conflicts(document_id(publication_id))})


@sft_bp.post("/api/research-reports/<publication_id>/conflicts/resolve")
def resolve_research_report_conflicts(publication_id: str):
    actor = require_user()
    import os
    from flask import request
    from server.jobs.storage.couchdb_research_reports import document_id, get_research_report
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "research report store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = get_research_report(store, publication_id)
    except Exception:
        return jsonify({"success": False, "error": "research report not found"}), 404
    if document.get("owner_ref") != actor:
        return jsonify({"success": False, "error": "only the research report owner may resolve conflicts"}), 403
    keep_rev = str((request.get_json(silent=True) or {}).get("keep_rev") or "")
    if not keep_rev:
        return jsonify({"success": False, "error": "keep_rev is required"}), 400
    remaining = store.resolve_conflicts(document_id(publication_id), keep_rev=keep_rev)
    try:
        from server.jobs.dispatch.audit import append_audit
        import settings as Settings

        append_audit(Settings.CACHE_DB_PATH, action="research_report_conflict_resolve",
                     actor=actor, job_id=publication_id, detail=keep_rev)
    except Exception:
        pass
    return jsonify({"success": True, "conflicts": remaining})


@sft_bp.get("/api/research-reports/<publication_id>/agent")
def get_research_report_agent(publication_id: str):
    actor = require_user()
    import os
    from server.jobs.storage.couchdb_research_reports import get_research_report, projection
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore
    from server.jobs.storage.research_report_agent import agent_manifest, agent_markdown, load_index

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "research report store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = get_research_report(store, publication_id)
        value = projection(store, document)
        index_value = load_index(store, document)
    except Exception:
        return jsonify({"success": False, "error": "research report not found"}), 404
    if document.get("owner_ref") != actor and str(document.get("visibility") or "private") != "public":
        return jsonify({"success": False, "error": "research report access denied"}), 403
    return jsonify({"success": True, "manifest": agent_manifest(document, index_value), "markdown": agent_markdown(store, document, index_value)})


@sft_bp.get("/api/research-reports/<publication_id>/agent.md")
def get_research_report_agent_markdown(publication_id: str):
    actor = require_user()
    import os
    from server.jobs.storage.couchdb_research_reports import get_research_report, projection
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore
    from server.jobs.storage.research_report_agent import agent_manifest, agent_markdown, load_index

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "research report store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = get_research_report(store, publication_id)
        value = projection(store, document)
        index_value = load_index(store, document)
    except Exception:
        return jsonify({"success": False, "error": "research report not found"}), 404
    if document.get("owner_ref") != actor and str(document.get("visibility") or "private") != "public":
        return jsonify({"success": False, "error": "research report access denied"}), 403
    return Response(agent_markdown(store, document, index_value), mimetype="text/markdown")


@sft_bp.get("/api/research-reports/<publication_id>/projection")
def get_research_report_projection(publication_id: str):
    actor = require_user()
    import os
    from server.jobs.storage.couchdb_research_reports import get_research_report, projection
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "research report store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = get_research_report(store, publication_id)
        value = projection(store, document)
    except Exception:
        return jsonify({"success": False, "error": "research report projection not found"}), 404
    visibility = str(document.get("visibility") or "private")
    if document.get("owner_ref") != actor and visibility != "public":
        return jsonify({"success": False, "error": "research report access denied"}), 403
    return jsonify({"success": True, "projection": value})


@sft_bp.get("/api/research-reports/<publication_id>/attachments")
def list_research_report_attachments(publication_id: str):
    actor = require_user()
    import os
    from server.jobs.storage.couchdb_research_reports import get_research_report
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "research report store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = get_research_report(store, publication_id)
    except Exception:
        return jsonify({"success": False, "error": "research report not found"}), 404
    visibility = str(document.get("visibility") or "private")
    allowed = document.get("owner_ref") == actor or visibility == "public"
    if not allowed:
        from server.permissions.entries import PermissionStore
        from server.permissions.subjects import subjects_for_user
        db = os.environ.get("TRADERESEARCH_PERMISSIONS_DB", "") or os.environ.get("FACTORTESTER_PERMISSIONS_DB", "")
        allowed = bool(db and any(PermissionStore(db).allows(
            subject=subject, resource_type="research_report",
            resource_ref=publication_id, action="read",
        ) for subject in subjects_for_user(actor)))
    if not allowed:
        return jsonify({"success": False, "error": "research report access denied"}), 403
    attachments = document.get("attachments") if isinstance(document.get("attachments"), dict) else {}
    return jsonify({"success": True, "attachments": [
        {"path": path, **meta} for path, meta in sorted(attachments.items())
    ]})


@sft_bp.get("/api/research-reports/<publication_id>/attachments/<path:name>")
def get_research_report_attachment(publication_id: str, name: str):
    actor = require_user()
    import os
    from server.jobs.storage.couchdb_research_reports import document_id, get_research_report
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "research report store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = get_research_report(store, publication_id)
    except Exception:
        return jsonify({"success": False, "error": "research report not found"}), 404
    visibility = str(document.get("visibility") or "private")
    allowed = document.get("owner_ref") == actor or visibility == "public"
    if not allowed:
        from server.permissions.entries import PermissionStore
        from server.permissions.subjects import subjects_for_user
        db = os.environ.get("TRADERESEARCH_PERMISSIONS_DB", "") or os.environ.get("FACTORTESTER_PERMISSIONS_DB", "")
        allowed = bool(db and any(PermissionStore(db).allows(
            subject=subject, resource_type="research_report",
            resource_ref=publication_id, action="read",
        ) for subject in subjects_for_user(actor)))
    if not allowed:
        return jsonify({"success": False, "error": "research report access denied"}), 403
    attachments = document.get("attachments") if isinstance(document.get("attachments"), dict) else {}
    meta = next((item for item in attachments.values()
                 if isinstance(item, dict) and item.get("name") == name), None)
    if meta is None:
        return jsonify({"success": False, "error": "attachment not found"}), 404
    data = store.get_attachment(document_id(publication_id), name)
    response = make_response(data)
    response.headers["Content-Type"] = str(meta.get("content_type") or "application/octet-stream")
    response.headers["Content-Disposition"] = f'inline; filename="{name}"'
    return response


@sft_bp.get("/api/research-reports/<publication_id>")
def get_research_report_document(publication_id: str):
    actor = require_user()
    import os
    from server.jobs.storage.couchdb_research_reports import get_research_report
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "research report store unavailable"}), 503
    store = CouchDBObjectStore(url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip())
    try:
        document = get_research_report(store, publication_id)
    except Exception:
        return jsonify({"success": False, "error": "research report not found"}), 404
    visibility = str(document.get("visibility") or "private")
    allowed = document.get("owner_ref") == actor or visibility == "public"
    if not allowed:
        from server.permissions.entries import PermissionStore
        from server.permissions.subjects import subjects_for_user
        db = os.environ.get("TRADERESEARCH_PERMISSIONS_DB", "") or os.environ.get("FACTORTESTER_PERMISSIONS_DB", "")
        allowed = bool(db and any(PermissionStore(db).allows(
            subject=subject, resource_type="research_report",
            resource_ref=publication_id, action="read",
        ) for subject in subjects_for_user(actor)))
    if not allowed:
        return jsonify({"success": False, "error": "research report access denied"}), 403
    return jsonify({"success": True, "document": document})


@sft_bp.get("/api/job-test-reports/<path:report_ref>")
@sft_bp.get("/api/reports/<path:report_ref>")
def get_report_document(report_ref: str):
    """Read one CouchDB report document, scoped to its owner."""
    actor = require_user()
    import os
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore

    url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
    if not url:
        return jsonify({"success": False, "error": "report store unavailable"}), 503
    store = CouchDBObjectStore(
        url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip(),
        username=os.environ.get("FACTORTESTER_COUCHDB_USER", ""),
        password=os.environ.get("FACTORTESTER_COUCHDB_PASSWORD", ""),
    )
    try:
        document = store.get_report(report_ref)
    except Exception:
        return jsonify({"success": False, "error": "report not found"}), 404
    if not _can_read_report(actor, document, report_ref):
        return jsonify({"success": False, "error": "report access denied"}), 403
    return jsonify({"success": True, "document": document})


@sft_bp.get("/api/dispatch/status")
def dispatch_status():
    """Read-only dispatch/worker projection for the operations panel."""
    require_user()
    from server.jobs.dispatch.outbox import DispatchOutbox

    job_repository = repository()
    db_path = getattr(job_repository, "db_path", None)
    if db_path is None:
        return jsonify({"success": False, "error": "job repository unavailable"}), 503
    outbox = DispatchOutbox(db_path)
    deployment = os.environ.get("FACTORTESTER_DEPLOYMENT_ID", "").strip()
    raw_port = os.environ.get("FACTORTESTER_SERVICE_PORT", "").strip()
    port = int(raw_port) if raw_port.isdigit() else 0
    return jsonify({
        "success": True,
        "deployment_id": deployment,
        "service_port": port,
        "queue": (
            f"factortester.jobs.{deployment}.{port}"
            if deployment and port else ""
        ),
        "outbox": outbox.counts(),
        "workers": job_repository.list_worker_targets(),
    })


@sft_bp.get("/api/jobs/<job_id>/stream")
def stream_test_job(job_id: str):
    """Stream the durable Job progress projection.

    Celery workers run in a different process (and possibly a different
    server), so the old daemon EventBroker is no longer the live source.
    Progress snapshots are persisted in the Job database and replayed here.
    """
    _job, error = require_job(job_id)
    if error:
        return error
    owner = require_user()

    @stream_with_context
    def generate():
        last_sequence = -1
        while True:
            current = repository().load(job_id, owner=owner)
            if current is None:
                yield _sse("error", {"error": "research job not found"})
                return
            progress = repository().progress(job_id, current.attempt)
            if progress is not None and int(progress["sequence"]) > last_sequence:
                last_sequence = int(progress["sequence"])
                yield _sse("progress", {
                    **progress,
                    "status": current.status.value,
                    "percent_scope": "global",
                })
            if current.status in TERMINAL_STATUSES:
                yield _sse("result", {
                    "status": current.status.value,
                    "result_summary": current.result_summary,
                    "error": current.error,
                })
                return
            yield _sse("heartbeat", {
                "status": current.status.value,
                "latest_progress": (
                    progress if progress is not None and last_sequence >= 0 else None
                ),
                "server_time": time.time(),
            })
            time.sleep(1.0)

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
        "report_ref": job.report_ref or (
            str(job.result_summary.get("report_ref") or "")
            if isinstance(job.result_summary, dict) else ""
        ),
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
    usage = job_repository.storage_usage(owner=owner, job_bytes=breakdown["artifact_bytes"])
    quota = job_repository.storage_quota(
        owner=owner,
        default_bytes=default_user_quota_bytes(),
    )
    try:
        inventory = job_repository.storage_inventory(
            owner=owner,
            category=str(request.args.get("category") or ""),
            limit=int(request.args.get("limit") or 50),
            offset=int(request.args.get("offset") or 0),
            group=str(request.args.get("group") or ""),
            job_id=str(request.args.get("job_id") or ""),
        )
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "invalid storage page"}), 400
    return jsonify({
        "success": True,
        "usage_bytes": usage,
        "quota_bytes": quota,
        "over_quota": usage > quota,
        **breakdown,
        **inventory,
        "servers": job_repository.storage_servers(owner=owner),
        "unattributed_bytes": max(0, breakdown["artifact_bytes"] - inventory["covered_bytes"]),
        "quota_scope": "measured_account_storage",
        "excluded_scopes": [],
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

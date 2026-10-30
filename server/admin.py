"""Retired local user administration and Keycloak-protected job inspection."""

from __future__ import annotations

import base64

from flask import Blueprint, g, jsonify, request
import orjson

from server.jobs.repository import JobRepository
from server.services.http_auth import login_required


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _keycloak_admin_failure():
    from server.identity.keycloak_authorization import keycloak_request_credentials

    if keycloak_request_credentials() is None:
        return jsonify({"success": False, "error": "需要有效的 Keycloak 会话"}), 401
    identity = getattr(g, "keycloak_user_session", None)
    roles = identity.get("keycloak_roles", ()) if isinstance(identity, dict) else ()
    if "admin_console:manage" not in roles:
        return jsonify({"success": False, "error": "需要 Keycloak 管理权限"}), 403
    return None


@admin_bp.before_request
def _retire_local_identity_administration():
    """User, organization, and hierarchy management now lives in Keycloak."""
    if request.path == "/admin/api/jobs" and request.method == "GET":
        return None
    return jsonify({
        "success": False,
        "code": "keycloak_managed_identity",
        "error": "Manage users, organizations, groups, and roles in Keycloak.",
    }), 410


def _job_repository() -> JobRepository:
    from flask import current_app

    repository = current_app.extensions.get("job_repository")
    if not isinstance(repository, JobRepository):
        repository = JobRepository()
        current_app.extensions["job_repository"] = repository
    return repository


@admin_bp.route("/api/jobs", methods=["GET"])
@login_required
def api_global_jobs():
    failure = _keycloak_admin_failure()
    if failure:
        return failure
    try:
        limit = min(100, max(1, int(request.args.get("limit", "20") or 20)))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "limit 必须是整数"}), 400
    cursor = str(request.args.get("cursor") or "").strip()
    before_updated_at = None
    before_job_id = ""
    if cursor:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            decoded = orjson.loads(raw)
            before_updated_at = float(decoded["updated_at"])
            before_job_id = str(decoded["job_id"])
            if not before_job_id:
                raise ValueError
        except (KeyError, TypeError, ValueError, orjson.JSONDecodeError):
            return jsonify({"success": False, "error": "cursor 无效"}), 400
    jobs, has_more = _job_repository().list_global_summaries(
        limit=limit,
        before_updated_at=before_updated_at,
        before_job_id=before_job_id,
    )
    next_cursor = None
    if has_more and jobs:
        next_cursor = base64.urlsafe_b64encode(orjson.dumps({
            "updated_at": jobs[-1]["updated_at"],
            "job_id": jobs[-1]["job_id"],
        })).rstrip(b"=").decode()
    return jsonify({
        "success": True,
        "jobs": jobs,
        "page_size": len(jobs),
        "has_more": has_more,
        "next_cursor": next_cursor,
    })


@admin_bp.route("/api/<path:_retired_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def retired_local_admin_api(_retired_path: str):
    """Return a migration response for every removed local identity endpoint."""
    return jsonify({
        "success": False,
        "code": "keycloak_managed_identity",
        "error": "Manage users, organizations, groups, and roles in Keycloak.",
    }), 410

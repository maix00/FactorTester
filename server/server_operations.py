"""Super-admin server operations projection.

The authenticated FactorTester server is the authorization boundary.  The
loopback Manager remains the process-lifecycle owner and is never exposed to a
browser directly.
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from server.services.http_auth import login_required
from server.services.manager_control import manager_action, manager_snapshot
from server.identity.keycloak_authorization import keycloak_request_credentials


server_operations_bp = Blueprint("server_operations", __name__, url_prefix="/admin")
_ALLOWED_ACTIONS = frozenset({
    "start", "stop", "restart", "restart_api", "restart_bundle",
    "force_stop",
})


def _require_super_admin():
    if keycloak_request_credentials() is None:
        return jsonify({
            "success": False,
            "error": "需要有效的 Keycloak 会话",
        }), 401
    identity = getattr(g, "keycloak_user_session", None)
    roles = identity.get("keycloak_roles", ()) if isinstance(identity, dict) else ()
    if "admin_console:manage" not in roles:
        return jsonify({
            "success": False,
            "error": "需要 Keycloak 服务器管理权限",
        }), 403
    return None


@server_operations_bp.get("/api/server-instances")
@login_required
def api_server_instances():
    error = _require_super_admin()
    if error:
        return error
    try:
        snapshot = manager_snapshot()
    except Exception:
        return jsonify({
            "success": False,
            "error": "本机服务器管理服务当前不可用",
        }), 503
    return jsonify({"success": True, **snapshot})


@server_operations_bp.post("/api/server-instances/<instance_id>/actions")
@login_required
def api_server_instance_action(instance_id: str):
    error = _require_super_admin()
    if error:
        return error
    action = str((request.get_json(silent=True) or {}).get("action") or "")
    if action not in _ALLOWED_ACTIONS:
        return jsonify({
            "success": False,
            "error": "服务器实例或操作无效",
        }), 400
    try:
        result = manager_action(instance_id, action)
    except (LookupError, ValueError):
        return jsonify({
            "success": False,
            "error": "服务器实例或操作无效",
        }), 400
    except Exception:
        return jsonify({
            "success": False,
            "error": "本机服务器管理操作失败",
        }), 503
    return jsonify({"success": True, **result})

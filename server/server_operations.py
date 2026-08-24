"""Super-admin server operations projection.

The authenticated FactorTester server is the authorization boundary.  The
loopback Manager remains the process-lifecycle owner and is never exposed to a
browser directly.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from server.services.http_auth import login_required
from server.services.manager_control import manager_action, manager_snapshot
from server.services.session_runtime import require_user
from tools.data.account_manage import get_account, is_super_admin_account


server_operations_bp = Blueprint("server_operations", __name__, url_prefix="/admin")
_ALLOWED_ACTIONS = frozenset({
    "start", "stop", "restart", "restart_api", "restart_bundle",
    "force_stop",
})


def _require_super_admin():
    account = get_account(require_user())
    if not is_super_admin_account(account):
        return jsonify({
            "success": False,
            "error": "只有超级管理员可以管理服务器运行状态",
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

"""User-scoped discovery of FactorTester listener ports."""

from __future__ import annotations

from flask import jsonify, request

from server.jobs.ports import detect_port
from server.modules.single_factor_test import sft_bp
from server.services.manager_control import manager_snapshot
from server.services.session_runtime import require_user


def _valid_port(value: object) -> int:
    try:
        port = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return port if 1 <= port <= 65535 else 0


@sft_bp.get("/api/jobs/ports")
def list_job_ports():
    """Return only listener ports visible to the authenticated user.

    Manager capability data stays server-side.  This projection deliberately
    omits instance IDs, branch names, labels, paths, and manager addresses.
    The current listener is always included, so discovery still works when the
    local manager is unavailable.
    """
    require_user()
    current = _valid_port(detect_port(request.environ))
    ports = {current} if current else set()
    manager_available = False
    try:
        snapshot = manager_snapshot()
        manager_available = True
    except Exception:
        snapshot = {}
    for item in snapshot.get("instances", []) if isinstance(snapshot, dict) else []:
        if not isinstance(item, dict) or not item.get("running"):
            continue
        port = _valid_port(item.get("port"))
        if port:
            ports.add(port)
    return jsonify({
        "success": True,
        "ports": sorted(ports),
        "current_port": current,
        "source": "manager" if manager_available else "current_listener",
    })

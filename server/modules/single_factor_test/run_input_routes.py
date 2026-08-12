"""Authenticated inspection endpoints for source-backed Run inputs."""

from __future__ import annotations

from flask import jsonify, request

from server.modules.single_factor_test import sft_bp
from server.services.http_auth import login_required
from server.services.run_input_inspection import inspect_strategy_source


@sft_bp.post("/api/run-inputs/strategy/inspect")
@login_required
def inspect_strategy_run_input():
    try:
        inspected = inspect_strategy_source(request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify({
            "success": False,
            "valid": False,
            "code": "invalid_strategy_source",
            "error": str(exc),
        }), 400
    return jsonify({"success": True, "valid": True, **inspected})

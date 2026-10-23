"""Business-port API for the staged NautilusTrader workbench."""

from __future__ import annotations

from flask import Blueprint, jsonify

from server.services.nautilus_bridge.capabilities import native_capabilities
from server.services.session_runtime import current_user


nautilus_workbench_bp = Blueprint("nautilus_workbench", __name__)


@nautilus_workbench_bp.get("/api/nautilus/capabilities")
def capabilities():
    """Expose installed support, without promising an unconfigured trading mode."""
    if current_user() is None:
        return jsonify({"error": "authentication required"}), 401
    return jsonify(native_capabilities())

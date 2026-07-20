"""Authenticated protocol discovery for separately installed clients."""

from __future__ import annotations

from flask import jsonify

from server.services.http_auth import login_required
from server.services.protocol_manifest import protocol_manifest

from . import shared_bp


@shared_bp.get("/api/protocol-manifest")
@login_required
def api_protocol_manifest():
    return jsonify({"success": True, **protocol_manifest()})

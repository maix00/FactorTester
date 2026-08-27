"""Flask adapter for explicit client factor-workspace pulls."""

from __future__ import annotations

import os
from typing import cast

from flask import jsonify, request

from server.modules.custom_factors import cf_bp
from server.services.factor_source_manifest import FactorSourceManifest
from server.services.http_auth import login_required
from server.services.session_runtime import current_user


@cf_bp.route("/api/source-sync/manifest", methods=["GET"])
@login_required
def api_source_sync_manifest():
    value = FactorSourceManifest().build(
        cast(str, current_user()),
        server_id=str(os.environ.get("FACTORTESTER_SERVER_ID") or "local"),
        include_subordinates=(
            request.args.get("include_subordinates", "1") == "1"
        ),
    )
    return jsonify(value)


__all__ = ["api_source_sync_manifest"]

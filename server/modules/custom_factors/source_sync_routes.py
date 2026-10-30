"""Flask adapter for explicit client factor-workspace pulls."""

from __future__ import annotations

import os
from typing import cast

from flask import jsonify, request

from server.modules.custom_factors import factor_library_internal_bp
from server.services.factor_source_manifest import FactorSourceManifest
from server.services.http_auth import login_required
from server.services.session_runtime import current_user


@factor_library_internal_bp.route("/family-sources/manifest", methods=["GET"])
@login_required
def api_source_sync_manifest():
    try:
        from server.identity.keycloak_authorization import (
            AuthorizationUnavailable,
            keycloak_request_credentials,
        )

        credentials = keycloak_request_credentials()
        principal = cast(str, current_user())
        if credentials is None or credentials[2] != principal:
            return jsonify({"success": False, "error": "verified Keycloak session is required"}), 401
        value = FactorSourceManifest().build(
            principal,
            server_id=str(os.environ.get("FACTORTESTER_SERVER_ID") or "local"),
            access_token=credentials[0],
            include_subordinates=(
                request.args.get("include_subordinates", "1") == "1"
            ),
        )
        return jsonify(value)
    except PermissionError as exc:
        return jsonify({"success": False, "error": str(exc)}), 403
    except Exception as exc:
        from server.identity.keycloak_authorization import AuthorizationUnavailable

        if isinstance(exc, AuthorizationUnavailable):
            return jsonify({"success": False, "error": str(exc),
                            "code": "authorization_unavailable"}), 503
        raise


__all__ = ["api_source_sync_manifest"]

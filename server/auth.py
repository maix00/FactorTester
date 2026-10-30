"""Keycloak-only request gate for the business API."""

from __future__ import annotations

import re

from flask import Blueprint, g, jsonify, request, session

from server.services.page_runtime import cleanup_user_pages
from server.services.session_runtime import (
    check_session_idle,
    cleanup_session_resource,
    current_user,
    current_user_obj,
    touch_session_activity,
)


auth_bp = Blueprint("auth", __name__)
_RETIRED_ENDPOINTS = frozenset({
    "auth.login", "auth.register", "auth.api_keep_login",
    "auth.api_public_organizations", "auth.logout", "auth.api_account_password",
})


def _is_public_job_gateway_read() -> bool:
    """Allow only Manager-delegated, read-only job projections."""
    if not session.get("manager_gateway_public_jobs") or request.method != "GET":
        return False
    return request.path == "/api/jobs" or bool(re.fullmatch(
        r"/api/jobs/[A-Za-z0-9._-]{1,128}"
        r"(?:/result|/artifacts|/supplementals(?:/[A-Za-z0-9._-]{1,128})?"
        r"|/custom-analyses)?",
        request.path,
    ))


@auth_bp.before_app_request
def _check_login():
    """Authenticate business API calls through the verified Keycloak session."""
    public_endpoints = _RETIRED_ENDPOINTS | frozenset({
        "auth.api_me",
        "shared.client_release_channel",
        "shared.client_release_beta_appcast",
        "shared.client_release_asset",
    })
    endpoint = request.endpoint
    if endpoint is None or endpoint in public_endpoints:
        if current_user():
            touch_session_activity()
        if endpoint in _RETIRED_ENDPOINTS:
            return jsonify({
                "success": False,
                "code": "keycloak_managed_identity",
                "error": "Identity and password management are provided by Keycloak.",
            }), 410
        return None

    if _is_public_job_gateway_read():
        return None

    if current_user():
        if check_session_idle():
            user = current_user_obj()
            if user is not None:
                cleanup_user_pages(user)
            cleanup_session_resource(session.get("_sid", ""))
            session.clear()
            return jsonify({
                "success": False, "error": "会话已超时，请重新登录",
                "login_required": True, "auto_logout": True,
            }), 401
        touch_session_activity()
        return None

    return jsonify({
        "success": False, "error": "请先通过 Keycloak 登录",
        "login_required": True,
    }), 401


@auth_bp.get("/api/me")
def api_me():
    """Return verified identity claims; do not hydrate a local account record."""
    username = current_user()
    identity = getattr(g, "keycloak_user_session", None)
    roles = tuple(identity.get("keycloak_roles", ())) if isinstance(identity, dict) else ()
    return jsonify({
        "username": username,
        "alias": (identity or {}).get("alias") if isinstance(identity, dict) else None,
        "role": (identity or {}).get("role") if isinstance(identity, dict) else None,
        "keycloak_roles": list(roles),
        "is_admin": "admin_console:manage" in roles,
        "is_developer": "developer" in roles,
        "keep_login": bool(session.get("keep_login")),
    })


@auth_bp.post("/login")
def login():
    """Retired local password login endpoint."""
    return None  # The before-request gate returns the Keycloak-only 410.


@auth_bp.post("/register")
def register():
    """Retired local registration endpoint."""
    return None


@auth_bp.post("/logout")
def logout():
    """Retired business-port logout; the Manager owns the OIDC logout flow."""
    return None


@auth_bp.get("/api/organizations")
def api_public_organizations():
    """Retired account-database organization lookup used by local registration."""
    return None


@auth_bp.post("/api/keep_login")
def api_keep_login():
    """Retired local-session persistence toggle."""
    return None


@auth_bp.post("/api/account/password")
def api_account_password():
    """Retired password rotation endpoint; Keycloak owns credentials."""
    return None

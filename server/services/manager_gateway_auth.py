"""Authenticate loopback requests delegated by Manager 7998."""

from __future__ import annotations

import hmac
import os

from flask import Flask, request, session

from server.manager.http.visitor_access import (
    VISITOR_PRINCIPAL_PREFIX,
    normalize_visitor_id,
    visitor_principal,
)
from tools.data.account_manage import accounts_lock, load_accounts


def install_manager_gateway_auth(app: Flask) -> None:
    """Project one authenticated 7998 user into a sibling service request."""
    @app.before_request
    def accept_manager_gateway() -> None:
        owner = str(request.headers.get("X-FactorTester-Principal") or "").strip()
        supplied = str(request.headers.get("X-FactorTester-Manager") or "").strip()
        expected = os.environ.get("GTHT_MANAGER_CAPABILITY_TOKEN", "").strip()
        if not owner or not supplied or not expected:
            return
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            return
        if not hmac.compare_digest(supplied, expected):
            return
        if owner == "__public_jobs__":
            session["manager_gateway_public_jobs"] = True
            return
        if owner.startswith(VISITOR_PRINCIPAL_PREFIX):
            visitor_id = normalize_visitor_id(
                owner.removeprefix(VISITOR_PRINCIPAL_PREFIX)
            )
            if not visitor_id or owner != visitor_principal(visitor_id):
                return
            # A visitor owner is constructed by the Manager from an
            # origin-bound visitor session.  The service still receives the
            # owner through the existing Manager capability channel, but it
            # can only be a UUID namespace, never an account principal.
            session["username"] = owner
            session["manager_gateway_public_jobs"] = True
            session["manager_gateway_visitor_id"] = visitor_id
            return
        if owner == "__public_graph__":
            session["manager_gateway_public_graph"] = True
            return
        with accounts_lock:
            exists = any(
                str(account.get("username") or "") == owner
                for account in load_accounts()
            )
        if exists:
            session["username"] = owner
            session["manager_gateway"] = True

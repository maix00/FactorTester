"""Authenticate loopback requests delegated by Manager 7998."""

from __future__ import annotations

import hmac
import os

from flask import Flask, request, session

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
        with accounts_lock:
            exists = any(
                str(account.get("username") or "") == owner
                for account in load_accounts()
            )
        if exists:
            session["username"] = owner
            session["manager_gateway"] = True

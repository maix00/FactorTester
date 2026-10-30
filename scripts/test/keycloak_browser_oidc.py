#!/usr/bin/env python3
"""Verify browser login through Manager, its Keycloak session, and logout.

Uses the browser's normal TLS trust. Credentials come from the environment;
no passwords, cookies, codes or tokens are included in the acceptance receipt.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main() -> int:
    manager = os.environ["MANAGER_URL"].rstrip("/")
    origin = urlsplit(manager)
    if origin.scheme not in {"http", "https"} or not origin.netloc or origin.path:
        raise SystemExit("MANAGER_URL must be a Manager origin")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel=os.environ.get("PLAYWRIGHT_CHANNEL", "chrome"))
        try:
            context = browser.new_context()
            # Validate deployment readiness before requesting credentials. A
            # standalone Keycloak form is not proof of Manager integration.
            start = context.request.get(manager + "/auth/oidc/start?next=/app", max_redirects=0)
            location = start.headers.get("location", "")
            if start.status not in {302, 303} or "/protocol/openid-connect/auth" not in location:
                raise SystemExit(f"Manager OIDC is not ready (HTTP {start.status})")
            username = os.environ["KEYCLOAK_USERNAME"]
            password = os.environ["KEYCLOAK_PASSWORD"]
            page = context.new_page()
            page.goto(manager + "/auth/oidc/start?next=/app")
            page.locator("#username").fill(username)
            if not page.locator("#password").is_visible():
                page.locator("#kc-login").click()
            page.locator("#password").fill(password)
            page.locator("#kc-login").click()
            page.wait_for_url(re.compile(re.escape(manager) + r"/app(?:[?#].*)?$"), timeout=30000)
            response = context.request.get(manager + "/api/session")
            if response.status != 200:
                raise SystemExit(f"Manager session verification failed (HTTP {response.status})")
            session = response.json()
            if (session.get("username") != username or not session.get("keycloak_subject")
                    or not session.get("keycloak_issuer") or session.get("visitor_login")):
                raise SystemExit("Manager returned no matching Keycloak user session")
            expected_role = os.environ.get("KEYCLOAK_EXPECTED_ROLE")
            if expected_role and session.get("role") != expected_role:
                raise SystemExit("Manager role does not match migration acceptance")
            checks = ["manager_login", "verified_session"]
            if "admin_console:manage" in session.get("admin_capabilities", []):
                directory = context.request.get(manager + "/api/admin/account-directory")
                if directory.status != 200:
                    raise SystemExit(f"Administrator directory failed (HTTP {directory.status})")
                checks.append("administrator_directory")
            logout = context.request.post(manager + "/auth/logout", headers={"Origin": manager})
            if logout.status != 200:
                raise SystemExit(f"Manager logout failed (HTTP {logout.status})")
            after = context.request.get(manager + "/api/session")
            if after.status != 401:
                if after.status != 200 or after.json().get("visitor_login") is not True:
                    raise SystemExit("Logout left an authenticated user session")
            checks.append("manager_logout")
            print(json.dumps({"manager": manager, "role": session.get("role"), "checks": checks}))
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify browser login through Manager, its Keycloak session, and logout.

Uses the browser's normal TLS trust. Credentials come from the environment;
no passwords, cookies, codes or tokens are included in the acceptance receipt.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import parse_qs, urlsplit

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
            page.goto(manager + "/app")
            organization_entry = page.get_by_role("button", name=re.compile(
                r"使用组织账户继续|Continue with your organization account"))
            page.get_by_role("button", name=re.compile(
                r"^(登录|Sign in)$|使用组织账户继续|Continue with your organization account"
            )).first.wait_for(state="visible")
            if not organization_entry.is_visible():
                page.get_by_role("button", name=re.compile(r"^(登录|Sign in)$")).first.click()
            organization_entry.wait_for(state="visible")
            organization_entry.click()
            page.locator("#username").wait_for(state="visible")
            page.locator("#username").fill(username)
            if not page.locator("#password").is_visible():
                page.locator("#kc-login").click()
            page.locator("#password").fill(password)
            page.locator("#kc-login").click()
            if os.environ.get("KEYCLOAK_EXPECT_PUBLIC_LOGIN_DENIED") == "1":
                page.wait_for_url(manager + "/app?auth_error=public_login_denied", timeout=30000)
                if any(cookie["name"] == "ft-manager-session"
                       for cookie in context.cookies(manager)):
                    raise SystemExit("Denied public login created a Manager session")
                print(json.dumps({"manager": manager,
                                  "checks": ["react_login_entry", "public_login_denied",
                                             "no_manager_session"]}))
                return 0
            page.wait_for_url(re.compile(re.escape(manager) + r"/app(?:[?#].*)?$"), timeout=30000)
            error = parse_qs(urlsplit(page.url).query).get("auth_error", [""])[0]
            if error:
                safe_error = error if error in {"provider", "invalid", "unverified", "public_login_denied", "device"} else "unknown"
                raise SystemExit(f"Manager OIDC callback rejected ({safe_error})")
            response = context.request.get(manager + "/api/session")
            if response.status != 200:
                has_session = any(c["name"] == "ft-manager-session" for c in context.cookies(manager))
                browser_status = page.evaluate("fetch('/api/session').then(r => r.status)")
                from server.identity.user_session import keycloak_session, may_login_public_server
                token = next((c["value"] for c in context.cookies(manager) if c["name"] == "ft-manager-session"), "")
                identity = keycloak_session(token)
                raise SystemExit(f"Manager session verification failed (HTTP {response.status}, browser_http={browser_status}, cookie_present={has_session}, token_bytes={len(token)}, introspection_valid={identity is not None}, public_allowed={may_login_public_server(identity)})")
            session = response.json()
            if (session.get("username") != username or not session.get("keycloak_subject")
                    or not session.get("keycloak_issuer") or session.get("visitor_login")):
                raise SystemExit("Manager returned no matching Keycloak user session")
            expected_role = os.environ.get("KEYCLOAK_EXPECTED_ROLE")
            if expected_role and session.get("role") != expected_role:
                raise SystemExit("Manager role does not match migration acceptance")
            checks = ["react_login_entry", "manager_login", "verified_session"]
            directory = context.request.get(manager + "/api/admin/account-directory")
            is_admin = session.get('role') in {'super_admin', 'org_admin', 'level_admin'}
            if directory.status != (200 if is_admin else 403):
                raise SystemExit(f"Administrator boundary failed (HTTP {directory.status})")
            if is_admin:
                checks.append("administrator_directory")
            else:
                checks.append("administrator_denied")
            for variable, expected in [('KEYCLOAK_ALLOWED_USER_ID', 200),
                                       ('KEYCLOAK_DENIED_USER_ID', 403)]:
                target = os.environ.get(variable)
                if target:
                    from urllib.parse import quote
                    token = next(c['value'] for c in context.cookies(manager)
                                 if c['name'] == 'ft-manager-session')
                    realm = session['keycloak_issuer'].rsplit('/', 1)[-1]
                    response = context.request.get(
                        manager + '/identity/admin/realms/' + quote(realm, safe='')
                        + '/users/' + quote(target, safe=''),
                        headers={'Authorization': 'Bearer ' + token})
                    if response.status != expected:
                        raise SystemExit(f"Keycloak scoped user boundary failed (expected {expected}, HTTP {response.status})")
                    checks.append('scoped_user_' + str(expected))
            for variable, expected in [("KEYCLOAK_OWN_RESOURCE", True),
                                       ("KEYCLOAK_OTHER_RESOURCE", False)]:
                resource_id = os.environ.get(variable)
                if resource_id:
                    from server.identity.keycloak_authorization import keycloak_authorized
                    token = next(c["value"] for c in context.cookies(manager)
                                 if c["name"] == "ft-manager-session")
                    if keycloak_authorized(token, resource_id=resource_id, scope="read") != expected:
                        raise SystemExit("Keycloak object ownership boundary failed")
                    checks.append("object_allowed" if expected else "object_denied")
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
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Playwright exceptions can contain authorization URLs and cookies.
        # Keep only a safe failure category in the public acceptance output.
        raise SystemExit(f"Browser acceptance failed: {type(exc).__name__}") from None

#!/usr/bin/env python3
"""Verify browser login through Manager, its Keycloak session, and logout.

Uses normal TLS trust or an explicitly supplied CA with a pinned Chrome key.
Credentials come from the environment;
no passwords, cookies, codes or tokens are included in the acceptance receipt.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright


@contextmanager
def browser_certificate_trust():
    """Trust one reviewed public certificate, never disable TLS globally."""
    path = os.environ.get('KEYCLOAK_BROWSER_CA_FILE')
    if not path:
        yield {}
        return
    import base64
    import hashlib
    from pathlib import Path
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    certificate = Path(path).expanduser().resolve(strict=True)
    if not certificate.is_file() or certificate.stat().st_size > 1024*1024:
        raise ValueError('browser CA file is invalid or too large')
    pem = certificate.read_bytes()
    if b'PRIVATE KEY' in pem:
        raise ValueError('browser CA file must contain public certificates only')
    cert = x509.load_pem_x509_certificate(pem)
    spki = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    pin = base64.b64encode(hashlib.sha256(spki).digest()).decode('ascii')
    previous = os.environ.get('NODE_EXTRA_CA_CERTS')
    # Playwright's APIRequestContext runs in its Node driver. Chrome requires
    # its own explicit key pin; ignore_https_errors remains disabled in both.
    os.environ['NODE_EXTRA_CA_CERTS'] = str(certificate)
    try:
        yield {'args': ['--ignore-certificate-errors-spki-list='+pin]}
    finally:
        if previous is None:
            os.environ.pop('NODE_EXTRA_CA_CERTS', None)
        else:
            os.environ['NODE_EXTRA_CA_CERTS'] = previous


def verify_assistant_admission(session, get, expected_role: str) -> str:
    """Check a newly issued claim and the real Manager's gated read API.

    This starts no Agent, creates no Profile and sends no model request. It is
    permission acceptance, not a claim that chat execution has been verified.
    """
    if expected_role not in {'agent_assistant:public:use', 'agent_assistant:internal:use', 'denied'}:
        raise ValueError('invalid assistant permission expectation')
    denied = expected_role == 'denied'
    if not denied and expected_role not in session.get('keycloak_roles', ()):
        raise SystemExit('New Manager session omitted the expected assistant location role')
    response = get('/api/client/profile-claims')
    if response.status != (403 if denied else 200):
        raise SystemExit(f'Assistant admission failed (HTTP {response.status})')
    payload = response.json()
    if not denied and (payload.get('success') is not True or not isinstance(payload.get('claims'), list)):
        raise SystemExit('Assistant admission returned an invalid response')
    return 'assistant_denied' if denied else 'assistant_location_permission'


def main() -> int:
    manager = os.environ["MANAGER_URL"].rstrip("/")
    origin = urlsplit(manager)
    if origin.scheme not in {"http", "https"} or not origin.netloc or origin.path:
        raise SystemExit("MANAGER_URL must be a Manager origin")
    with browser_certificate_trust() as tls_options, sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel=os.environ.get("PLAYWRIGHT_CHANNEL", "chrome"), **tls_options)
        try:
            device = os.environ.get('KEYCLOAK_BROWSER_DEVICE')
            if device and device not in p.devices:
                raise ValueError('unknown browser acceptance device')
            context = browser.new_context(**(p.devices[device] if device else {}))
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
            expected_principal = os.environ.get("KEYCLOAK_EXPECTED_PRINCIPAL", username)
            if (session.get("username") != expected_principal or not session.get("keycloak_subject")
                    or not session.get("keycloak_issuer") or session.get("visitor_login")):
                raise SystemExit("Manager returned no matching Keycloak user session")
            expected_role = os.environ.get("KEYCLOAK_EXPECTED_ROLE")
            if expected_role and session.get("role") != expected_role:
                raise SystemExit("Manager role does not match migration acceptance")
            checks = ["react_login_entry", "manager_login", "verified_session"]
            if os.environ.get('KEYCLOAK_VERIFY_REFRESH') == '1':
                if not any(c['name'] == 'tr-oidc-refresh' and c['httpOnly']
                           for c in context.cookies(manager)):
                    raise SystemExit('Login did not issue an HttpOnly refresh credential')
                # Model an idle browser whose access cookie has expired. Keep
                # its real Keycloak refresh credential; no realm TTL mutation.
                context.clear_cookies(name='ft-manager-session')
                renewed = page.evaluate("""async () => Promise.all(Array.from({length: 8}, async () => {
                    const r = await fetch('/api/session', {cache:'no-store'});
                    const s = await r.json();
                    return {status:r.status, subject:s.keycloak_subject};
                }))""")
                if any(r['status'] != 200 or r.get('subject') != session['keycloak_subject']
                       for r in renewed):
                    raise SystemExit('Concurrent browser refresh failed or changed identity')
                if not any(c['name'] == 'ft-manager-session' for c in context.cookies(manager)):
                    raise SystemExit('Refresh did not restore the access cookie')
                checks.append('concurrent_browser_refresh:8')
            directory = context.request.get(manager + "/api/admin/account-directory")
            is_admin = session.get('role') in {'super_admin', 'org_admin', 'level_admin'}
            if directory.status != (200 if is_admin else 403):
                raise SystemExit(f"Administrator boundary failed (HTTP {directory.status})")
            if is_admin:
                checks.append("administrator_directory")
            else:
                checks.append("administrator_denied")
            expected_assistant = os.environ.get('KEYCLOAK_EXPECT_ASSISTANT_ROLE')
            if expected_assistant:
                checks.append(verify_assistant_admission(session,
                    lambda path: context.request.get(manager + path), expected_assistant))
            expectations_path = os.environ.get('KEYCLOAK_RESEARCH_EXPECTATIONS')
            if expectations_path:
                # A separately reviewed migration allow-set, not an owner-name
                # heuristic. List reads may schedule the normal lazy refresh.
                from scripts.migrations.keycloak_research_stage import _read_private_json
                expected = _read_private_json(expectations_path)
                if (not isinstance(expected, dict) or expected.get('schema') != 'tr-research-browser-parity-v1'
                        or expected.get('identity_id') != session.get('tr_identity_id')):
                    raise SystemExit('Research expectations belong to another identity')
                for endpoint, field, ref_key, expected_key in (
                    ('/api/research?scope=all', 'researches', 'research_id', 'research_refs'),
                    ('/api/research/reports?scope=all', 'reports', 'report_id', 'report_refs'),
                ):
                    wanted = expected.get(expected_key)
                    if (not isinstance(wanted, list) or any(not isinstance(ref, str) or not ref for ref in wanted)
                            or len(set(wanted)) != len(wanted)):
                        raise SystemExit('Invalid reviewed Research allow-set')
                    response = context.request.get(manager + endpoint)
                    if response.status != 200:
                        raise SystemExit(f'Research list failed (HTTP {response.status})')
                    rows = response.json().get(field)
                    if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get(ref_key) for row in rows):
                        raise SystemExit('Research list omitted identities')
                    refs = [row[ref_key] for row in rows]
                    if len(set(refs)) != len(refs) or set(refs) != set(wanted):
                        raise SystemExit(f'Research allow-set mismatch (list={field}, missing={len(set(wanted)-set(refs))}, unexpected={len(set(refs)-set(wanted))})')
                    checks.append(f'{field}_ref_set_verified:{len(refs)}')
                page.locator('.tr-module-nav button').filter(has_text=re.compile(r'^(研究|Research)$')).click()
                page.locator('.tr-research-page .ant-table-tbody').wait_for()
                page.locator('.tr-research-page .ant-spin-spinning').wait_for(state='hidden')
                leaked = page.locator('.tr-tab-layer[aria-hidden="true"] button, .tr-tab-layer[aria-hidden="true"] input').evaluate_all('''nodes => nodes.some(node => {
                    const style=getComputedStyle(node),rect=node.getBoundingClientRect();
                    return rect.width>0 && rect.height>0 && style.visibility!=='hidden' && style.display!=='none';
                })''')
                if leaked:
                    raise SystemExit('Inactive Dockview controls overlap the Research page')
                screenshot = os.environ.get('KEYCLOAK_RESEARCH_SCREENSHOT')
                if screenshot:
                    page.screenshot(path=screenshot)
                checks.append('react_research_table')
            assistant_screenshot = os.environ.get('KEYCLOAK_ASSISTANT_SCREENSHOT')
            if assistant_screenshot:
                if expected_assistant not in {'agent_assistant:public:use', 'agent_assistant:internal:use'}:
                    raise SystemExit('Assistant UI acceptance requires an allowed location role')
                page.get_by_role('button', name=re.compile(
                    r'打开智能体助手|Open agent assistant', re.I)).click()
                panel = page.locator('.tr-agent-assistant-panel:visible, .tr-agent-assistant-drawer:visible').first
                panel.wait_for(state='visible')
                panel.locator('.tr-agent-assistant-loading').wait_for(state='hidden', timeout=60000)
                panel.locator('.tr-agent-assistant-mount[aria-busy="true"]').wait_for(state='detached', timeout=60000)
                page.screenshot(path=assistant_screenshot, animations='disabled', scale='css')
                if panel.locator('.tr-agent-assistant-error, .ant-alert-warning').count():
                    raise SystemExit('Assistant UI returned an error or permission denial')
                state = 'setup' if panel.locator('.tr-agent-assistant-setup').count() else 'conversation'
                if state == 'conversation':
                    panel.locator('.profile-chatkit-host').wait_for(state='visible')
                checks.append('react_assistant_' + state)
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
            inventory_path = os.environ.get("KEYCLOAK_RESOURCE_INVENTORY")
            if inventory_path:
                # This owner-only check detects accidentally public resources;
                # it does not represent historical sharing/hierarchy parity.
                from pathlib import Path
                from collections import defaultdict
                from server.identity.keycloak_authorization import keycloak_authorized_objects
                inventory = json.loads(Path(inventory_path).read_text())
                by_type = defaultdict(list)
                expected = set()
                for index, resource in enumerate(inventory):
                    by_type[resource["resource_type"]].append((resource["resource_ref"], index))
                    if resource["owner_subject"] == session["keycloak_subject"]:
                        expected.add(index)
                token = next(c["value"] for c in context.cookies(manager) if c["name"] == "ft-manager-session")
                actual = set()
                for resource_type, refs in by_type.items():
                    actual.update(keycloak_authorized_objects(
                        token, resource_type=resource_type, refs=refs, scope="read"))
                if actual != expected:
                    raise SystemExit(f"Existing object permission mismatch (missing={len(expected-actual)}, unexpected={len(actual-expected)})")
                checks.append(f"owner_only_inventory_verified:{len(inventory)}")
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
        cause = exc.__cause__
        status = getattr(cause, "code", None)
        suffix = f" (upstream HTTP {status})" if isinstance(status, int) else ""
        raise SystemExit(f"Browser acceptance failed: {type(exc).__name__}{suffix}") from None

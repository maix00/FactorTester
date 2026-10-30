#!/usr/bin/env python3
"""Verify source-side public-login gating in an isolated Keycloak realm.

The cached Keycloak image is required. No deployed realm, user, credential,
or data is read or modified. The isolated broker flow does not verify direct
local-password login, object permissions, or production identity federation.
"""
from __future__ import annotations

import json
import secrets
import threading
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import sync_playwright

from scripts.test.keycloak_cross_realm_smoke import Sandbox
from server.identity.keycloak import jwt_claims


def run(sandbox: Sandbox) -> dict[str, str]:
    realm = "lazy-source"
    password, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    sandbox.request("POST", "/admin/realms", token=sandbox.admin, body={
        "realm": realm, "enabled": True, "registrationAllowed": False, "sslRequired": "none",
    })
    profile = sandbox.api("GET", realm, "users/profile")
    profile["attributes"].append({
        "name": "tr_identity_sync_enabled", "displayName": "Organization sync",
        "permissions": {"view": ["admin"], "edit": ["admin"]},
    })
    profile["attributes"].append({
        "name": "tr_identity_id", "displayName": "Stable identity",
        "permissions": {"view": ["admin"], "edit": ["admin"]},
    })
    profile["unmanagedAttributePolicy"] = "ADMIN_EDIT"
    sandbox.api("PUT", realm, "users/profile", profile)
    sandbox.api("POST", realm, "clients", {
        "clientId": "tr-manager", "enabled": True, "protocol": "openid-connect",
    })
    manager_id = sandbox.find(realm, "clients?" + urlencode({"clientId": "tr-manager"}),
                              "tr-manager", field="clientId")["id"]
    sandbox.api("POST", realm, f"clients/{manager_id}/roles", {"name": "public_server:login"})
    role = sandbox.find(realm, f"clients/{manager_id}/roles", "public_server:login")
    sandbox.api("POST", realm, "clients", {
        "clientId": "public-broker", "enabled": True, "protocol": "openid-connect",
        "publicClient": False, "secret": secret, "directAccessGrantsEnabled": True,
        "standardFlowEnabled": True, "fullScopeAllowed": False,
        "redirectUris": ["http://localhost:8080/realms/lazy-target/broker/organization/endpoint"],
    })
    broker_id = sandbox.find(realm, "clients?" + urlencode({"clientId": "public-broker"}),
                             "public-broker", field="clientId")["id"]
    sandbox.api("POST", realm, "client-scopes", {"name": "public-identity-eligibility", "protocol": "openid-connect"})
    scope_id = sandbox.find(realm, "client-scopes", "public-identity-eligibility")["id"]
    sandbox.api("POST", realm, f"client-scopes/{scope_id}/scope-mappings/clients/{manager_id}", [role])
    sandbox.api("POST", realm, f"client-scopes/{scope_id}/protocol-mappers/models", {
        "name": "organization-sync-enabled", "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-attribute-mapper",
        "config": {"user.attribute": "tr_identity_sync_enabled", "claim.name": "tr_identity_sync_enabled",
                   "jsonType.label": "String", "multivalued": "true", "aggregate.attrs": "true",
                   "id.token.claim": "true", "access.token.claim": "true"},
    })
    sandbox.api("POST", realm, f"client-scopes/{scope_id}/protocol-mappers/models", {
        "name": "stable-identity", "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-attribute-mapper",
        "config": {"user.attribute": "tr_identity_id", "claim.name": "tr_identity_id",
                   "jsonType.label": "String", "id.token.claim": "true", "access.token.claim": "true"},
    })
    sandbox.api("PUT", realm, f"clients/{broker_id}/default-client-scopes/{scope_id}")
    sandbox.api("POST", realm, "groups", {
        "name": "organization", "attributes": {"tr_identity_sync_enabled": ["true"]},
    })
    group = sandbox.find(realm, "groups", "organization")
    for username in ("eligible", "not-eligible"):
        sandbox.api("POST", realm, "users", {
            "username": username, "enabled": True, "emailVerified": True,
            "firstName": "Temporary", "lastName": "User", "email": username + "@example.invalid",
            "attributes": {"tr_identity_id": ["stable-" + username]},
            "credentials": [{
                "type": "password", "value": password, "temporary": False,
            }],
        })
    users = {name: sandbox.find(realm, "users?" + urlencode({"username": name, "exact": "true"}),
                                name, field="username") for name in ("eligible", "not-eligible")}
    for user in users.values():
        sandbox.api("PUT", realm, f"users/{user['id']}/groups/{group['id']}")
    sandbox.api("POST", realm, f"users/{users['eligible']['id']}/role-mappings/clients/{manager_id}", [role])

    def claims(username: str) -> dict:
        result = sandbox.request("POST", f"/realms/{realm}/protocol/openid-connect/token", form={
            "grant_type": "password", "client_id": "public-broker", "client_secret": secret,
            "scope": "openid", "username": username, "password": password,
        })
        return jwt_claims(result["id_token"])

    assert claims("eligible").get("tr_identity_sync_enabled") == ["true"]
    assert "tr_identity_sync_enabled" not in claims("not-eligible")
    sandbox.api("PUT", realm, f"groups/{group['id']}", {
        "id": group["id"], "name": "organization", "attributes": {"tr_identity_sync_enabled": ["false"]},
    })
    assert claims("eligible").get("tr_identity_sync_enabled") == ["false"]
    sandbox.api("DELETE", realm, f"users/{users['eligible']['id']}/role-mappings/clients/{manager_id}", [role])
    assert "tr_identity_sync_enabled" not in claims("eligible")
    # Restore eligibility to exercise actual Keycloak identity brokering.
    sandbox.api("PUT", realm, f"groups/{group['id']}", {
        "id": group["id"], "name": "organization", "attributes": {"tr_identity_sync_enabled": ["true"]},
    })
    sandbox.api("POST", realm, f"users/{users['eligible']['id']}/role-mappings/clients/{manager_id}", [role])
    broker_login(sandbox, password=password, secret=secret, users=users,
                 group=group, manager_id=manager_id, role=role)
    return {"eligible": "claim present", "missing_public_role": "claim absent",
            "organization_disabled": "claim false", "role_revoked": "claim absent",
            "broker_login": "verified", "broker_revoke": "denied",
            "same_username_collision": "not automatically linked",
            "profile_update": "on next broker login"}


def broker_login(sandbox: Sandbox, *, password: str, secret: str, users: dict,
                 group: dict, manager_id: str, role: dict) -> None:
    """Prove an eligible user is created at login and an ineligible one is not."""
    realm, source = "lazy-target", "http://localhost:8080/realms/lazy-source"
    target = "http://localhost:8080/realms/" + realm
    sandbox.request("POST", "/admin/realms", token=sandbox.admin, body={
        "realm": realm, "enabled": True, "registrationAllowed": False, "sslRequired": "none",
    })
    profile = sandbox.api("GET", realm, "users/profile")
    profile["attributes"].append({"name": "tr_identity_id", "displayName": "Stable identity",
                                  "permissions": {"view": ["admin"], "edit": ["admin"]}})
    profile["unmanagedAttributePolicy"] = "ADMIN_EDIT"
    sandbox.api("PUT", realm, "users/profile", profile)
    sandbox.api("POST", realm, "clients", {"clientId": "browser", "enabled": True,
        "protocol": "openid-connect", "publicClient": True, "standardFlowEnabled": True,
        "redirectUris": ["http://localhost:8080/qa/callback"]})
    sandbox.api("POST", realm, "identity-provider/instances", {
        "alias": "organization", "providerId": "oidc", "enabled": True, "trustEmail": False,
        "storeToken": False, "config": {
            "issuer": source, "authorizationUrl": source + "/protocol/openid-connect/auth",
            "tokenUrl": source + "/protocol/openid-connect/token",
            "userInfoUrl": source + "/protocol/openid-connect/userinfo",
            "jwksUrl": source + "/protocol/openid-connect/certs", "useJwksUrl": "true",
            "validateSignature": "true", "clientId": "public-broker", "clientSecret": secret,
            "filteredByClaim": "true", "claimFilterName": "tr_identity_sync_enabled",
            "claimFilterValue": "^true$", "syncMode": "FORCE",
        },
    })
    sandbox.api("POST", realm, "identity-provider/instances/organization/mappers", {
        "name": "stable-identity", "identityProviderAlias": "organization",
        "identityProviderMapper": "oidc-user-attribute-idp-mapper",
        "config": {"syncMode": "FORCE", "claim": "tr_identity_id", "user.attribute": "tr_identity_id"},
    })
    # Same username is not proof of the same person across realms.
    for selected_realm, stable in (("lazy-source", "source-distinct"), (realm, "target-distinct")):
        sandbox.api("POST", selected_realm, "users", {
            "username": "collision", "enabled": True, "emailVerified": True,
            "firstName": "Temporary", "lastName": "User", "email": "collision@example.invalid",
            "attributes": {"tr_identity_id": [stable]},
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        })
    source_collision = sandbox.find("lazy-source", "users?" + urlencode({"username": "collision", "exact": "true"}),
                                    "collision", field="username")
    target_collision = sandbox.find(realm, "users?" + urlencode({"username": "collision", "exact": "true"}),
                                    "collision", field="username")
    sandbox.api("PUT", "lazy-source", f"users/{source_collision['id']}/groups/{group['id']}")
    sandbox.api("POST", "lazy-source", f"users/{source_collision['id']}/role-mappings/clients/{manager_id}", [role])
    authorization = target + "/protocol/openid-connect/auth?" + urlencode({
        "client_id": "browser", "response_type": "code", "scope": "openid",
        "redirect_uri": "http://localhost:8080/qa/callback", "state": secrets.token_urlsafe(16),
        "kc_idp_hint": "organization",
    })
    # The isolated container's canonical issuer is localhost:8080, while its
    # published port is random. This loopback-only relay preserves that issuer
    # for the browser; it never logs requests and is removed after the test.
    upstream = urlsplit(sandbox.base)
    class Relay(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def relay(self):
            if urlsplit(self.path).path == "/qa/callback":
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            connection = HTTPConnection(upstream.hostname, upstream.port, timeout=15)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else None
                headers = {key: value for key, value in self.headers.items()
                           if key.lower() not in {"connection", "host", "transfer-encoding"}}
                headers["Host"] = "localhost:8080"
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                self.send_response_only(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in {"connection", "transfer-encoding"}:
                        self.send_header(key, value)
                self.end_headers()
                self.wfile.write(response.read())
            finally:
                connection.close()

        do_GET = relay
        do_POST = relay

    relay = ThreadingHTTPServer(("127.0.0.1", 8080), Relay)
    thread = threading.Thread(target=relay.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                def attempt(username: str, should_login: bool) -> list[dict]:
                    context = browser.new_context()
                    try:
                        page = context.new_page()
                        page.set_default_timeout(8000)
                        page.goto(authorization)
                        page.locator("#username").fill(username)
                        page.locator("#password").fill(password)
                        page.locator("#kc-login").click()
                        if should_login:
                            page.wait_for_url("**/qa/callback?**", timeout=12000)
                        else:
                            page.get_by_text("does not match the configured essential claim", exact=False).wait_for(timeout=12000)
                        return sandbox.api("GET", realm, "users?" + urlencode({"username": username, "exact": "true"}))
                    finally:
                        context.close()

                assert sandbox.api("GET", realm, "users?" + urlencode({"username": "eligible", "exact": "true"})) == []
                assert attempt("not-eligible", False) == []
                found = attempt("eligible", True)
                assert len(found) == 1
                assert (found[0].get("attributes") or {}).get("tr_identity_id") == ["stable-eligible"]

                # Existing broker links must also recheck source grants at the
                # next login; they must not create or silently relink users.
                source_user = users["eligible"]
                role_path = f"users/{source_user['id']}/role-mappings/clients/{manager_id}"
                sandbox.api("DELETE", "lazy-source", role_path, [role])
                assert len(attempt("eligible", False)) == 1
                sandbox.api("POST", "lazy-source", role_path, [role])
                sandbox.api("PUT", "lazy-source", f"groups/{group['id']}", {
                    "id": group["id"], "name": "organization", "attributes": {"tr_identity_sync_enabled": ["false"]},
                })
                assert len(attempt("eligible", False)) == 1
                sandbox.api("PUT", "lazy-source", f"groups/{group['id']}", {
                    "id": group["id"], "name": "organization", "attributes": {"tr_identity_sync_enabled": ["true"]},
                })
                updated = sandbox.api("GET", "lazy-source", f"users/{source_user['id']}")
                updated["firstName"] = "Updated"
                sandbox.api("PUT", "lazy-source", f"users/{source_user['id']}", updated)
                found = attempt("eligible", True)
                assert len(found) == 1 and found[0].get("firstName") == "Updated"

                context = browser.new_context()
                try:
                    page = context.new_page()
                    page.set_default_timeout(8000)
                    page.goto(authorization)
                    page.locator("#username").fill("collision")
                    page.locator("#password").fill(password)
                    page.locator("#kc-login").click()
                    page.wait_for_url("**/realms/lazy-target/login-actions/**", timeout=12000)
                    assert urlsplit(page.url).path != "/qa/callback"
                    assert sandbox.api("GET", realm, f"users/{target_collision['id']}/federated-identity") == []
                    target_row = sandbox.api("GET", realm, f"users/{target_collision['id']}")
                    assert (target_row.get("attributes") or {}).get("tr_identity_id") == ["target-distinct"]
                finally:
                    context.close()
            finally:
                browser.close()
    finally:
        relay.shutdown()
        relay.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    with Sandbox() as sandbox:
        result = run(sandbox)
    print(json.dumps({**result, "temporary_container_removed": True}, sort_keys=True))

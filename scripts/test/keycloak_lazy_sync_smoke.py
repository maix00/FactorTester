#!/usr/bin/env python3
"""Verify source-side public-login gating in an isolated Keycloak realm.

The cached Keycloak image is required. No deployed realm, user, credential,
or data is read or modified. This is one part of the broker acceptance, not a
claim that cross-Manager identity synchronization is already connected.
"""
from __future__ import annotations

import json
import secrets
from urllib.parse import urlencode

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
        "fullScopeAllowed": False,
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
    sandbox.api("PUT", realm, f"clients/{broker_id}/default-client-scopes/{scope_id}")
    sandbox.api("POST", realm, "groups", {
        "name": "organization", "attributes": {"tr_identity_sync_enabled": ["true"]},
    })
    group = sandbox.find(realm, "groups", "organization")
    for username in ("eligible", "not-eligible"):
        sandbox.api("POST", realm, "users", {
            "username": username, "enabled": True, "emailVerified": True,
            "firstName": "Temporary", "lastName": "User", "email": username + "@example.invalid",
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
    return {"eligible": "claim present", "missing_public_role": "claim absent",
            "organization_disabled": "claim false", "role_revoked": "claim absent"}


if __name__ == "__main__":
    with Sandbox() as sandbox:
        result = run(sandbox)
    print(json.dumps({**result, "temporary_container_removed": True}, sort_keys=True))

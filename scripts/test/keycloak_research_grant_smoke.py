#!/usr/bin/env python3
"""Exercise Research explicit grants against a disposable local Keycloak.

No existing realm is modified and no image or Python package is downloaded.
The Profile-membership provider is a denial-only test double: the exercised
Research grant, token introspection, UMA decisions and SQLite catalog are real.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from scripts.test.keycloak_cross_realm_smoke import Sandbox
from server.identity.keycloak import ServiceOIDCClient
from server.identity.keycloak_authorization import ensure_keycloak_resource
from server.identity.keycloak_research import KeycloakResearchAuthorization, KeycloakResearchGrantManager
from server.identity.request_context import bind_verified_identity, identity_request
from server.manager.services.research_catalog import ResearchCatalog


class NoProfileGrants:
    def profile_membership_access_many(self, *, viewer, profiles):
        return {pair: {"can_view": False, "can_download": False} for pair in profiles}


def run(sandbox):
    realm, client_id = "research-grant", "research-client"
    secret, password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    sandbox.request("POST", "/admin/realms", token=sandbox.admin, body={
        "realm": realm, "enabled": True, "sslRequired": "none", "registrationAllowed": False,
    })
    profile = sandbox.api("GET", realm, "users/profile")
    profile["attributes"].append({"name": "tr_identity_id", "displayName": "Stable ID",
                                  "permissions": {"view": ["admin"], "edit": ["admin"]}})
    sandbox.api("PUT", realm, "users/profile", profile)
    sandbox.api("POST", realm, "clients", {"clientId": client_id, "enabled": True,
        "protocol": "openid-connect", "publicClient": False, "secret": secret,
        "directAccessGrantsEnabled": True, "serviceAccountsEnabled": True,
        "authorizationServicesEnabled": True})
    client_row = sandbox.find(realm, "clients?" + urlencode({"clientId": client_id}), client_id, field="clientId")
    sandbox.api("POST", realm, "clients/" + client_row["id"] + "/protocol-mappers/models", {
        "name": "stable-id", "protocol": "openid-connect", "protocolMapper": "oidc-usermodel-attribute-mapper",
        "config": {"user.attribute": "tr_identity_id", "claim.name": "tr_identity_id",
                   "jsonType.label": "String", "access.token.claim": "true", "introspection.token.claim": "true"},
    })
    sandbox.api("POST", realm, "clients/" + client_row["id"] + "/protocol-mappers/models", {
        "name": "client-audience", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
        "config": {"included.client.audience": client_id, "access.token.claim": "true"},
    })
    for name in ("owner", "member"):
        sandbox.api("POST", realm, "users", {"username": name, "enabled": True, "emailVerified": True,
            "firstName": "Temporary", "lastName": "User", "email": name + "@example.invalid",
            "attributes": {"tr_identity_id": ["stable-" + name]},
            "credentials": [{"type": "password", "value": password, "temporary": False}]})
    users = {name: sandbox.find(realm, "users?" + urlencode({"username": name, "exact": "true"}),
                                name, field="username") for name in ("owner", "member")}
    client = ServiceOIDCClient(sandbox.base, realm, client_id, client_secret=secret)
    issuer = "http://localhost:8080/realms/" + realm
    sessions = {}
    for name, row in users.items():
        token = client._token({"grant_type": "password", "client_id": client_id,
                               "username": name, "password": password})["access_token"]
        claims = client.introspect(token)
        if (claims.get("active") is not True or claims.get("iss") != issuer
                or claims.get("sub") != row["id"] or claims.get("tr_identity_id") != "stable-" + name):
            raise AssertionError("temporary token introspection checks failed: " + str({
                "active": claims.get("active") is True, "issuer": claims.get("iss") == issuer,
                "subject": claims.get("sub") == row["id"],
                "stable": claims.get("tr_identity_id") == "stable-" + name}))
        sessions[name] = (token, {"username": name, "keycloak_issuer": issuer,
                                  "keycloak_subject": row["id"], "tr_identity_id": "stable-" + name})
    settings = {"base_url": sandbox.base, "realm": realm, "authz_client_id": client_id,
                "authz_client_secret": secret}
    def by_identity(stable):
        rows = [sandbox.api("GET", realm, "users/" + row["id"]) for row in users.values()]
        matched = [row for row in rows if (row.get("attributes") or {}).get("tr_identity_id") == [stable]]
        if len(matched) != 1:
            raise LookupError("ambiguous temporary identity")
        return matched[0]
    class Directory:
        def _get(self, path):
            return sandbox.api("GET", realm, path)
        def user_by_identity_id(self, stable):
            return by_identity(stable)
    manager = KeycloakResearchGrantManager(settings_provider=lambda: settings,
        user_provider=lambda subject: sandbox.api("GET", realm, "users/" + subject),
        user_by_identity=by_identity)
    resolver = lambda name: {"identity_id": "stable-" + name, "subject": users[name]["id"]}
    with tempfile.TemporaryDirectory(prefix="tr-research-grants-") as root, \
            patch("server.identity.keycloak_authorization.oidc_settings", lambda: settings), \
            patch("server.identity.federation_identity_sync.manager_keycloak_admin_adapter", Directory):
        database = Path(root) / "catalog.sqlite"
        legacy = ResearchCatalog(database)
        research = legacy.create_research(owner_ref="owner", title="Temporary")
        ref = research["research_id"]
        ensure_keycloak_resource(resource_type="research", resource_ref=ref, owner_subject=users["owner"]["id"])
        catalog = ResearchCatalog(database, research_authorizer=KeycloakResearchAuthorization(),
            profile_authorizer=NoProfileGrants(), profile_grant_manager=manager,
            profile_identity_resolver=resolver)
        with identity_request():
            bind_verified_identity(*sessions["member"])
            assert catalog.list_researches(viewer="member") == []
        with identity_request():
            bind_verified_identity(*sessions["owner"])
            catalog.set_explicit_grant(ref, actor="owner", principal_ref="member", scopes=["read", "use"])
            grants = catalog.list_explicit_grants(ref, actor="owner")
            assert len(grants) == 1 and grants[0]["identity_id"] == "stable-member"
        with identity_request():
            bind_verified_identity(*sessions["member"])
            assert len(catalog.list_researches(viewer="member")) == 1
        with identity_request():
            bind_verified_identity(*sessions["owner"])
            catalog.set_explicit_grant(ref, actor="owner", principal_ref="member", scopes=[])
            assert catalog.list_explicit_grants(ref, actor="owner") == []
        with identity_request():
            # Deliberately reuse the same previously issued token after revoke.
            bind_verified_identity(*sessions["member"])
            assert catalog.list_researches(viewer="member") == []
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT authorized_users_json FROM research_catalog_researches").fetchone()[0] == "[]"
    return {"real_keycloak": True, "real_catalog": True, "same_token_revocation": True,
            "legacy_acl_written": False, "profile_membership_provider": "denial-only test double"}


if __name__ == "__main__":
    with Sandbox() as server:
        print(json.dumps(run(server), sort_keys=True))

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
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from scripts.test.keycloak_cross_realm_smoke import Sandbox
from server.identity.keycloak import ServiceOIDCClient
from server.identity.keycloak_authorization import ensure_keycloak_resource
from server.identity.keycloak_policy_evaluation import KeycloakPolicyEvaluator
from server.identity.keycloak_research import KeycloakResearchAuthorization, KeycloakResearchGrantManager
from server.identity.request_context import bind_verified_identity, identity_request
from scripts.test.historical_research_catalog import HistoricalResearchCatalog as ResearchCatalog


class NoProfileGrants:
    def profile_membership_access_many(self, *, viewer, profiles):
        return {pair: {"can_view": False, "can_download": False} for pair in profiles}


def run(sandbox, *, on_ready=None):
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
    for name in ("owner", "member", "late"):
        sandbox.api("POST", realm, "users", {"username": name, "enabled": True, "emailVerified": True,
            "firstName": "Temporary", "lastName": "User", "email": name + "@example.invalid",
            "attributes": {"tr_identity_id": ["stable-" + name]},
            "credentials": [{"type": "password", "value": password, "temporary": False}]})
    users = {name: sandbox.find(realm, "users?" + urlencode({"username": name, "exact": "true"}),
                                name, field="username") for name in ("owner", "member", "late")}
    if on_ready is not None:
        sandbox.api("POST", realm, "clients/" + client_row["id"] + "/roles", {"name": "public_server:login"})
        public_role = sandbox.api("GET", realm, "clients/" + client_row["id"] + "/roles/public_server%3Alogin")
        sandbox.api("POST", realm, "users/" + users["owner"]["id"] + "/role-mappings/clients/" + client_row["id"],
                    [public_role])
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
    def evaluator():
        return KeycloakPolicyEvaluator(allowed_kinds={"research", "research_report"},
            allowed_scopes={"read", "manage", "share"}, adapter=Directory(), settings=settings,
            request=lambda _adapter, client_uuid, body: sandbox.api("POST", realm,
                f"clients/{client_uuid}/authz/resource-server/policy/evaluate", body))
    manager = KeycloakResearchGrantManager(settings_provider=lambda: settings,
        user_provider=lambda subject: sandbox.api("GET", realm, "users/" + subject),
        user_by_identity=by_identity, link_policy_evaluator=evaluator)
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
        if on_ready is not None:
            on_ready(sandbox=sandbox, realm=realm, client_id=client_id, client_uuid=client_row['id'],
                     client=client, issuer=issuer, sessions=sessions, settings=settings, users=users,
                     manager=manager, catalog=catalog, research_id=ref, public_role=public_role)
        with identity_request():
            bind_verified_identity(*sessions["owner"])
            created = catalog.create_research(owner_ref="owner", title="Keycloak-created Research")
            assert created["access"]["can_manage"] is True
            try:
                catalog.create_research(owner_ref="owner", title="Must not be public", visibility="public")
            except ValueError:
                pass
            else:
                raise AssertionError("strict Research creation accepted a legacy public ACL")
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
            # Exercise the actual page-assistance workspace handler against
            # the same live Keycloak grant. Agent runtime admission is a test
            # double here; the authorization and workspace store are real.
            from server.manager.http import page_assistance_routes as routes
            store, replies = routes.PageAssistanceStore(), []
            class Handler(routes.PageAssistanceRoutesMixin):
                body = {"profile_id": "self"}
                def _agent_app_profile(self, _profile): return "member", "self"
                def _assistance_profile(self, _profile, workspace_id):
                    return "member", "self", workspace_id
                def _json_body(self, _maximum): return self.body
                def _research_catalog_service(self): return catalog
                def _agent_app_error(self, exc): raise exc
            handler = Handler()
            with patch.object(routes, "_STORE", store), patch.object(routes, "json_response",
                    lambda _handler, value, status=200: replies.append((value, status))):
                handler._post_page_assistance_routes(SimpleNamespace(
                    path="/api/client/profile-agent/assistance/workspaces"))
                workspace_id = replies[-1][0]["workspace_id"]
                handler.body = {"profile_id": "self", "workspace_id": workspace_id, "tab_id": "page",
                    "workspace": {"client_revision": 1, "active_tab_id": "page", "tabs": [{
                        "tab_id": "page", "research_id": ref, "assistance": {"schema_version": 1,
                            "page_kind": "research", "revision": 0,
                            "navigation": {"schema_version": 1, "root_id": "root", "nodes": {
                                "root": {"id": "root", "kind": "page", "children": []}}},
                            "document_schema": {"type": "object", "readOnly": True},
                            "document": {"research_id": ref}}}]}}
                handler._post_page_assistance_routes(SimpleNamespace(
                    path="/api/client/profile-agent/assistance/publish"))
                assert replies[-1][1] == 200 and replies[-1][0]["page"] is not None
        with identity_request():
            bind_verified_identity(*sessions["owner"])
            catalog.set_explicit_grant(ref, actor="owner", principal_ref="member", scopes=[])
            assert catalog.list_explicit_grants(ref, actor="owner") == []
        with identity_request():
            # Deliberately reuse the same previously issued token after revoke.
            bind_verified_identity(*sessions["member"])
            assert catalog.list_researches(viewer="member") == []
            with patch.object(routes, "_STORE", store), patch.object(routes, "json_response",
                    lambda _handler, value, status=200: replies.append((value, status))):
                handler._get_page_assistance_routes(SimpleNamespace(
                    path="/api/client/profile-agent/assistance",
                    query=urlencode({"profile_id": "self", "workspace_id": workspace_id})))
                assert replies[-1][1] == 200 and replies[-1][0]["page"] is None
        with identity_request():
            bind_verified_identity(*sessions["owner"])
            link = catalog.create_share_link(target_kind="research", research_id=ref, actor="owner")
        with identity_request():
            bind_verified_identity(*sessions["member"])
            started = time.perf_counter()
            assert catalog.redeem_share_link(link["token"], actor="member")["research_id"] == ref
            redemption_seconds = time.perf_counter() - started
            assert len(catalog.list_researches(viewer="member")) == 1

        # Remove the issuer's Keycloak share scope without changing the link.
        # The next claimant must fail under a live Policy Evaluation decision.
        pat = manager.token_provider(settings)
        resource = manager._resource(settings, pat, "research", ref)
        resource_id = str(resource.get("_id") or resource.get("id"))
        owners = [row for row in manager._resource_policies(settings, pat, resource_id)
                  if str(row.get("name") or "").endswith(":owner")]
        assert len(owners) == 1 and "share" in owners[0]["scopes"]
        owner_policy = owners[0]
        original = {"name": owner_policy["name"], "description": owner_policy["description"],
                    "users": [users["owner"]["id"]], "scopes": owner_policy["scopes"], "logic": "POSITIVE"}
        def owned_refs():
            cursor = {'updated_at': 0, 'research_id': ''}
            refs = []
            while cursor is not None:
                page = catalog.owned_sync_page(viewer='owner', after_time=cursor['updated_at'],
                                               after_ref=cursor['research_id'], limit=1)
                refs.extend(item['research_id'] for item in page['researches'])
                cursor = page['next_cursor']
            return refs
        with identity_request():
            bind_verified_identity(*sessions['owner'])
            assert set(owned_refs()) == {ref, created['research_id']}
        without_read = {**original, 'scopes': [scope for scope in original['scopes'] if scope != 'read']}
        manager.request(settings, pat, 'PUT', 'uma-policy/' + owner_policy['id'], without_read)
        with identity_request():
            # The same token is intentionally reused: ownership alone must
            # never bypass the current Keycloak read decision.
            bind_verified_identity(*sessions['owner'])
            assert ref not in owned_refs()
        manager.request(settings, pat, 'PUT', 'uma-policy/' + owner_policy['id'], original)
        without_share = {**original, "scopes": [scope for scope in original["scopes"] if scope != "share"]}
        manager.request(settings, pat, "PUT", "uma-policy/" + owner_policy["id"], without_share)
        with identity_request():
            bind_verified_identity(*sessions["late"])
            try:
                catalog.redeem_share_link(link["token"], actor="late")
            except PermissionError:
                pass
            else:
                raise AssertionError("revoked issuer share scope allowed link redemption")
        manager.request(settings, pat, "PUT", "uma-policy/" + owner_policy["id"], original)
        with identity_request():
            bind_verified_identity(*sessions["owner"])
            catalog.revoke_share_link(ref, link["link_id"], actor="owner")
        with identity_request():
            bind_verified_identity(*sessions["late"])
            try:
                catalog.redeem_share_link(link["token"], actor="late")
            except KeyError:
                pass
            else:
                raise AssertionError("revoked link was redeemed")
        with sqlite3.connect(database) as db:
            assert {row[0] for row in db.execute("SELECT authorized_users_json FROM research_catalog_researches")} == {"[]"}
            assert db.execute("SELECT count(*) FROM research_catalog_researches WHERE title='Must not be public'").fetchone()[0] == 0
    return {"real_keycloak": True, "real_catalog": True, "same_token_revocation": True,
            "revoked_page_context_removed": True, "real_link_redemption": True,
            "issuer_and_link_revocation": True, "real_research_creation": True, "legacy_acl_written": False,
            "owned_discovery_real_keycloak_revocation": True,
            "local_redeem_seconds": round(redemption_seconds, 3),
            "profile_membership_provider": "denial-only test double", "agent_runtime_admission": "test double"}


if __name__ == "__main__":
    with Sandbox() as server:
        print(json.dumps(run(server), sort_keys=True))

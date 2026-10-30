"""Opt-in Keycloak 26 integration in a newly created disposable realm.

The test only deletes the randomly named realm it created itself. Set the
protected bootstrap env file and local test Keycloak URL explicitly to run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import time
from types import SimpleNamespace
import urllib.error
import urllib.parse
import urllib.request
import uuid

import pytest

from scripts.migrations import keycloak_server_admission as migration
from server.identity import federation_identity_sync as federation
from server.identity import server_admission as access
from server.identity.keycloak import KeycloakAdminAdapter, ServiceOIDCClient
from server.identity.keycloak_hierarchy_admin import KeycloakHierarchyProvisioner
from server.identity.keycloak_profile import configure_identity_mappers, protect_identity_attributes
from server.identity.realm_groups import organization_group_path
from server.identity.user_session import UserSessionVerifier
from server.manager.domain.federation.registry import FederatedServerRegistry
from server.manager.http.federation import admin as federation_admin
from server.manager.http.federation.admin import FederationAdminRoutesMixin
from server.manager.transfers.node_advertisements import signed_advertisement
from server.manager.transfers.node_keys import NodeKey
from tests.federation_fixtures import federation_registration


@pytest.mark.skipif(
    not os.getenv("TR_TEST_KEYCLOAK_BOOTSTRAP_FILE") or not os.getenv("TR_TEST_KEYCLOAK_URL"),
    reason="requires an explicitly selected disposable-realm Keycloak",
)
def test_real_keycloak_admission_apply_revoke_and_rollback(tmp_path, monkeypatch):
    base = os.environ["TR_TEST_KEYCLOAK_URL"].rstrip("/")
    values = dict(line.split("=", 1) for line in
                  Path(os.environ["TR_TEST_KEYCLOAK_BOOTSTRAP_FILE"]).read_text().splitlines()
                  if "=" in line)
    credentials = urllib.parse.urlencode({
        "grant_type": "password", "client_id": "admin-cli",
        "username": values["TR_IDENTITY_BOOTSTRAP_USER"],
        "password": values["TR_IDENTITY_BOOTSTRAP_PASSWORD"],
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(
        base + "/realms/master/protocol/openid-connect/token", data=credentials, method="POST",
    ), timeout=10) as response:
        token = json.load(response)["access_token"]

    def request(method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Authorization": "Bearer " + token,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status

    realm = "tr-admission-test-" + uuid.uuid4().hex[:16]
    assert request("POST", "/admin/realms", {
        "realm": realm, "enabled": True, "adminPermissionsEnabled": True,
    }) == 201
    try:
        admin = KeycloakAdminAdapter(base, realm)
        monkeypatch.setattr(admin, "_token", lambda: token)
        provisioner = KeycloakHierarchyProvisioner(admin)
        provisioner.enable_admin_permissions()
        protect_identity_attributes(admin)
        orgpath = organization_group_path("org-a")
        groups, _ = provisioner.ensure_groups([
            "/traderesearch", "/traderesearch/organizations", orgpath,
        ])
        org_id = groups[orgpath]

        def create_client(name, secret, service=False):
            status, location = admin._post("clients", {
                "clientId": name, "enabled": True, "protocol": "openid-connect",
                "publicClient": False, "secret": secret,
                "serviceAccountsEnabled": service, "standardFlowEnabled": False,
                "directAccessGrantsEnabled": name == "tr-manager",
            })
            assert status == 201
            return location.rstrip("/").rsplit("/", 1)[-1]

        login_secret = secrets.token_urlsafe(32)
        directory_secret = secrets.token_urlsafe(32)
        login = create_client("tr-manager", login_secret)
        directory = create_client("tr-directory", directory_secret, True)
        other = create_client("unrelated-client", secrets.token_urlsafe(32))
        configure_identity_mappers(admin, "tr-manager")
        provisioner.ensure_group_claim_mapper(["tr-manager"])
        service_subject = admin._get("clients/" + directory + "/service-account-user")["id"]
        realm_clients = admin._get("clients?" + urllib.parse.urlencode({"clientId": "realm-management"}))
        realm_management = next(row["id"] for row in realm_clients if row.get("clientId") == "realm-management")
        roles = [admin._get("clients/" + realm_management + "/roles/" + name)
                 for name in ("query-groups", "query-users", "view-users")]
        admin._post("users/" + service_subject + "/role-mappings/clients/" + realm_management, roles)
        password = secrets.token_urlsafe(32)
        _, location = admin._post("users", {
            "username": "probe", "enabled": True,
            "attributes": {"tr_organization_id": ["org-a"]},
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        })
        user = location.rstrip("/").rsplit("/", 1)[-1]
        assert admin._get("users/" + user).get("attributes", {}).get("tr_organization_id") == ["org-a"]
        admin._put("users/" + user + "/groups/" + org_id, {})
        admin._post("clients/" + login + "/roles", {"name": "public_server:login"})
        role = admin._get("clients/" + login + "/roles/" + urllib.parse.quote("public_server:login", safe=""))
        admin._post("users/" + user + "/role-mappings/clients/" + login, [role])
        admin._post("clients/" + login + "/roles", {"name": "admin_console:manage"})
        admin_role = admin._get("clients/" + login + "/roles/" + urllib.parse.quote("admin_console:manage", safe=""))
        admin._post("users/" + user + "/role-mappings/clients/" + login, [admin_role])
        directory_adapter = KeycloakAdminAdapter(base, realm, client_id="tr-directory", client_secret=directory_secret)
        with urllib.request.urlopen(base + "/realms/" + realm + "/.well-known/openid-configuration",
                                    timeout=10) as response:
            issuer = json.load(response)["issuer"]
        monkeypatch.setattr(access, "oidc_settings", lambda: {
            "issuer": issuer, "client_id": "tr-manager", "roles_client_id": "tr-manager",
        })
        monkeypatch.setattr(federation, "manager_keycloak_admin_adapter", lambda: directory_adapter)
        login_form = urllib.parse.urlencode({"grant_type": "password", "username": "probe",
                                             "password": password, "client_id": "tr-manager",
                                             "client_secret": login_secret}).encode()
        with urllib.request.urlopen(urllib.request.Request(
            base + "/realms/" + realm + "/protocol/openid-connect/token", data=login_form, method="POST",
        ), timeout=10) as response:
            user_token = json.load(response)["access_token"]
        verifier = UserSessionVerifier(ServiceOIDCClient(base, realm, "tr-manager",
                                                          client_secret=login_secret),
                                       issuer=issuer, audience="tr-manager")
        claims = verifier.client.introspect(user_token)
        assert claims.get("active") is True
        assert claims.get("iss") == issuer
        assert claims.get("sub") == user
        assert claims.get("preferred_username") == "probe"
        assert (claims.get("azp") == "tr-manager" or "tr-manager" in (claims.get("aud") or []))
        identity = verifier.session(user_token)
        assert identity and identity["keycloak_subject"] == user
        assert identity["organization_id"] == "org-a"
        assert orgpath in identity["keycloak_groups"]
        assert "public_server:login" in identity["keycloak_roles"]
        assert "admin_console:manage" in identity["keycloak_roles"]
        internal = SimpleNamespace(public_server=False, server_id="internal-a", managed_organizations=("org-a",))
        public = SimpleNamespace(public_server=True, server_id="public-a", managed_organizations=())

        access.clear_server_admission_cache()
        assert not access.server_admission(identity, state=internal)[0]
        node_key = NodeKey.load_or_create(tmp_path / "node-key.json", node_id="internal-a")
        node_fingerprint = node_key.fingerprint
        plan = migration.inspect_internal(admin, server_id="internal-a", organization_id="org-a",
                                          node_fingerprint=node_fingerprint)
        assert not plan["conflicts"]
        assert migration.apply(admin, plan, expected_sha256=plan["sha256"],
                               receipt=tmp_path / "internal.jsonl")["status"] == "verified"
        assert not migration.inspect_internal(admin, server_id="internal-a", organization_id="org-a",
                                              node_fingerprint=node_fingerprint)["changes"]
        access.clear_server_admission_cache()
        assert access.server_admission(identity, state=internal) == (True, "")
        assert access.federated_manager_binding("internal-a", "org-a", node_fingerprint)
        assert not access.federated_manager_binding("internal-a", "org-a", secrets.token_hex(32))
        migration._delete(admin, "users/" + user + "/groups/" + org_id)
        access.clear_server_admission_cache()
        assert not access.server_admission(identity, state=internal)[0]

        admin._put("users/" + user + "/groups/" + org_id, {})
        assert migration.rollback(admin, plan, expected_sha256=plan["sha256"],
                                  record=lambda _: None)["status"] == "rolled_back"
        assert migration._group(admin, access.manager_binding_group_path("internal-a")) is None
        access.clear_server_admission_cache()
        assert not access.server_admission(identity, state=internal)[0]

        # Keep the real org/key authority for the live manager-binding route
        # after exercising rollback; the prior signed advertisement is offline.
        internal_plan = migration.inspect_internal(admin, server_id="internal-a",
                                                   organization_id="org-a",
                                                   node_fingerprint=node_fingerprint)
        assert migration.apply(admin, internal_plan, expected_sha256=internal_plan["sha256"],
                               receipt=tmp_path / "internal-again.jsonl")["status"] == "verified"

        plan = migration.inspect_public(admin, server_id="public-a", directory_client_id="tr-directory",
                                        login_client_id="tr-manager", roles_client_id="tr-manager")
        assert not plan["conflicts"]
        assert migration.apply(admin, plan, expected_sha256=plan["sha256"],
                               receipt=tmp_path / "public.jsonl")["status"] == "verified"
        configured = migration.inspect_public(admin, server_id="public-a", directory_client_id="tr-directory",
                                              login_client_id="tr-manager", roles_client_id="tr-manager")
        assert not configured["changes"]
        # A negative policy would grant the wrong principals. Never adopt it
        # even if its target resource, scope and user policy appear correct.
        endpoint = ("clients/" + plan["permissions_uuid"] + "/authz/resource-server/permission/scope/"
                    + configured["permission"]["id"])
        permission = {**configured["permission"], "resources": [plan["target_uuid"]],
                      "scopes": ["view"], "policies": [plan["policy_name"]]}
        admin._put(endpoint, {**permission, "logic": "NEGATIVE"})
        conflict = migration.inspect_public(admin, server_id="public-a", directory_client_id="tr-directory",
                                            login_client_id="tr-manager", roles_client_id="tr-manager")
        assert "client_permission_conflict" in conflict["conflicts"]
        admin._put(endpoint, {**permission, "logic": "POSITIVE"})
        directory_adapter._token_value = ""  # refresh service role claims
        access.clear_server_admission_cache()
        assert access.server_admission(identity, state=public) == (True, "")
        assert access.current_manager_role(identity, "admin_console:manage")

        # Drive the real admin handler against the real isolated Keycloak
        # bindings and a real registry/SQLite audit, without changing either
        # deployment's realm or identity database.
        import settings
        monkeypatch.setattr(settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
        registry = FederatedServerRegistry(tmp_path / "registry.json")
        advertisement = signed_advertisement({
            "schema_version": 2, "node_id": "internal-a", "identity": node_key.public_record(),
            "client_control_endpoint": "https://node.example:7998",
            "client_data_endpoint": "https://node.example:7997",
            "peer_control_endpoint": "https://node.example:17998",
            "peer_data_endpoint": "https://node.example:17997",
            "issued_at": time.time() - 3600, "lease_seconds": 30.0,
            "nonce": "0123456789abcdef",
        }, node_key=node_key)
        row = federation_registration("internal-a", latency_ms=1, load=0)
        row.update(role="feat", public_server=False, managed_organizations=[],
                   transfer_node=advertisement)
        registry.register(row)
        state = SimpleNamespace(public_server=True, federation_registry=registry,
                                node_identities=SimpleNamespace(require=lambda _: node_key))
        replies = []
        monkeypatch.setattr(federation_admin, "json_response",
                            lambda _, value, status=200, **kw: replies.append((status, value)))

        class Handler(FederationAdminRoutesMixin):
            def __init__(self):
                self.state = state
                self.payload = {"server_id": "internal-a", "organization_id": "org-a",
                                "fingerprint": node_fingerprint}
            def _session(self):
                return identity
            def _has_secure_ui_transport(self):
                return True
            def _json_body(self, _):
                return self.payload

        handler = Handler()
        handler._bind_legacy_internal_manager()
        assert replies[-1][0] == 200 and replies[-1][1]["dry_run"]
        reviewed = replies[-1][1]["plan"]["record_sha256"]
        handler.payload.update(dry_run=False, expected_sha256=reviewed)
        handler._bind_legacy_internal_manager()
        assert replies[-1][0] == 200
        assert registry.describe("internal-a")["managed_organizations"] == ["org-a"]
        handler._bind_legacy_internal_manager()
        assert replies[-1][1]["binding"]["status"] == "already_bound"
        migration._delete(admin, "users/" + user + "/role-mappings/clients/" + login, [admin_role])
        assert not access.current_manager_role(identity, "admin_console:manage")
        handler._bind_legacy_internal_manager()
        assert replies[-1][0] == 403
        migration._delete(admin, "users/" + user + "/role-mappings/clients/" + login, [role])
        access.clear_server_admission_cache()
        assert not access.server_admission(identity, state=public)[0]
        with pytest.raises(urllib.error.HTTPError) as denied:
            directory_adapter._get("clients/" + other + "/installation/providers/keycloak-oidc-keycloak-json")
        assert denied.value.code == 403
        assert migration.rollback(admin, plan, expected_sha256=plan["sha256"],
                                  record=lambda _: None)["status"] == "rolled_back"
        directory_adapter._token_value = ""
        access.clear_server_admission_cache()
        assert not access.server_admission(identity, state=public)[0]
    finally:
        access.clear_server_admission_cache()
        assert request("DELETE", "/admin/realms/" + realm) == 204

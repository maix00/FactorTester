"""Opt-in Keycloak 26 integration in a newly created disposable realm.

The test only deletes the randomly named realm it created itself. Set the
protected bootstrap env file and local test Keycloak URL explicitly to run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
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
        internal = SimpleNamespace(public_server=False, server_id="internal-a", managed_organizations=("org-a",))
        public = SimpleNamespace(public_server=True, server_id="public-a", managed_organizations=())

        access.clear_server_admission_cache()
        assert not access.server_admission(identity, state=internal)[0]
        plan = migration.inspect_internal(admin, server_id="internal-a", organization_id="org-a")
        assert not plan["conflicts"]
        assert migration.apply(admin, plan, expected_sha256=plan["sha256"],
                               receipt=tmp_path / "internal.jsonl")["status"] == "verified"
        assert not migration.inspect_internal(admin, server_id="internal-a", organization_id="org-a")["changes"]
        access.clear_server_admission_cache()
        assert access.server_admission(identity, state=internal) == (True, "")
        migration._delete(admin, "users/" + user + "/groups/" + org_id)
        access.clear_server_admission_cache()
        assert not access.server_admission(identity, state=internal)[0]
        admin._put("users/" + user + "/groups/" + org_id, {})
        assert migration.rollback(admin, plan, expected_sha256=plan["sha256"],
                                  record=lambda _: None)["status"] == "rolled_back"
        assert migration._group(admin, access.manager_binding_group_path("internal-a")) is None
        access.clear_server_admission_cache()
        assert not access.server_admission(identity, state=internal)[0]

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

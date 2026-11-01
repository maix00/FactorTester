#!/usr/bin/env python3
"""Exercise device grants and revocation in a disposable Keycloak realm."""
from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from scripts.test.keycloak_cross_realm_smoke import Sandbox
from server.identity import keycloak_authorization, keycloak_device
from server.identity.keycloak import KeycloakAdminAdapter
from scripts.migrations.keycloak_device_inventory import read_keycloak_directory
from server.manager.domain.devices import DeviceRegistry
from server.manager.http import device_routes


def run(sandbox: Sandbox) -> dict[str, str]:
    realm = "device-qa"
    password, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    issuer = f"http://localhost:8080/realms/{realm}"
    sandbox.request("POST", "/admin/realms", token=sandbox.admin, body={
        "realm": realm, "enabled": True, "sslRequired": "none", "registrationAllowed": False,
    })
    profile = sandbox.api("GET", realm, "users/profile")
    profile["attributes"].append({"name": "tr_identity_id", "displayName": "Stable identity",
                                  "permissions": {"view": ["admin"], "edit": ["admin"]}})
    profile["unmanagedAttributePolicy"] = "ADMIN_EDIT"
    sandbox.api("PUT", realm, "users/profile", profile)
    sandbox.api("POST", realm, "clients", {
        "clientId": "tr-resource-server", "enabled": True, "protocol": "openid-connect",
        "publicClient": False, "secret": secret, "serviceAccountsEnabled": True,
        "directAccessGrantsEnabled": True, "authorizationServicesEnabled": True,
    })
    users = {}
    for username in ("owner", "other"):
        sandbox.api("POST", realm, "users", {
            "username": username, "enabled": True, "emailVerified": True,
            "firstName": "Temporary", "lastName": "User", "email": username + "@example.invalid",
            "attributes": {"tr_identity_id": ["stable-" + username],
                           "legacy_username": ["org@" + username + "@legacy"]},
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        })
        users[username] = sandbox.find(realm, "users?" + urlencode({"username": username, "exact": "true"}),
                                       username, field="username")

    def token(username: str) -> str:
        result = sandbox.request("POST", f"/realms/{realm}/protocol/openid-connect/token", form={
            "grant_type": "password", "client_id": "tr-resource-server", "client_secret": secret,
            "username": username, "password": password,
        })
        return result["access_token"]

    admin = KeycloakAdminAdapter(sandbox.base, realm)
    admin._token = lambda: sandbox.admin  # ephemeral realm test credential

    settings = {"issuer": issuer, "base_url": sandbox.base, "backchannel_base_url": sandbox.base,
                "realm": realm, "authz_client_id": "tr-resource-server", "authz_client_secret": secret}
    owner = {"keycloak_subject": users["owner"]["id"], "keycloak_issuer": issuer,
             "tr_identity_id": "stable-owner", "username": "owner"}
    other = {"keycloak_subject": users["other"]["id"], "keycloak_issuer": issuer,
             "tr_identity_id": "stable-other", "username": "other"}
    key = {"kty": "EC", "crv": "P-256", "x": "A" * 43, "y": "A" * 43}
    other_key = {**key, "x": "B" * 42 + "A"}
    device_id = "device-1234567890123456"
    owner_token, other_token = token("owner"), token("other")
    args = {"server_id": "manager-1", "device_id": device_id, "public_key": key}
    replies = []
    with patch.object(keycloak_device, "oidc_settings", return_value=settings), \
         patch.object(keycloak_authorization, "oidc_settings", return_value=settings), \
         patch("server.identity.federation_identity_sync.manager_keycloak_admin_adapter", return_value=admin), \
         patch.object(device_routes, 'json_response', side_effect=lambda _h, payload, status=200, **_kw: replies.append((status, payload))), \
         tempfile.TemporaryDirectory(prefix='tr-device-status-') as temp:
        directory = read_keycloak_directory('owner')
        assert directory['accounts'] == [{'username': 'owner', 'tr_identity_id': 'stable-owner',
                                           'keycloak_subject': users['owner']['id'], 'active': True}]
        for principal in ('Owner', 'org@owner@legacy'):
            matched = read_keycloak_directory(principal)['accounts']
            assert len(matched) == 1 and matched[0]['keycloak_subject'] == users['owner']['id']
        assert read_keycloak_directory('missing') == {'accounts': []}
        keycloak_device.register_device(session=owner, **args)
        registry = DeviceRegistry(Path(temp) / 'devices.json', server_id='manager-1')
        registry.enroll(username='owner', device_id=device_id, public_key=key)
        missing_id = 'device-unregistered-123456'
        registry.enroll(username='owner', device_id=missing_id, public_key=key)
        route = device_routes.DeviceNetworkRoutesMixin()
        route.state = SimpleNamespace(device_registry=registry, server_id='manager-1', public_server=True)
        route._session, route._bearer_token = lambda: owner, lambda: owner_token
        route._device_list()
        status = {row['device_id']: row['keycloak_authorized'] for row in replies[-1][1]['devices']}
        assert replies[-1][0] == 200 and status == {device_id: True, missing_id: False}
        assert keycloak_device.may_use_device(token=owner_token, session=owner, **args)
        records = [{"username": "owner", "device_id": device_id, "public_key": key,
                    "enabled": True, "source_server_id": "manager-1"}]
        assert keycloak_device.may_use_devices(token=owner_token, session=owner, server_id="manager-1", records=records) == {device_id}
        assert not keycloak_device.may_use_device(token=other_token, session=other, **args)
        assert not keycloak_device.may_use_device(token=owner_token, session=owner, **{**args, "public_key": other_key})
        assert keycloak_device.revoke_device(session=owner, **args)
        assert not keycloak_device.may_use_device(token=owner_token, session=owner, **args)
        assert not keycloak_device.may_use_devices(token=owner_token, session=owner, server_id="manager-1", records=records)
        route._device_list()
        assert replies[-1][0] == 200 and all(not row['keycloak_authorized'] for row in replies[-1][1]['devices'])
        assert replies[-1][1]['registered_device_count'] == 2 and replies[-1][1]['public_device_count'] == 0
        assert not keycloak_device.revoke_device(session=owner, **args)
    return {"owner": "allowed", "other_user": "denied", "other_key": "denied", "live_inventory": "verified",
            "same_token_after_revoke": "denied"}


if __name__ == "__main__":
    with Sandbox() as sandbox:
        result = run(sandbox)
    print(json.dumps({**result, "temporary_container_removed": True}, sort_keys=True))

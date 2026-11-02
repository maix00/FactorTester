#!/usr/bin/env python3
"""Exercise device grants and revocation in a disposable Keycloak realm."""
from __future__ import annotations

import json
import hashlib
import os
import secrets
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from scripts.test.keycloak_cross_realm_smoke import Sandbox
from server.identity import keycloak_authorization, keycloak_device
from server.identity.keycloak import KeycloakAdminAdapter
from scripts.migrations.keycloak_device_inventory import read_keycloak_directory
from scripts.migrations.keycloak_device_stage import KeycloakDeviceStageBackend, review, stage
from scripts.migrations.keycloak_device_parity import verify_device_policy_parity
from scripts.migrations import keycloak_device_stage_cli
from server.identity.keycloak_policy_evaluation import KeycloakPolicyEvaluator
from server.manager.domain.devices import DeviceRegistry
from server.manager.http import device_routes


@contextmanager
def restored_device_postgres(*, username, key, device_id):
    """Disposable PostgreSQL: dump and restore a real scoped device table."""
    import psycopg
    from psycopg.types.json import Jsonb

    name, password = 'tr-device-pg-' + secrets.token_hex(6), secrets.token_hex(24)
    started = False
    try:
        subprocess.run(['docker', 'run', '--rm', '-d', '--pull=never', '--name', name,
                        '--memory=256m', '--cpus=1', '--pids-limit=100', '-p', '127.0.0.1::5432',
                        '-e', 'POSTGRES_PASSWORD=' + password, 'postgres:17-alpine'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        started = True
        port = subprocess.check_output(['docker', 'port', name, '5432/tcp'], text=True).strip().rsplit(':', 1)[1]
        base = f'postgresql://postgres:{password}@127.0.0.1:{port}'
        deadline = time.monotonic() + 40
        while True:
            try:
                with psycopg.connect(base + '/postgres?sslmode=disable', autocommit=True) as db:
                    db.execute('CREATE DATABASE device_live')
                    db.execute('CREATE DATABASE device_restored')
                break
            except psycopg.OperationalError:
                if time.monotonic() > deadline: raise
                time.sleep(0.5)
        with psycopg.connect(base + '/device_live?sslmode=disable') as db:
            db.execute('''CREATE TABLE control_devices (device_id TEXT NOT NULL, username TEXT NOT NULL,
                public_key JSONB NOT NULL, enabled BOOLEAN NOT NULL, source_server_id TEXT NOT NULL,
                PRIMARY KEY (source_server_id, device_id))''')
            db.execute('INSERT INTO control_devices VALUES (%s,%s,%s,%s,%s)',
                       (device_id, username, Jsonb(key), True, 'manager-1'))
        dump = subprocess.check_output(['docker', 'exec', name, 'pg_dump', '-U', 'postgres', '-Fc', 'device_live'])
        subprocess.run(['docker', 'exec', '-i', name, 'pg_restore', '-U', 'postgres', '-d', 'device_restored'],
                       input=dump, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        yield base + '/device_live?sslmode=disable', base + '/device_restored?sslmode=disable'
    finally:
        if started:
            subprocess.run(['docker', 'rm', '-f', name], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


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
    from server.identity.keycloak_hierarchy_admin import KeycloakHierarchyProvisioner
    paths = ['/traderesearch', '/traderesearch/organizations', '/traderesearch/organizations/qa']
    group_ids, _ = KeycloakHierarchyProvisioner(admin).ensure_groups(paths)
    for user in users.values():
        admin._put('users/' + user['id'] + '/groups/' + group_ids[paths[-1]], {})

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
         patch("server.identity.user_session.oidc_settings", return_value=settings), \
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
        # Stage one separate legacy device into this disposable realm, then
        # verify actual user-token decisions as well as the admin evaluation.
        old_name = 'org@owner@legacy'
        old_device = 'device-migration-123456'
        snapshot = {'server_id': 'manager-1', 'devices': [{
            'device_id': old_device, 'username': old_name, 'public_key': key,
            'enabled': True, 'source_server_id': 'manager-1',
        }]}
        old_directory = read_keycloak_directory(old_name)
        evaluator = KeycloakPolicyEvaluator(allowed_kinds=('device',), allowed_scopes=('use',),
                                            adapter=admin, settings=settings)
        backend = KeycloakDeviceStageBackend(settings=settings, evaluator=evaluator, issuer=issuer)
        staged = stage(reviewed=review(snapshot, old_directory, manager_id='manager-1', issuer=issuer),
            backup_snapshot=snapshot, backup_directory=old_directory,
            live_snapshot=lambda: snapshot, live_directory=lambda: read_keycloak_directory(old_name),
            manager_id='manager-1', issuer=issuer, journal=Path(temp) / 'staging.jsonl',
            resource_absent=backend.resource_absent, create=backend.create, verify=backend.verify)
        assert staged['staged'] == 1 and staged['cutover_ready'] is False
        parity_args = dict(reviewed=review(snapshot, old_directory, manager_id='manager-1', issuer=issuer),
            live_snapshot=lambda: snapshot, live_directory=lambda: read_keycloak_directory(old_name),
            manager_id='manager-1', issuer=issuer, evaluator=evaluator, resource_absent=backend.resource_absent)
        parity = verify_device_policy_parity(**parity_args)
        assert parity['users'] == 2 and parity['allowed'] == 1 and parity['denied'] == 1
        migrated = {**args, 'device_id': old_device}
        assert keycloak_device.may_use_device(token=owner_token, session=owner, **migrated)
        assert not keycloak_device.may_use_device(token=other_token, session=other, **migrated)
        assert keycloak_device.revoke_device(session=owner, **migrated)
        assert not keycloak_device.may_use_device(token=owner_token, session=owner, **migrated)
        try:
            verify_device_policy_parity(**parity_args)
        except keycloak_authorization.AuthorizationUnavailable:
            pass
        else:
            raise AssertionError('parity must not accept or repair a revoked device')
        # A disabled legacy record is denied even if a stale Keycloak resource
        # accidentally still grants use. The verifier must discover that grant.
        disabled_snapshot = {'server_id': 'manager-1', 'devices': [
            {**snapshot['devices'][0], 'enabled': False}]}
        denied_args = {**parity_args,
            'reviewed': review(disabled_snapshot, old_directory, manager_id='manager-1', issuer=issuer),
            'live_snapshot': lambda: disabled_snapshot}
        assert verify_device_policy_parity(**denied_args)['denied'] == 2
        keycloak_device.register_device(session=owner, **migrated)
        try:
            verify_device_policy_parity(**denied_args)
        except keycloak_authorization.AuthorizationUnavailable:
            pass
        else:
            raise AssertionError('disabled device overgrant must block parity')
        assert keycloak_device.revoke_device(session=owner, **migrated)
        # Exercise the operator entry against an actual dump/restored database.
        # The realm backup here is only a disposable fixture; it is not a
        # Keycloak restore rehearsal or evidence about a production backup.
        cli_device = 'device-cli-migration-123456'
        with restored_device_postgres(username=old_name, key=key, device_id=cli_device) as (live_url, backup_url):
            plan_file, journal = Path(temp) / 'cli-plan.json', Path(temp) / 'cli-journal.jsonl'
            kc_fixture = Path(temp) / 'kc-fixture'
            kc_fixture.write_bytes(b'disposable fixture, not a realm export')
            kc_fixture.chmod(0o600)
            common = ['device-stage', '--manager-id', 'manager-1', '--principal', old_name,
                      '--plan', str(plan_file)]
            from server.manager.storage.control_db import CONTROL_DATABASE_ENV
            with patch.dict(os.environ, {CONTROL_DATABASE_ENV: live_url, 'TR_DEVICE_RESTORED_DB_URL': backup_url}), \
                 redirect_stdout(StringIO()):
                with patch.object(sys, 'argv', [common[0], 'review', *common[1:]]):
                    keycloak_device_stage_cli.main()
                with patch.object(sys, 'argv', [common[0], 'stage', *common[1:], '--journal', str(journal),
                    '--keycloak-backup', str(kc_fixture), '--keycloak-backup-sha256',
                    hashlib.sha256(kc_fixture.read_bytes()).hexdigest(), '--device-writes-quiesced']):
                    keycloak_device_stage_cli.main()
                with patch.object(sys, 'argv', [common[0], 'verify', *common[1:], '--device-writes-quiesced']):
                    keycloak_device_stage_cli.main()
            cli_args = {**args, 'device_id': cli_device}
            assert keycloak_device.may_use_device(token=owner_token, session=owner, **cli_args)
            assert not keycloak_device.may_use_device(token=other_token, session=other, **cli_args)
            assert keycloak_device.revoke_device(session=owner, **cli_args)
            assert not keycloak_device.may_use_device(token=owner_token, session=owner, **cli_args)
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
            "legacy_stage": "verified", "postgres_restore_cli": "verified", "allow_deny_parity": "verified",
            "same_token_after_revoke": "denied"}


if __name__ == "__main__":
    with Sandbox() as sandbox:
        result = run(sandbox)
    print(json.dumps({**result, "temporary_container_removed": True}, sort_keys=True))

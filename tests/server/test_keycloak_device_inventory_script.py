import json
import os
import subprocess
import sys

import pytest

from scripts.migrations.keycloak_device_inventory import plan, read_postgres_snapshot

KEY = {'kty': 'EC', 'crv': 'P-256', 'x': 'A' * 43, 'y': 'A' * 43}
ACCOUNT = {'username': 'alice', 'tr_identity_id': 'stable', 'keycloak_subject': 'subject', 'active': True}


def test_inventory_distinguishes_legacy_denial_and_other_manager_without_keys():
    local = {'username': 'alice', 'public_key': KEY, 'enabled': True, 'public_access': False}
    remote = {'device_id': 'device-peer-123456', 'username': 'alice', 'public_key': KEY, 'enabled': True}
    snapshot = {'server_id': 'lan', 'devices': {'device-local-12345': local},
                'sources': {'public': {'devices': [remote]}}}
    result = plan(snapshot, {'accounts': [ACCOUNT]}, manager_id='lan')
    assert result['summary']['statuses'] == {'legacy_policy_review': 1, 'outside_manager': 1}
    assert result['summary']['keycloak_live_grants_checked'] is False
    assert 'public_key' not in json.dumps(result)
    assert result == plan(snapshot, {'accounts': [ACCOUNT]}, manager_id='lan')


def test_inventory_rejects_ambiguous_identity_and_manager():
    snapshot = {'server_id': 'lan', 'devices': {}, 'sources': {}}
    with pytest.raises(ValueError, match='another Manager'):
        plan(snapshot, {'accounts': [ACCOUNT]}, manager_id='public')
    with pytest.raises(ValueError, match='duplicate identities'):
        plan(snapshot, {'accounts': [ACCOUNT, {**ACCOUNT, 'username': 'bob'}]}, manager_id='lan')


def test_cli_writes_owner_only_plan_and_summary_without_device_data(tmp_path):
    snapshot = tmp_path / 'devices.json'
    directory = tmp_path / 'accounts.json'
    output = tmp_path / 'plan.json'
    snapshot.write_text(json.dumps({'server_id': 'lan', 'devices': {
        'device-local-12345': {'username': 'alice', 'public_key': KEY, 'enabled': True}}, 'sources': {}}))
    directory.write_text(json.dumps({'accounts': [ACCOUNT]}))
    result = subprocess.run([sys.executable, '-m', 'scripts.migrations.keycloak_device_inventory',
        '--snapshot', str(snapshot), '--reviewed-directory', str(directory), '--manager-id', 'lan',
        '--output', str(output)], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['statuses'] == {'grant': 1}
    assert 'alice' not in result.stdout and KEY['x'] not in result.stdout
    assert os.stat(output).st_mode & 0o777 == 0o600
    assert 'public_key' not in output.read_text()
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run([sys.executable, '-m', 'scripts.migrations.keycloak_device_inventory',
            '--snapshot', str(snapshot), '--reviewed-directory', str(directory), '--manager-id', 'lan',
            '--output', str(output)], capture_output=True, check=True)


def test_postgres_inventory_is_read_only_scoped_and_pages_without_loss():
    class Result:
        def __init__(self, rows): self.rows = rows
        def fetchall(self): return self.rows
    class Connection:
        def __init__(self): self.calls = []
        def execute(self, query, parameters=()):
            self.calls.append((query, parameters))
            if query.startswith('SET TRANSACTION'): return Result([])
            if 'information_schema.columns' in query: return Result([{'column_name': 'public_access'}])
            principal, after, limit = parameters
            assert principal == 'alice' and limit == 501 and 'quota_exempt' not in query
            rows = [{'device_id': f'device-{n:07d}', 'username': principal, 'public_key': KEY,
                     'enabled': True, 'source_server_id': 'lan', 'public_access': False} for n in range(1002)]
            return Result([row for row in rows if row['device_id'] > after][:limit])
    connection = Connection()
    snapshot = read_postgres_snapshot(connection, manager_id='lan', principal='alice')
    assert len(snapshot['devices']) == 1002
    assert snapshot['legacy_columns_present'] == ['public_access']
    assert len({row['device_id'] for row in snapshot['devices']}) == 1002
    assert connection.calls[0][0] == 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'
    assert len([call for call in connection.calls if 'FROM control_devices' in call[0]]) == 3

import json
import os
import hashlib

import pytest

from scripts.migrations.keycloak_device_stage import KeycloakDeviceStageBackend, review, stage

KEY = {'kty': 'EC', 'crv': 'P-256', 'x': 'A' * 43, 'y': 'A' * 43}
DIRECTORY = {'accounts': [{'username': 'alice', 'tr_identity_id': 'stable',
                           'keycloak_subject': 'subject', 'active': True}]}
SNAPSHOT = {'server_id': 'lan', 'devices': [{
    'device_id': 'device-123456789012', 'username': 'alice', 'public_key': KEY,
    'enabled': True, 'source_server_id': 'lan',
}]}
ISSUER = 'https://id.example/realms/test'


def _args(tmp_path, **overrides):
    kwargs = dict(reviewed=review(SNAPSHOT, DIRECTORY, manager_id='lan', issuer=ISSUER),
                  backup_snapshot=SNAPSHOT, backup_directory=DIRECTORY,
                  live_snapshot=lambda: SNAPSHOT, live_directory=lambda: DIRECTORY,
                  manager_id='lan', issuer=ISSUER, journal=tmp_path / 'journal.jsonl',
                  resource_absent=lambda _ref: True,
                  create=lambda _ref, _subject, _intent: 'resource',
                  verify=lambda _identity, _ref: True)
    return kwargs | overrides


def test_stage_journals_intent_before_create_and_verifies_exact_owner(tmp_path):
    args = _args(tmp_path)
    calls = []
    def create(ref, subject, intent):
        records = [json.loads(row) for row in args['journal'].read_text().splitlines()]
        assert records[-1]['event'] == 'intent' and records[-1]['intent'] == intent
        calls.append((ref, subject, intent))
        return 'resource'
    args['create'] = create
    args['verify'] = lambda identity, ref: identity == 'stable' and ref == calls[0][0]
    result = stage(**args)
    assert result['staged'] == 1 and result['cutover_ready'] is False
    assert calls[0][1] == 'subject'
    assert [json.loads(row)['event'] for row in args['journal'].read_text().splitlines()] == [
        'begin', 'intent', 'verified', 'complete']
    assert os.stat(args['journal']).st_mode & 0o777 == 0o600
    assert all(value not in args['journal'].read_text() for value in ('alice', 'subject', KEY['x']))
    with pytest.raises(FileExistsError):
        stage(**args)


def test_stage_fails_before_writing_when_subject_or_issuer_changed(tmp_path):
    changed = {'accounts': [{**DIRECTORY['accounts'][0], 'keycloak_subject': 'different'}]}
    args = _args(tmp_path, live_directory=lambda: changed)
    with pytest.raises(ValueError, match='changed after review'):
        stage(**args)
    assert not args['journal'].exists()
    args = _args(tmp_path, issuer='https://other.example/realms/test')
    with pytest.raises(ValueError, match='does not match backup'):
        stage(**args)


def test_existing_resource_is_not_regranted_and_ambiguous_legacy_grant_blocks(tmp_path):
    args = _args(tmp_path, resource_absent=lambda _ref: False)
    with pytest.raises(ValueError, match='manual authorization review'):
        stage(**args)
    assert not args['journal'].exists()
    ambiguous = {**SNAPSHOT, 'devices': [{**SNAPSHOT['devices'][0], 'public_access': False}]}
    args = _args(tmp_path, backup_snapshot=ambiguous, live_snapshot=lambda: ambiguous,
                 reviewed=review(ambiguous, DIRECTORY, manager_id='lan', issuer=ISSUER))
    with pytest.raises(ValueError, match='unresolved'):
        stage(**args)
    assert not args['journal'].exists()


def test_normalized_duplicate_blocks_before_any_keycloak_write(tmp_path):
    first = SNAPSHOT['devices'][0]
    duplicate = {**first, 'device_id': ' ' + first['device_id'] + ' '}
    snapshot = {**SNAPSHOT, 'devices': [first, duplicate]}
    reviewed = review(snapshot, DIRECTORY, manager_id='lan', issuer=ISSUER)
    assert reviewed['statuses'] == {'conflict': 2}
    calls = []
    args = _args(tmp_path, backup_snapshot=snapshot, live_snapshot=lambda: snapshot,
                 reviewed=reviewed, create=lambda *items: calls.append(items))
    with pytest.raises(ValueError, match='unresolved'):
        stage(**args)
    assert not calls and not args['journal'].exists()


def test_partial_failure_leaves_durable_intent_and_never_retries(tmp_path):
    calls = []
    def fail(ref, subject, intent):
        calls.append(ref)
        raise RuntimeError('response lost after possible create')
    args = _args(tmp_path, create=fail)
    with pytest.raises(RuntimeError): stage(**args)
    assert [json.loads(row)['event'] for row in args['journal'].read_text().splitlines()] == [
        'begin', 'intent', 'unresolved']
    with pytest.raises(FileExistsError): stage(**args)
    assert len(calls) == 1


def test_identity_change_between_grants_stops_before_next_write(tmp_path):
    second = {**SNAPSHOT['devices'][0], 'device_id': 'device-987654321098'}
    snapshot = {**SNAPSHOT, 'devices': [SNAPSHOT['devices'][0], second]}
    changed = {'accounts': [{**DIRECTORY['accounts'][0], 'keycloak_subject': 'different'}]}
    reads = iter([DIRECTORY, DIRECTORY, changed])
    calls = []
    args = _args(tmp_path, backup_snapshot=snapshot, live_snapshot=lambda: snapshot,
                 reviewed=review(snapshot, DIRECTORY, manager_id='lan', issuer=ISSUER),
                 live_directory=lambda: next(reads), create=lambda ref, *_: calls.append(ref) or 'resource')
    with pytest.raises(ValueError, match='changed after review'): stage(**args)
    assert len(calls) == 1
    assert [json.loads(row)['event'] for row in args['journal'].read_text().splitlines()] == [
        'begin', 'intent', 'verified']


def test_backend_refuses_a_changed_realm_or_client(monkeypatch):
    from server.identity import keycloak_authorization, user_session
    settings = {'issuer': ISSUER, 'realm': 'test', 'authz_client_id': 'authz',
                'authz_client_secret': 'secret', 'base_url': 'https://id.example'}
    current = dict(settings)
    monkeypatch.setattr(user_session, 'oidc_settings', lambda: current)
    monkeypatch.setattr(keycloak_authorization, 'protection_token', lambda _settings: 'token')
    with pytest.raises(ValueError, match='another issuer'):
        KeycloakDeviceStageBackend(settings=settings, evaluator=None, issuer='https://other.example/realm')
    backend = KeycloakDeviceStageBackend(settings=settings, evaluator=None, issuer=ISSUER)
    current['authz_client_id'] = 'other'
    with pytest.raises(ValueError, match='configuration changed'):
        backend.create('ref', 'subject', 'a' * 64)


def test_cli_checks_restored_database_backup_and_quiescence_before_writes(tmp_path, monkeypatch, capsys):
    import sys
    from types import SimpleNamespace
    from scripts.migrations import keycloak_device_stage_cli as cli
    from server.manager.storage import control_db
    from server.identity import keycloak_policy_evaluation, user_session

    live = SimpleNamespace(host='db', port=5432, database='live')
    backup = SimpleNamespace(host='db', port=5432, database='restored')
    monkeypatch.setattr(control_db.ControlDatabaseConfig, 'from_env', classmethod(lambda _cls: live))
    monkeypatch.setattr(control_db.ControlDatabaseConfig, 'from_url', classmethod(lambda _cls, _url: backup))
    monkeypatch.setattr(cli, '_snapshot', lambda _config, **_kw: SNAPSHOT)
    monkeypatch.setattr(cli, 'read_keycloak_directory', lambda _principal: DIRECTORY)
    monkeypatch.setattr(user_session, 'oidc_settings', lambda: {'issuer': ISSUER})
    monkeypatch.setenv('TR_DEVICE_RESTORED_DB_URL', 'unused-in-test')
    plan_file = tmp_path / 'plan.json'
    base = ['device-stage', '--manager-id', 'lan', '--principal', 'alice', '--plan', str(plan_file)]
    monkeypatch.setattr(sys, 'argv', [base[0], 'review', *base[1:]])
    backup.database = 'live'
    with pytest.raises(SystemExit): cli.main()
    assert not plan_file.exists()
    backup.database = 'restored'
    cli.main()
    assert os.stat(plan_file).st_mode & 0o777 == 0o600
    assert 'alice' not in capsys.readouterr().out

    backup_file = tmp_path / 'keycloak.backup'
    backup_file.write_bytes(b'isolated realm backup')
    backup_file.chmod(0o600)
    digest = hashlib.sha256(backup_file.read_bytes()).hexdigest()
    stage_args = [base[0], 'stage', *base[1:], '--journal', str(tmp_path / 'journal'),
                  '--keycloak-backup', str(backup_file), '--keycloak-backup-sha256', digest]
    monkeypatch.setattr(sys, 'argv', stage_args)
    with pytest.raises(SystemExit): cli.main()
    assert not (tmp_path / 'journal').exists()

    class Backend:
        def __init__(self, **_kwargs): pass
        def resource_absent(self, _ref): return True
        def create(self, _ref, _subject, _intent): return 'resource'
        def verify(self, _identity, _ref): return True
    monkeypatch.setattr(keycloak_policy_evaluation, 'KeycloakPolicyEvaluator', lambda **_kwargs: object())
    monkeypatch.setattr(cli, 'KeycloakDeviceStageBackend', Backend)
    monkeypatch.setattr(sys, 'argv', stage_args + ['--device-writes-quiesced'])
    cli.main()
    assert json.loads(capsys.readouterr().out)['staged'] == 1

    with pytest.raises(ValueError, match='checksum'):
        cli._check_keycloak_backup(str(backup_file), '0' * 64)
    backup_file.chmod(0o644)
    with pytest.raises(PermissionError): cli._check_keycloak_backup(str(backup_file), digest)

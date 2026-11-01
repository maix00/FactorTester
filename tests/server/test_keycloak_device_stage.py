import json
import os

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

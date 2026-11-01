import copy
import hashlib

import pytest

from scripts.migrations.keycloak_local_report_binding import BindingBackend, _SCOPES, review, stage
from server.identity.keycloak_authorization import keycloak_resource_name, keycloak_resource_uri
from server.jobs.storage.couchdb_research_publication import publication_id
from server.jobs.storage.couchdb_research_reports import document_id
from server.manager.services.local_report_publication import _receipt_id, _research_binding

RESEARCH = 'research:v1:' + 'R' * 24
REPORT = 'report:v1:' + 'P' * 24


def evidence():
    manager, owner, subject, issuer = 'manager', 'stable-owner', 'subject-owner', 'https://id.test/realm'
    receipt = {'_id': _receipt_id(manager, owner, REPORT), '_rev': '1-receipt',
        'kind': 'research_report_registration', 'state': 'registered', 'research_id': RESEARCH,
        'report_id': REPORT, 'manager_id': manager, 'owner_identity_id': owner, 'owner_subject': subject,
        'issuer': issuer, 'creation_intent': 'a' * 64}
    pub = publication_id(manager, owner, REPORT, 'main')
    publication = {'_id': document_id(pub), '_rev': '1-publication', 'kind': 'research_report',
        'publication_id': pub, 'research_id': RESEARCH, 'report_id': REPORT, 'branch_ref': 'main',
        'owner_identity_id': owner, 'keycloak_resource_id': 'resource-id', 'generation': 1,
        'projection_hash': 'f' * 64,
        'publication': {'publication_id': pub, 'report_id': REPORT, 'branch_ref': 'main',
            'storage_server_id': manager, 'generation': 1, 'projection_hash': 'f' * 64, 'owner_ref': 'alice'}}
    resource = {'_id': 'resource-id', 'name': keycloak_resource_name('research_report', REPORT),
        'type': 'urn:traderesearch:resource:research_report',
        'uris': [keycloak_resource_uri('research_report', REPORT)], 'scopes': [{'name': 'read'}],
        'attributes': {'traderesearch_owner_subject': [subject], 'traderesearch_creation_intent': ['a' * 64],
                       'traderesearch_ref_hash': [hashlib.sha256(REPORT.encode()).hexdigest()]}}
    directory = {owner: subject, 'stable-other': 'subject-other'}
    return dict(manager_id=manager, issuer=issuer, research_id=RESEARCH, report_id=REPORT,
                owner_id=owner, owner_subject=subject, receipt=receipt, publication=publication,
                resource=resource, policies=[{'id': 'policy-1', 'scopes': ['read']}], directory=directory)


def decisions():
    # A revoked share permission remains revoked after metadata migration.
    return {(identity, scope): identity == 'stable-owner' and scope != 'share'
            for identity in ('stable-owner', 'stable-other') for scope in _SCOPES}


def test_binding_migration_preserves_revoked_and_other_user_decisions():
    state, logs, checks = evidence(), [], decisions()
    approved = review(**state, decisions=checks)
    def update(resource):
        assert logs[-1]['event'] == 'binding_intent'
        state['resource'] = resource
    result = stage(approved=approved, read_evidence=lambda: copy.deepcopy(state),
        read_decisions=lambda _directory, _report: dict(checks), update_resource=update, record=logs.append)
    assert result == {'status': 'bound', 'cutover_ready': False}
    assert state['resource']['attributes']['traderesearch_research_binding'] == [_research_binding(RESEARCH, REPORT)]
    assert checks[('stable-owner', 'share')] is False and checks[('stable-other', 'write')] is False
    assert [item['event'] for item in logs] == ['binding_intent', 'binding_verified']
    assert 'subject-owner' not in str(logs)


@pytest.mark.parametrize('field', ['research', 'owner', 'intent', 'resource', 'resource_type', 'ref_hash',
                                   'projection', 'policies', 'directory', 'decisions'])
def test_invalid_or_incomplete_evidence_cannot_be_reviewed(field):
    state, checks = evidence(), decisions()
    if field == 'research': state['publication']['research_id'] = 'research:v1:' + 'Q' * 24
    if field == 'owner': state['receipt']['owner_subject'] = 'different'
    if field == 'intent': state['resource']['attributes']['traderesearch_creation_intent'] = ['b' * 64]
    if field == 'resource': state['publication']['keycloak_resource_id'] = 'different'
    if field == 'resource_type': state['resource']['type'] = 'other'
    if field == 'ref_hash': state['resource']['attributes']['traderesearch_ref_hash'] = ['f' * 64]
    if field == 'projection': state['publication']['publication']['storage_server_id'] = 'other'
    if field == 'policies': state['policies'].append({'id': 'policy-1'})
    if field == 'directory': state['directory']['stable-other'] = 'subject-owner'
    if field == 'decisions': checks.pop(('stable-other', 'share'))
    with pytest.raises(ValueError): review(**state, decisions=checks)


def test_changed_or_foreign_binding_never_mutates():
    state, checks = evidence(), decisions()
    approved = review(**state, decisions=checks)
    state['receipt']['_rev'] = '2-changed'
    writes = []
    with pytest.raises(ValueError, match='changed after review'):
        stage(approved=approved, read_evidence=lambda: state, read_decisions=lambda *_: checks,
              update_resource=writes.append, record=writes.append)
    assert not writes
    state = evidence()
    state['resource']['attributes']['traderesearch_research_binding'] = ['f' * 64]
    with pytest.raises(ValueError, match='another Research'): review(**state, decisions=checks)


def test_uncertain_write_or_changed_policy_is_not_retried():
    state, checks, logs = evidence(), decisions(), []
    approved = review(**state, decisions=checks)
    def mutate(resource):
        state['resource'] = resource
        checks[('stable-owner', 'share')] = True
    with pytest.raises(ValueError, match='permissions changed'):
        stage(approved=approved, read_evidence=lambda: copy.deepcopy(state), read_decisions=lambda *_: dict(checks),
              update_resource=mutate, record=logs.append)
    assert [item['event'] for item in logs] == ['binding_intent', 'binding_unresolved']
    with pytest.raises(ValueError, match='changed after review'):
        stage(approved=approved, read_evidence=lambda: copy.deepcopy(state), read_decisions=lambda *_: dict(checks),
              update_resource=lambda _: pytest.fail('must not retry'), record=logs.append)


def test_policy_inventory_change_is_detected_even_if_sampled_decisions_match():
    state, checks, logs = evidence(), decisions(), []
    approved = review(**state, decisions=checks)
    def mutate(resource):
        state['resource'] = resource
        state['policies'][0]['scopes'] = ['read', 'write']
    with pytest.raises(ValueError, match='permissions changed'):
        stage(approved=approved, read_evidence=lambda: copy.deepcopy(state), read_decisions=lambda *_: dict(checks),
              update_resource=mutate, record=logs.append)
    assert [item['event'] for item in logs] == ['binding_intent', 'binding_unresolved']


def test_backend_reads_authoritative_receipt_and_updates_only_the_resource(monkeypatch):
    import json
    from types import SimpleNamespace
    from server.identity import keycloak_research_cutover
    state, checks = evidence(), decisions()
    settings = {'issuer': state['issuer'], 'realm': 'test', 'authz_client_id': 'authz'}
    monkeypatch.setattr(keycloak_research_cutover, '_active_human_subjects', lambda _adapter: state['directory'])
    class Store:
        def _request(self, method, path):
            assert method == 'GET'
            row = state['receipt'] if path == state['receipt']['_id'] else state['publication']
            return 200, json.dumps(row).encode()
    class Manager:
        def settings_provider(self): return settings
        def token_provider(self, _settings): return 'temporary-protection-token'
        def _resource(self, *_args): return copy.deepcopy(state['resource'])
        def _resource_policies(self, *_args): return copy.deepcopy(state['policies'])
        def request(self, _settings, _token, method, path, body):
            assert method == 'PUT' and path == 'resource_set/resource-id'
            state['resource'] = body
    class Evaluator:
        def evaluate(self, identity, *, candidates):
            assert candidates == [('research_report', REPORT, _SCOPES)]
            return {('research_report', REPORT, scope): checks[(identity, scope)] for scope in _SCOPES}
    backend = BindingBackend(state=SimpleNamespace(server_id='manager'), store=Store(), manager=Manager(),
        adapter=object(), research_id=RESEARCH, report_id=REPORT, owner_id='stable-owner', evaluator=Evaluator())
    snapshot = backend.read_evidence()
    approved = review(**snapshot, decisions=backend.read_decisions(snapshot['directory'], REPORT))
    assert stage(approved=approved, read_evidence=backend.read_evidence, read_decisions=backend.read_decisions,
                 update_resource=backend.update_resource, record=lambda _value: None)['status'] == 'bound'
    with pytest.raises(ValueError, match='resource identity'):
        backend.update_resource({**state['resource'], '_id': 'id?unexpected=true'})
    original_id = state['resource']['_id']
    state['resource']['_id'] = 'id?unexpected=true'
    with pytest.raises(ValueError, match='resource identity'):
        backend.read_evidence()
    state['resource']['_id'] = original_id
    settings['realm'] = 'different'
    with pytest.raises(ValueError, match='configuration changed'):
        backend.update_resource(state['resource'])


def test_operator_entry_requires_exact_restore_quiescence_and_checked_backups(tmp_path, monkeypatch, capsys):
    import hashlib
    import json
    import sys
    from types import SimpleNamespace
    from scripts.migrations import keycloak_local_report_binding_cli as cli
    from server.identity import federation_identity_sync, keycloak_research, server_admission
    from server.manager.services import research_couchdb_publication

    state, checks = evidence(), decisions()
    class Store:
        database = 'restored'
        def _request(self, method, path):
            assert method == 'GET'
            row = state['receipt'] if path == state['receipt']['_id'] else state['publication']
            return 200, json.dumps(row).encode()
    class Backend:
        def __init__(self, **_kwargs): pass
        def read_evidence(self): return copy.deepcopy(state)
        def read_decisions(self, *_args): return dict(checks)
        def update_resource(self, resource): state['resource'] = resource
    monkeypatch.setattr(server_admission, '_context', lambda _state: (False, 'manager', ()))
    monkeypatch.setattr(research_couchdb_publication, 'report_store_from_environment', lambda: SimpleNamespace(database='live'))
    monkeypatch.setattr(federation_identity_sync, 'manager_keycloak_admin_adapter', lambda: object())
    monkeypatch.setattr(keycloak_research, 'KeycloakResearchGrantManager', lambda: object())
    monkeypatch.setattr(cli, 'BindingBackend', Backend)
    monkeypatch.setattr(cli, '_restored_store', lambda _live: Store())
    path, journal = tmp_path / 'plan.json', tmp_path / 'journal.jsonl'
    base = ['binding', '--manager-id', 'manager', '--owner-id', 'stable-owner',
            '--research-id', RESEARCH, '--report-id', REPORT, '--plan', str(path)]
    monkeypatch.setattr(sys, 'argv', [base[0], 'review', *base[1:]])
    cli.main()
    assert json.loads(capsys.readouterr().out)['status'] == 'ready'
    backups = []
    for name in ('keycloak', 'couch'):
        file = tmp_path / name
        file.write_bytes(name.encode())
        file.chmod(0o600)
        backups += ['--' + name + '-backup', str(file), '--' + name + '-backup-sha256',
                    hashlib.sha256(file.read_bytes()).hexdigest()]
    command = [base[0], 'stage', *base[1:], '--journal', str(journal), *backups]
    monkeypatch.setattr(sys, 'argv', command)
    with pytest.raises(SystemExit): cli.main()
    assert not journal.exists()
    monkeypatch.setattr(sys, 'argv', command + ['--authorization-writes-quiesced', '--keycloak-restore-verified'])
    cli.main()
    assert json.loads(capsys.readouterr().out)['status'] == 'bound'
    assert [json.loads(row)['event'] for row in journal.read_text().splitlines()] == ['binding_intent', 'binding_verified']
    assert journal.stat().st_mode & 0o777 == 0o600
    changed = copy.deepcopy(state['publication'])
    changed['_rev'] = 'new'
    with pytest.raises(ValueError, match='restored publication differs'):
        cli._verify_restored({**state, 'publication': changed}, Store())

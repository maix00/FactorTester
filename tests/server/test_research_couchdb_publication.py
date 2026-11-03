from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.identity.keycloak_authorization import AuthorizationUnavailable
from server.identity.keycloak_research import ResearchRequestIdentity
from server.manager.services.research_couchdb_publication import ResearchCouchPublicationService
from tests.server.test_couchdb_research_publication import Couch, report


SESSION = {'username': 'alice', 'keycloak_subject': 'subject-alice', 'keycloak_issuer': 'https://issuer',
           'tr_identity_id': 'stable-alice', 'keycloak_roles': ['public_server:login']}


class Manager:
    def __init__(self):
        self.enabled = True
        self.resource = {'_id': 'resource-1', 'attributes': {'traderesearch_owner_subject': ['subject-alice']}}
    def identity_provider(self, actor):
        return ResearchRequestIdentity('token', 'https://issuer', 'subject-alice', actor, 'stable-alice')
    def settings_provider(self): return {}
    def token_provider(self, _settings): return 'protection-token'
    def _resource(self, *_args): return self.resource
    def user_provider(self, _subject):
        return {'id': 'subject-alice', 'username': 'alice', 'enabled': self.enabled,
                'attributes': {'tr_identity_id': ['stable-alice']}}
    def user_by_identity(self, _stable): return {'id': 'subject-alice'}


class Catalog:
    def __init__(self):
        self._profile_grant_manager = Manager()
        self.strict = True
        self.target_ok = True
    def require_keycloak_sharing(self):
        if not self.strict: raise RuntimeError('Keycloak required')
    def _keycloak_share_target(self, research_id, kind, report_id):
        if not self.target_ok or (research_id, kind, report_id) != ('research-1', 'report', 'report-1'):
            raise ValueError('invalid selected report')
        return 'research_report', report_id
    def _report_row(self, _report_id): return {'owner_ref': 'alice'}


def harness():
    catalog, store = Catalog(), Couch()
    auth = {'admit': True, 'read': True, 'write': True, 'share': True, 'checks': 0, 'revoke_after_first': False}
    def admission(session, *, state, use_cache):
        assert session == SESSION and state.public_server and use_cache is False
        return auth['admit'], ''
    def authorize(token, *, permissions, use_cache):
        assert token == 'token' and use_cache is False
        auth['checks'] += 1
        if auth['revoke_after_first'] and auth['checks'] == 2:
            auth['share'] = False
        return {(uri, scope): auth[scope] for uri, _name, scope in permissions}
    service = ResearchCouchPublicationService(state=SimpleNamespace(server_id='public', public_server=True),
        catalog=catalog, store=store, admission=admission, authorize_many=authorize)
    return service, catalog, store, auth


def publish(service, session=SESSION):
    return service.publish(session=session, research_id='research-1', report_id='report-1', branch_ref='main',
                           projection=report(), expected_revision=None)


def test_publishes_selected_report_and_rechecks_after_version_storage():
    service, _catalog, store, auth = harness()
    result = publish(service)
    assert result['report_id'] == 'report-1' and store.head_writes == 1 and auth['checks'] == 3
    document = next(value for value in store.docs.values() if value.get('kind') == 'research_report')
    assert document['owner_identity_id'] == 'stable-alice' and document['keycloak_resource_id'] == 'resource-1'


@pytest.mark.parametrize('which', ['admit', 'write', 'share'])
def test_current_public_admission_and_exact_report_scopes_are_required(which):
    service, _catalog, store, auth = harness()
    auth[which] = False
    with pytest.raises(PermissionError): publish(service)
    assert store.writes == 0


def test_revocation_after_preparation_still_prevents_couchdb_write():
    service, _catalog, store, auth = harness()
    auth['revoke_after_first'] = True
    with pytest.raises(PermissionError): publish(service)
    assert auth['checks'] == 2 and store.writes == 0


def test_unknown_changed_owner_and_unverified_caller_fail_closed():
    service, catalog, store, _auth = harness()
    catalog._profile_grant_manager.enabled = False
    with pytest.raises(AuthorizationUnavailable): publish(service)
    catalog._profile_grant_manager.enabled = True
    with pytest.raises(PermissionError): publish(service, {**SESSION, 'tr_identity_id': 'other'})
    catalog.target_ok = False
    with pytest.raises(ValueError): publish(service)
    assert store.writes == 0


def test_read_and_attachment_use_current_exact_report_permission_and_verify_integrity():
    service, _catalog, store, auth = harness()
    receipt = publish(service)
    args = {'session': SESSION, 'research_id': 'research-1', 'report_id': 'report-1',
            'publication_ref': receipt['publication_id']}
    assert service.read(**args)['projection']['report_id'] == 'report-1'
    assert service.read(session=SESSION, research_id='research-1', report_id='report-1',
                        branch_ref='main')['publication']['publication_id'] == receipt['publication_id']
    with pytest.raises(PermissionError):
        service.read(**args, branch_ref='another-branch')
    assert service.read(**args, attachment='research_asset/image-1')['content'] == b'picture'
    auth['read'] = False
    with pytest.raises(PermissionError): service.read(**args)
    auth['read'] = True
    document = next(value for value in store.docs.values() if value.get('kind') == 'research_report')
    document['attachments']['research_asset/image-1']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='identity'): service.read(**args, attachment='research_asset/image-1')


def test_read_rejects_resource_substitution_and_other_report():
    service, _catalog, store, _auth = harness()
    receipt = publish(service)
    document = next(value for value in store.docs.values() if value.get('kind') == 'research_report')
    document['keycloak_resource_id'] = 'different-resource'
    with pytest.raises(PermissionError):
        service.read(session=SESSION, research_id='research-1', report_id='report-1',
                     publication_ref=receipt['publication_id'])

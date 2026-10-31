from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from server.identity.keycloak_authorization import AuthorizationUnavailable, keycloak_resource_name
from server.identity.keycloak_research import ResearchRequestIdentity
from server.manager.services.local_report_publication import LocalReportPublicationService
from tests.server.test_couchdb_research_publication import Couch, report
from tools.cli.release.research_reporting.public_research.object_uploads import projection_hash


RESEARCH = 'research:v1:' + 'R' * 24
REPORT = 'report:v1:' + 'P' * 24
SESSION = {'username': 'alice', 'keycloak_subject': 'subject-alice', 'keycloak_issuer': 'https://issuer',
           'tr_identity_id': 'stable-alice', 'keycloak_roles': ['public_server:login']}


class Manager:
    def __init__(self):
        self.resource, self.ensure_calls, self.failure, self.grants = None, 0, '', {}
        self.owner = {'id': 'subject-alice', 'username': 'alice', 'enabled': True,
                      'attributes': {'tr_identity_id': ['stable-alice']}}
    def identity_provider(self, actor):
        return ResearchRequestIdentity('token', 'https://issuer', 'subject-alice', actor, 'stable-alice')
    def settings_provider(self): return {'issuer': 'https://issuer'}
    def token_provider(self, _settings): return 'protection-token'
    def user_by_identity(self, stable):
        if stable == 'stable-alice': return self.owner
        if stable == 'stable-bob':
            return {'id': 'subject-bob', 'username': 'same-name-on-another-server', 'enabled': True,
                    'attributes': {'tr_identity_id': ['stable-bob']}}
        raise LookupError('unavailable')
    def user_provider(self, _subject): return self.owner
    def request(self, _settings, _token, method, path):
        assert method == 'GET' and path.startswith('resource_set?')
        return 200, [self.resource] if self.resource else [], ''
    def ensure_resource(self, *, resource_type, resource_ref, owner_subject, creation_intent, create_only):
        assert resource_type == 'research_report' and create_only is True
        assert self.resource is None
        self.ensure_calls += 1
        if self.failure == 'before': raise AuthorizationUnavailable('network failed')
        self.resource = {'_id': 'resource-1', 'name': keycloak_resource_name(resource_type, resource_ref),
            'attributes': {'traderesearch_owner_subject': [owner_subject],
                           'traderesearch_creation_intent': [creation_intent]}}
        if self.failure == 'after': raise AuthorizationUnavailable('response lost')
        return 'resource-1'
    def _resource(self, *_args):
        if self.resource is None: raise AuthorizationUnavailable('missing')
        return self.resource
    def list_user_grants(self, *, actor, resource_type, resource_ref):
        assert actor == 'alice' and resource_type == 'research_report' and resource_ref == REPORT
        return list(self.grants.values())
    def set_user_grant(self, *, actor, resource_type, resource_ref, source, identity_id, subject, scopes):
        assert actor == 'alice' and resource_type == 'research_report' and resource_ref == REPORT and source == 'explicit'
        if scopes:
            self.grants[identity_id] = {'identity_id': identity_id, 'subject': subject, 'scopes': sorted(scopes)}
        else:
            self.grants.pop(identity_id, None)
        return True


def harness(tmp_path):
    manager, store = Manager(), Couch()
    auth = {'admit': True, 'read': True, 'write': True, 'share': True}
    def admission(_session, *, state, use_cache):
        assert use_cache is False and state.public_server
        return auth['admit'], ''
    def authorize(_token, *, permissions, use_cache):
        assert use_cache is False
        return {(uri, scope): auth[scope] for uri, _name, scope in permissions}
    service = LocalReportPublicationService(state=SimpleNamespace(server_id='public', public_server=True,
        state_root=tmp_path), store=store, manager=manager, admission=admission, authorize_many=authorize)
    return service, manager, store, auth


def payload():
    value = report()
    value['report_id'] = REPORT
    value['projection_hash'] = projection_hash(value)
    return value


def publish(service, *, research=RESEARCH, report_ref=REPORT, branch='main', session=SESSION):
    return service.publish_local(session=session, research_id=research, report_id=report_ref,
        branch_ref=branch, projection=payload(), expected_revision=None)


def test_initial_publication_registers_only_report_and_reuses_it_for_branches(tmp_path):
    service, manager, store, _auth = harness(tmp_path)
    first = publish(service)
    assert publish(service)['idempotent'] is True
    other = publish(service, branch='review')
    assert first['publication_id'] != other['publication_id'] and manager.ensure_calls == 1
    assert {doc['kind'] for doc in store.docs.values()} == {'research_report', 'research_report_registration'}
    receipt = next(doc for doc in store.docs.values() if doc['kind'] == 'research_report_registration')
    assert receipt['state'] == 'registered' and 'projection' not in receipt
    assert service.read(session=SESSION, research_id=RESEARCH, report_id=REPORT,
                        branch_ref='main')['projection']['report_id'] == REPORT


def test_metadata_read_does_not_read_report_bodies_and_honors_revocation(tmp_path, monkeypatch):
    service, _manager, store, auth = harness(tmp_path)
    publish(service)
    monkeypatch.setattr(store, 'get_attachment', lambda *_args: (_ for _ in ()).throw(AssertionError('body read')))
    value = service.read(session=SESSION, research_id=RESEARCH, report_id=REPORT, branch_ref='main', metadata_only=True)
    assert value['publication']['report_id'] == REPORT and 'projection' not in value
    auth['read'] = False
    with pytest.raises(PermissionError):
        service.read(session=SESSION, research_id=RESEARCH, report_id=REPORT, branch_ref='main', metadata_only=True)


@pytest.mark.parametrize('revoked', ['admit', 'write', 'share'])
def test_retry_never_recreates_revoked_public_access_or_report_policy(tmp_path, revoked):
    service, manager, store, auth = harness(tmp_path)
    publish(service)
    auth[revoked] = False
    before = store.writes
    with pytest.raises(PermissionError): publish(service, branch='later')
    assert manager.ensure_calls == 1 and store.writes == before


def test_foreign_resource_and_removed_existing_resource_are_never_adopted(tmp_path):
    service, manager, store, _auth = harness(tmp_path)
    manager.resource = {'_id': 'foreign', 'name': keycloak_resource_name('research_report', REPORT),
                        'attributes': {'traderesearch_owner_subject': ['somebody-else']}}
    with pytest.raises(AuthorizationUnavailable, match='another registration'): publish(service)
    assert manager.ensure_calls == 0 and all(doc['kind'] != 'research_report' for doc in store.docs.values())
    service, manager, store, _auth = harness(tmp_path / 'second')
    publish(service)
    manager.resource = None
    with pytest.raises(AuthorizationUnavailable, match='needs repair'): publish(service, branch='later')
    assert manager.ensure_calls == 1


def test_uncertain_registration_only_recovers_if_resource_is_confirmed_without_regrant(tmp_path):
    service, manager, _store, _auth = harness(tmp_path)
    manager.failure = 'after'
    with pytest.raises(AuthorizationUnavailable): publish(service)
    manager.failure = ''
    assert publish(service)['report_id'] == REPORT and manager.ensure_calls == 1
    service, manager, _store, _auth = harness(tmp_path / 'before')
    manager.failure = 'before'
    with pytest.raises(AuthorizationUnavailable): publish(service)
    manager.failure = ''
    with pytest.raises(AuthorizationUnavailable, match='needs repair'): publish(service)
    assert manager.ensure_calls == 1


def test_concurrent_branches_share_one_resource_registration(tmp_path):
    service, manager, _store, _auth = harness(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda branch: publish(service, branch=branch), ['main', 'review']))
    assert manager.ensure_calls == 1 and len({value['publication_id'] for value in values}) == 2


def test_invalid_input_and_unverified_identity_do_not_create_records(tmp_path):
    service, manager, store, _auth = harness(tmp_path)
    with pytest.raises(ValueError): publish(service, research='research:v1:short')
    with pytest.raises(PermissionError): publish(service, session={**SESSION, 'tr_identity_id': 'different'})
    with pytest.raises(ValueError): publish(service, branch='')
    with pytest.raises(ValueError):
        service.publish_local(session=SESSION, research_id=RESEARCH, report_id=REPORT,
            branch_ref='main', projection=payload(), expected_revision=1)
    assert manager.ensure_calls == 0 and not store.docs


def test_report_grants_are_exact_stable_identity_and_live_revoke(tmp_path):
    service, manager, _store, auth = harness(tmp_path)
    publish(service)
    args = {'session': SESSION, 'research_id': RESEARCH, 'report_id': REPORT}
    assert service.set_grant(**args, identity_id='stable-bob', scopes=['read']) is True
    assert service.list_grants(**args) == [{'identity_id': 'stable-bob', 'subject': 'subject-bob', 'scopes': ['read']}]
    auth['share'] = False
    with pytest.raises(PermissionError): service.list_grants(**args)
    with pytest.raises(PermissionError): service.set_grant(**args, identity_id='stable-bob', scopes=[])
    assert 'stable-bob' in manager.grants
    auth['share'] = True
    with pytest.raises(LookupError): service.set_grant(**args, identity_id='same-name-on-another-server', scopes=['read'])
    with pytest.raises(ValueError): service.set_grant(**args, identity_id='stable-bob', scopes=['share'])
    assert service.set_grant(**args, identity_id='stable-bob', scopes=[]) is True
    assert service.list_grants(**args) == []


def test_report_grants_never_cross_report_or_research_registration(tmp_path):
    service, manager, _store, _auth = harness(tmp_path)
    publish(service)
    args = {'session': SESSION, 'research_id': 'research:v1:' + 'Q' * 24, 'report_id': REPORT}
    with pytest.raises(AuthorizationUnavailable, match='requires repair'):
        service.set_grant(**args, identity_id='stable-bob', scopes=['read'])
    assert manager.grants == {}


def test_local_grant_routes_do_not_open_legacy_catalog(tmp_path, monkeypatch):
    from server.manager.http import research_catalog_routes as routes

    service, manager, _store, auth = harness(tmp_path)
    publish(service)
    replies = []
    monkeypatch.setattr(routes, 'json_response', lambda _handler, payload, status=200: replies.append((status, payload)))
    class Handler(routes.ResearchCatalogRoutesMixin):
        state = service.state
        def _session(self): return SESSION
        def _research_catalog_service(self): raise AssertionError('legacy catalog must not be opened')
        def _refresh_research_catalog(self, _principal): raise AssertionError('legacy sync must not run')
        def _research_couch_service(self, *, local=False):
            assert local is True
            return service
        def _json_body(self, _maximum):
            return {'research_id': RESEARCH, 'report_id': REPORT, 'identity_id': 'stable-bob', 'scopes': ['read']}
    path = '/api/research/local-report-publication/grants'
    handler = Handler()
    assert handler._post_research_catalog_routes(SimpleNamespace(path=path, query=''))
    assert replies[-1][0] == 200 and replies[-1][1]['changed'] is True
    query = urlencode({'research_id': RESEARCH, 'report_id': REPORT})
    assert handler._get_research_catalog_routes(SimpleNamespace(path=path, query=query))
    assert replies[-1][1]['grants'][0]['identity_id'] == 'stable-bob'
    auth['share'] = False
    assert handler._post_research_catalog_routes(SimpleNamespace(path=path, query=''))
    assert replies[-1][0] == 403 and 'stable-bob' in manager.grants

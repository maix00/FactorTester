from __future__ import annotations

import base64
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlencode

import pytest

from server.manager import runtime as manager
from server.manager.http.peer_handler import peer_control_handler
from server.manager.transfers.node_client import NodeControlClient
from server.manager.transfers.node_keys import NodeKey

RESEARCH = 'research:v1:' + 'R' * 24
REPORT = 'report:v1:' + 'P' * 24
PUBLICATION = 'p-' + 'a' * 64


def test_signed_peer_report_uses_delegated_target_identity_and_live_decisions(tmp_path, monkeypatch):
    from server.identity import federated_peer_delegation as delegation
    from server.identity.request_context import current_verified_identity
    from server.manager.services import local_report_publication, research_couchdb_publication

    state = manager.ManagerState(tmp_path / 'repo', 'python', server_role='main',
        server_id='target', state_root=tmp_path / 'state')
    key = NodeKey.load_or_create(tmp_path / 'source.key', node_id='source')
    state.node_identities.enroll(key.public_record())
    identity = {'username': 'target-name', 'tr_identity_id': 'stable-person',
                'keycloak_issuer': 'https://target/realms/t', 'keycloak_subject': 'target-subject'}
    live, calls = {'peer': True, 'report': True}, []
    def accept(_state, binding, *, assertion, stable_id, target_scope):
        assert binding == 'source' and assertion == 'source-assertion'
        assert stable_id == 'stable-person' and target_scope == 'read'
        if not live['peer']: raise PermissionError('peer access revoked')
        return SimpleNamespace(target_session=identity, target_token='target-token', source_username='source-name')
    monkeypatch.setattr(delegation, 'bound_peer', lambda _state, node_id: node_id)
    monkeypatch.setattr(delegation, 'accept_from_peer', accept)
    monkeypatch.setattr(research_couchdb_publication, 'report_store_from_environment', lambda: 'target-couch')
    class ReportService:
        def __init__(self, *, state, store): assert store == 'target-couch'
        def read(self, *, session, research_id, report_id, publication_ref, branch_ref, attachment):
            assert current_verified_identity() == ('target-token', identity)
            assert session == identity and research_id == RESEARCH and report_id == REPORT
            if not live['report']: raise PermissionError('report access revoked')
            calls.append((publication_ref, branch_ref, attachment))
            if attachment: return {'content': b'exact-report-object', 'content_type': 'image/png'}
            return {'publication': {'publication_id': PUBLICATION, 'report_id': REPORT,
                                    'storage_server_id': 'target', 'branch_ref': 'main'},
                    'projection': {'report_id': REPORT}}
    monkeypatch.setattr(local_report_publication, 'LocalReportPublicationService', ReportService)
    server = ThreadingHTTPServer(('127.0.0.1', 0), peer_control_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = NodeControlClient(f'http://127.0.0.1:{server.server_address[1]}', key=key)
    request = {'kind': 'shared-report', 'operation': 'read', 'requester_server_id': 'source',
               'identity_id': 'stable-person', 'delegation_assertion': 'source-assertion',
               'principal': 'attacker-provided', 'payload': {'research_id': RESEARCH,
                    'report_id': REPORT, 'publication_ref': PUBLICATION}}
    try:
        result = client.signed_json('/api/federation/public-data', request)
        assert result['publication']['report_id'] == REPORT and calls[-1][0] == PUBLICATION
        request['payload']['attachment'] = 'research_asset/one'
        result = client.signed_json('/api/federation/public-data', request)
        assert base64.b64decode(result['content_base64']) == b'exact-report-object'
        live['report'] = False
        with pytest.raises(HTTPError) as denied: client.signed_json('/api/federation/public-data', request)
        assert denied.value.code == 403
        live['report'], live['peer'] = True, False
        with pytest.raises(HTTPError) as denied: client.signed_json('/api/federation/public-data', request)
        assert denied.value.code == 403
        request['requester_server_id'] = 'forged'
        with pytest.raises(HTTPError) as denied: client.signed_json('/api/federation/public-data', request)
        assert denied.value.code == 403 and len(calls) == 2
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_browser_remote_report_does_not_fall_back_to_local_or_stale(tmp_path, monkeypatch):
    from server.identity import server_admission
    from server.manager.http import research_catalog_routes as routes
    from server.modules.single_factor_test import execution_nodes
    session = {'username': 'source-name'}
    calls, responses = [], []
    gateway = SimpleNamespace(public_data=lambda route, **kw: calls.append((route, kw)) or {
        'publication': {'publication_id': PUBLICATION, 'report_id': REPORT,
                        'storage_server_id': 'target', 'branch_ref': 'main'},
        'projection': {'report_id': REPORT}})
    state = SimpleNamespace(server_id='source', federation_gateway=gateway)
    monkeypatch.setattr(server_admission, 'server_admission', lambda *_args, **_kw: (True, ''))
    monkeypatch.setattr(execution_nodes, 'peer_execution_route', lambda _state, peer: peer)
    monkeypatch.setattr(routes, 'json_response', lambda _handler, payload, status=200: responses.append((status, payload)))
    class Handler(routes.ResearchCatalogRoutesMixin):
        def _session(self): return session
        def _bearer_token(self): return 'source-session-token'
        def _research_catalog_service(self): raise AssertionError('no legacy catalog')
        def _research_couch_service(self, *, local=False): raise AssertionError('no local fallback')
    Handler.state = state
    query = urlencode({'research_id': RESEARCH, 'report_id': REPORT, 'branch_ref': 'main', 'server_id': 'target'})
    parsed = SimpleNamespace(path='/api/research/local-report-publication', query=query)
    assert Handler()._get_research_catalog_routes(parsed)
    assert responses[-1][0] == 200 and responses[-1][1]['projection']['report_id'] == REPORT
    assert calls[0][1]['delegated_user_token'] == 'source-session-token'
    assert calls[0][1]['kind'] == 'shared-report'
    monkeypatch.setattr(server_admission, 'server_admission', lambda *_args, **_kw: (False, 'revoked'))
    assert Handler()._get_research_catalog_routes(parsed)
    assert responses[-1][0] == 403
    state.federation_gateway = SimpleNamespace(public_data=lambda *_args, **_kw: (_ for _ in ()).throw(ConnectionError()))
    assert Handler()._get_research_catalog_routes(parsed)
    assert responses[-1][0] == 503


def test_gateway_uses_only_signed_delegated_route_with_report_budget(monkeypatch):
    from server.identity import federated_peer_delegation as delegation
    from server.manager.domain.federation.gateway import FederatedGateway
    from server.manager.transfers import node_client
    calls = []
    state = SimpleNamespace(server_id='source', node_key='signing-key')
    route = SimpleNamespace(server_id='target', peer_control_endpoint='https://peer', remote=True, online=True)
    binding = SimpleNamespace(endpoint='https://verified-peer')
    monkeypatch.setattr(delegation, 'bound_peer', lambda _state, peer, expected_endpoint: binding)
    monkeypatch.setattr(delegation, 'exchange_for_peer', lambda _state, _binding, *, token, principal:
                        ('short-peer-assertion', 'stable-person') if (token, principal) == ('source-token', 'alice') else None)
    class Peer:
        def __init__(self, endpoint, *, key, transport):
            assert endpoint == 'https://verified-peer' and key == 'signing-key'
        def signed_json(self, path, payload, **options):
            calls.append((path, payload, options))
            return {'success': True, 'projection': {'report_id': REPORT}}
    monkeypatch.setattr(node_client, 'NodeControlClient', Peer)
    gateway = FederatedGateway(state=state)
    result = gateway.public_data(route, kind='shared-report', operation='read', principal='alice',
        delegated_user_token='source-token', payload={'research_id': RESEARCH, 'report_id': REPORT})
    assert result['projection']['report_id'] == REPORT
    path, payload, options = calls[0]
    assert path == '/api/federation/public-data' and payload['delegation_assertion'] == 'short-peer-assertion'
    assert payload['identity_id'] == 'stable-person' and 'principal' not in payload
    assert options['max_response_bytes'] == 12 * 1024 * 1024
    route.online = False
    with pytest.raises(ValueError):
        gateway.public_data(route, kind='shared-report', operation='read', principal='alice', delegated_user_token='source-token')


def test_signed_control_response_budget_is_bounded(tmp_path):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def read(self, maximum): return b'x' * maximum
    transport = SimpleNamespace(open=lambda *_args, **_kw: Response())
    client = NodeControlClient('http://localhost', key=NodeKey.load_or_create(tmp_path / 'k', node_id='source'),
                               transport=transport)
    with pytest.raises(ValueError, match='exceeds its budget'):
        client._json_request('/test', method='GET', max_response_bytes=10)
    with pytest.raises(ValueError, match='budget is invalid'):
        client._json_request('/test', method='GET', max_response_bytes=100 * 1024 * 1024)

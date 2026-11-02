from io import BytesIO
from types import SimpleNamespace

import pytest

from server.manager.http import research_catalog_routes as routes
from server.manager.services import research_couchdb_publication as service_module
from server.jobs.storage import couchdb_reports
from tests.server.test_couchdb_research_publication import report
from tests.server.test_research_couchdb_publication import SESSION, harness


def _request(monkeypatch, *, change=lambda _c, _a: None, body=None, configured=True):
    responses = []
    service, catalog, store, auth = harness()
    change(catalog, auth)
    if configured:
        monkeypatch.setenv('TRADERESEARCH_COUCHDB_URL', 'http://isolated-couch')
    else:
        monkeypatch.delenv('TRADERESEARCH_COUCHDB_URL', raising=False)
        monkeypatch.delenv('FACTORTESTER_COUCHDB_URL', raising=False)
    monkeypatch.setattr(couchdb_reports, 'CouchDBObjectStore', lambda *_a, **_kw: store)
    monkeypatch.setattr(service_module, 'ResearchCouchPublicationService', lambda **_kwargs: service)
    monkeypatch.setattr(routes, 'json_response', lambda _handler, payload, status=200: responses.append((status, payload)))
    class Handler(routes.ResearchCatalogRoutesMixin):
        state = service.state
        def _session(self): return SESSION
        def _research_catalog_service(self): return catalog
        def _json_body(self, maximum):
            assert maximum == 32 * 1024 * 1024
            return body or {'branch_ref': 'main', 'projection': report(), 'expected_revision': None}
    handled = Handler()._post_research_catalog_routes(SimpleNamespace(
        path='/api/research/research-1/reports/report-1/couchdb-publication'))
    assert handled and len(responses) == 1
    return responses[0], store


def test_http_route_publishes_selected_report(monkeypatch):
    (status, response), store = _request(monkeypatch)
    assert status == 201 and response['publication']['report_id'] == 'report-1'
    assert store.writes == 1


def test_catalog_report_publication_keeps_verified_editable_source(tmp_path, monkeypatch):
    import base64
    import hashlib
    from tools.cli.release.research_reporting.workspace import initialize_report_workspace
    from tools.cli.release.research_reporting.authoring.tree_projection import load_snapshot
    from tools.cli.release.research_reporting.authoring.tree_bundle import bundle_from_snapshot
    from tools.cli.release.research_reporting.public_research.projection import build_upload_projection

    workspace = initialize_report_workspace(workspace_root=tmp_path, report_workspace_id='workspace',
        branch_id='main', report_id='report-1', workspace_id='research-1', title='Report', branch_ref='report-branch:main')
    root = workspace['package_root']
    snapshot = load_snapshot(package_root=root, branch_id='main')
    bundle = bundle_from_snapshot(snapshot, package_root=root, branch_id='main')
    authoring = {'sha256': hashlib.sha256(bundle).hexdigest(), 'root_ref': snapshot['head']['root_ref'],
                 'content_base64': base64.b64encode(bundle).decode('ascii')}
    body = {'branch_ref': 'main', 'projection': build_upload_projection(snapshot),
            'expected_revision': None, 'authoring': authoring}
    (status, response), store = _request(monkeypatch, body=body)
    assert status == 201
    service, catalog, _unused, _auth = harness()
    service.store = store
    result = service.read(session=SESSION, research_id='research-1', report_id='report-1',
                          publication_ref=response['publication']['publication_id'], metadata_only=True,
                          requires_edit=True)
    assert result['authoring']['sha256'] == authoring['sha256'] and result['edit_authorized'] is True
    class Handler(routes.ResearchCatalogRoutesMixin):
        state = service.state
        def __init__(self): self.wfile, self.status = BytesIO(), None
        def _session(self): return SESSION
        def _research_catalog_service(self): return catalog
        def _research_couch_service(self, *, local=False): return service
        def send_response(self, status): self.status = status
        def send_header(self, *_args): pass
        def end_headers(self): pass
    path = ('/api/research/research-1/reports/report-1/couchdb-publication/'
            + response['publication']['publication_id'] + '/attachments/report_authoring/' + authoring['sha256'])
    handler = Handler()
    assert handler._get_research_catalog_routes(SimpleNamespace(path=path, query=''))
    assert handler.status == 200 and handler.wfile.getvalue() == bundle
    _auth['write'] = False
    with pytest.raises(PermissionError):
        service.read(session=SESSION, research_id='research-1', report_id='report-1',
                     publication_ref=response['publication']['publication_id'],
                     attachment='report_authoring/' + authoring['sha256'])
    (status, _response), denied_store = _request(monkeypatch, body=body,
        change=lambda _catalog, auth: auth.update(write=False))
    assert status == 403 and denied_store.writes == 0
    bad = {**body, 'authoring': {**authoring, 'sha256': '0' * 64}}
    (status, _response), rejected_store = _request(monkeypatch, body=bad)
    assert status == 400 and rejected_store.writes == 0


def test_http_route_denies_live_public_access_revoke(monkeypatch):
    (status, _response), store = _request(monkeypatch, change=lambda _catalog, auth: auth.update(admit=False))
    assert status == 403 and store.writes == 0


def test_http_route_returns_conflict_for_stale_revision(monkeypatch):
    (status, response), store = _request(monkeypatch,
        body={'branch_ref': 'main', 'projection': report(), 'expected_revision': '1-old'})
    assert status == 409 and response['code'] == 'research_publication_conflict'
    assert store.writes == 0


def test_http_route_fails_closed_when_couchdb_is_not_configured(monkeypatch):
    (status, response), store = _request(monkeypatch, configured=False)
    assert status == 503 and response['code'] == 'research_store_unavailable' and store.writes == 0


def test_http_route_rejects_unrelated_report_fields(monkeypatch):
    (status, _response), store = _request(monkeypatch,
        body={'branch_ref': 'main', 'projection': report(), 'sibling_report': {'body': 'private'}})
    assert status == 400 and store.writes == 0


def test_http_route_reads_exact_publication_and_attachment_without_legacy_refresh(monkeypatch):
    service, catalog, _store, auth = harness()
    receipt = service.publish(session=SESSION, research_id='research-1', report_id='report-1',
        branch_ref='main', projection=report(), expected_revision=None)
    replies = []
    monkeypatch.setattr(routes, 'json_response', lambda _handler, payload, status=200: replies.append((status, payload)))
    class Handler(routes.ResearchCatalogRoutesMixin):
        state = service.state
        def __init__(self): self.wfile, self.status, self.headers = BytesIO(), None, {}
        def _session(self): return SESSION
        def _research_catalog_service(self): return catalog
        def _research_couch_service(self, *, local=False): return service
        def _refresh_research_catalog(self, _principal): raise AssertionError('legacy refresh must not run')
        def send_response(self, status): self.status = status
        def send_header(self, name, value): self.headers[name] = value
        def end_headers(self): pass
    base = '/api/research/research-1/reports/report-1/couchdb-publication/' + receipt['publication_id']
    handler = Handler()
    assert handler._get_research_catalog_routes(SimpleNamespace(path=base, query=''))
    assert replies[-1][0] == 200 and replies[-1][1]['projection']['report_id'] == 'report-1'
    branch_path = base.rsplit('/', 1)[0]
    assert handler._get_research_catalog_routes(SimpleNamespace(path=branch_path, query='branch_ref=main'))
    assert replies[-1][1]['publication']['publication_id'] == receipt['publication_id']
    assert handler._get_research_catalog_routes(SimpleNamespace(path=base + '/attachments/research_asset/image-1', query=''))
    assert handler.status == 200 and handler.wfile.getvalue() == b'picture'
    assert handler.headers['X-Content-Type-Options'] == 'nosniff'
    auth['read'] = False
    assert handler._get_research_catalog_routes(SimpleNamespace(path=base, query=''))
    assert replies[-1][0] == 403


@pytest.mark.parametrize('path', ['/api/research/migrations/reports', '/api/research/migrations/reports/discover'])
def test_retired_import_does_not_discover_or_apply_legacy_acl(monkeypatch, path):
    responses = []
    monkeypatch.setattr(routes, 'json_response', lambda _handler, payload, status=200: responses.append((status, payload)))
    class Handler(routes.ResearchCatalogRoutesMixin):
        def _research_catalog_session(self): return SESSION
        def _research_catalog_service(self): return object()
        def _research_catalog_body(self, maximum):
            return {'apply': True, 'records': [{'owner_ref': 'another-user', 'visibility': 'public'}]}
    assert Handler()._post_research_catalog_routes(SimpleNamespace(path=path))
    assert responses[0][0] == 410 and responses[0][1]['success'] is False
    assert not hasattr(routes.ResearchCatalogRoutesMixin, '_discover_research_report_records')

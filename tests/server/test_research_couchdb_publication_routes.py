from io import BytesIO
from types import SimpleNamespace

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
        def _research_couch_service(self): return service
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

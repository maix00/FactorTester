"""Bounded Manager discovery through the actual desktop Research RPC and HTTP route."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from tests.server.test_research_catalog_keycloak_reads import _fixture, _grant
from tools.cli.release.research_reporting.local_rpc import LocalResearchRPC


def test_discovery_queues_authorized_changes_without_opening_research_page(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    from server.manager.http import research_catalog_routes as routes

    catalog, a, b, permissions, calls = _fixture(tmp_path / 'manager')
    from tools.data.sqlite.db import connect_sqlite
    with connect_sqlite(catalog.db_path) as db:
        db.execute('UPDATE research_catalog_researches SET updated_at=10')
    denied, allowed = sorted([a, b])
    _grant(permissions, 'research', allowed, 'read')
    identity = {'username': 'alice', 'keycloak_issuer': 'https://id.test/realm',
                'keycloak_subject': 'subject', 'tr_identity_id': 'stable'}

    class Handler(routes.ResearchCatalogRoutesMixin, BaseHTTPRequestHandler):
        state = type('State', (), {'research_catalog': catalog})()
        def log_message(self, *_args): pass
        def _session(self):
            return identity if self.headers.get('Authorization') == 'Bearer test-token' else None
        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == '/api/session':
                body = json.dumps(identity).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            elif not self._get_research_catalog_routes(parsed):
                self.send_error(404)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    manager = {'endpoint': f'http://127.0.0.1:{server.server_port}', 'subject': 'subject', 'token': 'test-token',
               'certificate_pem': '', 'cookies': []}
    rpc = LocalResearchRPC(tmp_path / 'client', issuer=identity['keycloak_issuer'], identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Alice'}], manager=manager)
    discover = {'action': 'discover_researches', 'profile_id': 'self', 'cursor': '', 'limit': 1}
    sync = {'action': 'sync_reports', 'profile_id': 'self', 'after_report_id': '', 'limit': 4}
    try:
        first = rpc.request(discover)
        assert first['queued'] == 0 and first['next_cursor'] and denied not in first['next_cursor']
        # A Manager restart invalidates a cursor without dropping any pending work.
        monkeypatch.setattr(routes, '_OWNED_SYNC_CURSOR', Fernet(Fernet.generate_key()))
        expired = rpc.request({**discover, 'cursor': first['next_cursor']})
        assert expired == {'success': False, 'code': 'local_research_cursor_expired'}
        first = rpc.request(discover)
        second = rpc.request({**discover, 'cursor': first['next_cursor']})
        assert second['queued'] == 1 and second['next_cursor'] is None
        permissions.clear()
        assert rpc.request(sync)['researches'] == [{'research_id': allowed, 'status': 'denied'}]
        assert rpc.store.get(profile_id='self', research_id=allowed) is None
        _grant(permissions, 'research', allowed, 'read')
        assert rpc.request(sync)['researches'] == [{'research_id': allowed, 'status': 'imported'}]
        assert rpc.store.get(profile_id='self', research_id=allowed)['title']
        # Rescans do not enqueue an unchanged origin; newly granted objects are
        # picked up on a later scan even if they preceded the former cursor.
        _grant(permissions, 'research', denied, 'read')
        assert rpc.request(discover)['queued'] == 1
        assert rpc.request(sync)['researches'] == [{'research_id': denied, 'status': 'imported'}]
        first = rpc.request(discover)
        assert first['queued'] == 0
        assert rpc.request({**discover, 'cursor': first['next_cursor']})['queued'] == 0
        old_title = rpc.store.get(profile_id='self', research_id=denied)['title']
        with connect_sqlite(catalog.db_path) as db:
            db.execute('UPDATE research_catalog_researches SET title=? WHERE research_id=?', ('Changed without revision', denied))
        assert rpc.request(discover)['queued'] == 1
        assert rpc.request(sync)['researches'] == [{'research_id': denied, 'status': 'conflict'}]
        assert rpc.store.get(profile_id='self', research_id=denied)['title'] == old_title
        assert max(size for _token, size in calls) <= 3
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_mixed_migrated_discovery_preserves_refs_and_rejects_invalid_page(tmp_path, monkeypatch):
    import pytest
    from tools.cli.release.research_reporting import local_server_research as module
    from tools.cli.release.research_reporting.local_catalog import LocalResearchCatalog
    from tools.cli.release.research_reporting.local_publication import ensure_publication_table

    store = LocalResearchCatalog(tmp_path, issuer='https://issuer.test/realm', identity_id='stable', profiles={'self'})
    ensure_publication_table(store)
    refs = ['research:migrated:' + 'b' * 32, 'research:v1:' + 'R' * 24]
    items = [{'research_id': ref, 'updated_at': 1.0, 'title': 'Retained research', 'description': ''} for ref in refs]
    class Session:
        def get(self, path, *, query):
            assert path == '/api/research/owned-sync'
            return {'success': True, 'researches': items, 'next_cursor': None}
    monkeypatch.setattr(module, 'manager_session', lambda *_: ('https://manager.test', Session()))
    kwargs = dict(binding={}, manager={'endpoint': 'https://manager.test'}, profile_id='self', cursor='', limit=3)
    assert module.discover_server_researches(store, **kwargs) == {'queued': 2, 'next_cursor': None}
    with store._connect() as db:
        assert {r[0] for r in db.execute('SELECT research_id FROM server_research_pending')} == set(refs)
    for invalid in ('research:migrated:' + 'b' * 31, 'research:migrated:../private', 'research:unknown:' + 'a' * 32):
        items.append({'research_id': invalid, 'updated_at': 1.0, 'title': 'Invalid', 'description': ''})
        with pytest.raises(ValueError, match='response is invalid'):
            module.discover_server_researches(store, **kwargs)
        items.pop()
    with store._connect() as db:
        assert db.execute('SELECT count(*) FROM server_research_pending').fetchone()[0] == 2

"""Real HTTP client and SQLite coverage for a first server Research import."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

import pytest

from tools.cli.release.research_reporting.local_rpc import LocalResearchRPC


def test_owned_research_import_retries_and_never_overwrites_local_changes(tmp_path):
    research_id = 'research:v1:' + 'R' * 24
    identity = {'username': 'alice', 'keycloak_issuer': 'https://id.test/realm',
                'keycloak_subject': 'subject', 'tr_identity_id': 'stable'}
    item = {'research_id': research_id, 'owner_ref': 'alice', 'is_owned': True, 'status': 'active',
            'title': 'Research', 'description': 'Server description', 'created_at': 1.0, 'updated_at': 2.0,
            'access': {'can_view': True}}
    state = {'fail': True, 'revoke_after_read': False, 'session_calls': 0, 'research_calls': 0, 'revoke_research': False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if self.headers.get('Authorization') != 'Bearer token': return self.reply(401, {})
            path = unquote(urlsplit(self.path).path)
            if path == '/api/session':
                state['session_calls'] += 1
                if state['revoke_after_read'] and state['session_calls'] >= 3: return self.reply(403, {})
                return self.reply(200, identity)
            if path == '/api/research/' + research_id:
                if state['fail']: return self.reply(503, {})
                state['research_calls'] += 1
                if state['revoke_research'] and state['research_calls'] >= 2: return self.reply(403, {})
                return self.reply(200, {'success': True, 'research': item})
            return self.reply(404, {})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    manager = {'endpoint': f'http://127.0.0.1:{server.server_port}', 'subject': 'subject', 'token': 'token',
               'certificate_pem': '', 'cookies': []}
    rpc = LocalResearchRPC(tmp_path, issuer=identity['keycloak_issuer'], identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Alice'}], manager=manager)
    request = {'action': 'import_research', 'profile_id': 'self', 'research_id': research_id}
    sync = {'action': 'sync_reports', 'profile_id': 'self', 'after_report_id': '', 'limit': 4}
    try:
        queue = {'action': 'queue_researches', 'profile_id': 'self', 'research_ids': [research_id]}
        assert rpc.request(queue)['queued'] == 1
        assert rpc.request(queue)['queued'] == 0
        with pytest.raises(ValueError): rpc.request({**queue, 'research_ids': [research_id, research_id]})
        with pytest.raises(PermissionError): rpc.request({**queue, 'profile_id': 'other'})
        with pytest.raises(RuntimeError): rpc.request(request)
        assert rpc.store.get(profile_id='self', research_id=research_id) is None
        with rpc.store._connect() as db: assert db.execute('SELECT count(*) FROM server_research_pending').fetchone()[0] == 1
        state['fail'] = False
        assert rpc.request(sync)['researches'] == [{'research_id': research_id, 'status': 'imported'}]
        assert rpc.store.get(profile_id='self', research_id=research_id)['title'] == 'Research'
        assert rpc.request(request)['status'] == 'unchanged'
        item.update(title='Updated', updated_at=3.0)
        state.update(revoke_after_read=True, session_calls=0)
        assert rpc.request(request) == {'success': False, 'code': 'local_report_publication_denied'}
        assert rpc.store.get(profile_id='self', research_id=research_id)['title'] == 'Research'
        state.update(revoke_after_read=False, session_calls=0, revoke_research=True, research_calls=0)
        assert rpc.request(request) == {'success': False, 'code': 'local_report_publication_denied'}
        assert rpc.store.get(profile_id='self', research_id=research_id)['title'] == 'Research'
        state.update(revoke_research=False, session_calls=0, research_calls=0)
        assert rpc.request(sync)['researches'] == [{'research_id': research_id, 'status': 'updated'}]
        with rpc.store._connect() as db:
            db.execute('UPDATE researches SET title=? WHERE research_id=?', ('Local edit', research_id))
        item.update(title='Server edit', updated_at=4.0)
        with pytest.raises(ValueError, match='conflicts'): rpc.request(request)
        assert rpc.store.get(profile_id='self', research_id=research_id)['title'] == 'Local edit'
        assert rpc.request(sync)['researches'][0]['status'] == 'conflict'
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=3)


def test_import_rejects_wrong_owner_before_any_local_copy(tmp_path, monkeypatch):
    from tools.cli.release.research_reporting import local_server_research as module
    identity = {'username':'alice', 'keycloak_issuer':'https://id.test/realm', 'keycloak_subject':'subject', 'tr_identity_id':'stable'}
    research_id = 'research:v1:' + 'R' * 24
    rpc = LocalResearchRPC(tmp_path, issuer=identity['keycloak_issuer'], identity_id='stable',
                           profiles=[{'profile_id':'self','display_name':'Alice'}],
                           manager={'endpoint':'https://manager.test','subject':'subject','token':'','certificate_pem':'','cookies':[]})
    class Session:
        def get(self, path):
            if path == '/api/session': return identity
            return {'success': True, 'research': {'research_id':research_id,'owner_ref':'other', 'is_owned':True,
                    'status':'active','title':'Secret','description':'','created_at':1,'updated_at':1,'access':{'can_view':True}}}
    monkeypatch.setattr(module, 'manager_session', lambda *_: ('https://manager.test', Session()))
    with pytest.raises(PermissionError):
        rpc.request({'action':'import_research','profile_id':'self','research_id':research_id})
    assert rpc.store.get(profile_id='self', research_id=research_id) is None

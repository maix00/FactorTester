"""Real client HTTP transport to the single-report Keycloak/Couch service seam."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from tests.server.test_local_report_publication import SESSION, harness
from server.jobs.storage.couchdb_research_publication import ResearchPublicationConflict
from tools.cli.release.research_reporting.local_rpc import LocalResearchRPC
from tools.cli.release.research_reporting.public_research.object_uploads import projection_hash


def test_explicit_local_publication_transfers_only_selected_report_and_rechecks_access(tmp_path):
    service, _manager, store, auth = harness(tmp_path / 'manager')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if self.path == '/api/session' and self.headers.get('Authorization') == 'Bearer test-token':
                self.reply(200, SESSION)
            else: self.reply(401, {})
        def do_POST(self):
            if self.path != '/api/research/local-report-publication' or self.headers.get('Authorization') != 'Bearer test-token':
                return self.reply(401, {})
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            try:
                value = service.publish_local(session=SESSION, **data)
                self.reply(201, {'success': True, 'publication': value})
            except PermissionError:
                self.reply(403, {})
            except ResearchPublicationConflict:
                self.reply(409, {})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    manager = {'endpoint': f'http://127.0.0.1:{server.server_port}', 'token': 'test-token', 'certificate_pem': '', 'cookies': []}
    rpc = LocalResearchRPC(tmp_path / 'client', issuer=SESSION['keycloak_issuer'], identity_id=SESSION['tr_identity_id'],
                           profiles=[{'profile_id': 'self', 'display_name': 'Alice'}], manager=manager)
    try:
        research = rpc.request({'action': 'create', 'profile_id': 'self', 'title': 'R', 'description': '', 'operation_id': 'r'})['research']
        create = {'action': 'create_report', 'profile_id': 'self', 'research_id': research['research_id']}
        selected = rpc.request({**create, 'title': 'Selected', 'operation_id': 'one'})['report']
        private = rpc.request({**create, 'title': 'Private', 'operation_id': 'two'})['report']
        request = {'action': 'publish_report', 'profile_id': 'self', 'research_id': research['research_id'], 'report_id': selected['report_id']}
        assert not store.docs
        rpc.binding['identity_id'] = 'different-identity'
        with pytest.raises(PermissionError): rpc.request(request)
        assert not store.docs
        rpc.binding['identity_id'] = SESSION['tr_identity_id']
        published = rpc.request(request)['publication']
        assert rpc.request(request)['publication'] == published
        documents = [doc for doc in store.docs.values() if doc['kind'] == 'research_report']
        assert len(documents) == 1 and documents[0]['report_id'] == selected['report_id']
        assert private['report_id'] not in json.dumps(store.docs)
        head = rpc.request({'action': 'get_report', 'profile_id': 'self', 'research_id': research['research_id'], 'report_id': selected['report_id']})['version']
        edit = {'action': 'add_report_component', 'profile_id': 'self', 'research_id': research['research_id'],
                'report_id': selected['report_id'], 'component_id': 'chapter-1', 'kind': 'chapter', 'parent_id': '',
                'title': 'First', 'body': '', **head}
        next_head = rpc.request(edit)['version']
        second = rpc.request(request)['publication']
        assert second['generation'] == 1 and second['revision'] != published['revision']
        remote = service.read(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'], branch_ref='main')['projection']
        remote['generation'] = 2; remote['title'] = 'Other client'; remote['projection_hash'] = projection_hash(remote)
        service.publish_local(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'],
            branch_ref='main', projection=remote, expected_revision=second['revision'])
        rpc.request({**edit, **next_head, 'component_id': 'chapter-2', 'title': 'Second'})
        assert rpc.request(request) == {'success': False, 'code': 'local_report_publication_conflict'}
        auth['admit'] = False
        assert rpc.request(request) == {'success': False, 'code': 'local_report_publication_denied'}
        assert len([doc for doc in store.docs.values() if doc['kind'] == 'research_report']) == 1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)

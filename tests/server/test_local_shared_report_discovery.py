"""Two fresh native stores discover and synchronize one explicitly shared report."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from tests.server.test_couchdb_local_report_directory import ViewCouch
from tests.server.test_local_report_publication import SESSION, harness
from tools.cli.release.research_reporting.local_rpc import LocalResearchRPC


def test_fresh_device_discovers_one_shared_report_and_syncs_both_directions(tmp_path):
    service, _manager, _store, auth = harness(tmp_path / 'server')
    store = service.store = ViewCouch()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            if self.headers.get('Authorization') != 'Bearer test-token': return self.reply(401, {})
            if self.path == '/api/session': return self.reply(200, SESSION)
            parsed = urlsplit(self.path); query = parse_qs(parsed.query); parts = parsed.path.strip('/').split('/')
            try:
                if parsed.path == '/api/research/owned-local-report-sync':
                    return self.reply(200, {'success': True, **service.owned_page(session=SESSION,
                        after=query.get('cursor', [''])[0], limit=int(query.get('limit', ['4'])[0]))})
                if not parsed.path.startswith('/api/research/local-report-publication'):
                    return self.reply(404, {})
                args = {'session': SESSION, 'research_id': query['research_id'][0], 'report_id': query['report_id'][0]}
                if len(parts) == 3:
                    value = service.read(**args, branch_ref=query['branch_ref'][0],
                        metadata_only=query.get('metadata_only') == ['1'], requires_edit=query.get('requires_edit') == ['1'],
                        requires_publish=query.get('requires_publish') == ['1'])
                    if query.get('owner_metadata') == ['1']:
                        value['owner_metadata'] = service.owner_metadata(**args)
                    return self.reply(200, {'success': True, **value})
                if len(parts) == 7 and parts[4] == 'attachments':
                    data = service.read(**args, publication_ref=parts[3], attachment=parts[5] + '/' + parts[6])['content']
                    self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data); return
                return self.reply(404, {})
            except PermissionError:
                return self.reply(403, {})
        def do_POST(self):
            if self.headers.get('Authorization') != 'Bearer test-token': return self.reply(401, {})
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            try:
                return self.reply(201, {'success': True, 'publication': service.publish_local(session=SESSION, **body)})
            except PermissionError:
                return self.reply(403, {})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    manager = {'endpoint': f'http://127.0.0.1:{server.server_port}', 'subject': SESSION['keycloak_subject'],
               'token': 'test-token', 'certificate_pem': '', 'cookies': []}
    def client(name):
        return LocalResearchRPC(tmp_path / name, issuer=SESSION['keycloak_issuer'], identity_id=SESSION['tr_identity_id'],
                                profiles=[{'profile_id': 'self', 'display_name': 'Alice'}], manager=manager)
    try:
        first, second = client('first'), client('second')
        research = first.request({'action':'create', 'profile_id':'self', 'title':'Duration research',
                                  'description':'private notes', 'operation_id':'research'})['research']
        create = {'action':'create_report', 'profile_id':'self', 'research_id':research['research_id']}
        report = first.request({**create, 'title':'Shared', 'operation_id':'shared'})['report']
        private = first.request({**create, 'title':'Private', 'operation_id':'private'})['report']
        publication = {'profile_id':'self', 'research_id':research['research_id'], 'report_id':report['report_id']}
        first.request({'action':'publish_report', **publication})
        sync = {'action':'sync_reports', 'profile_id':'self', 'after_report_id':'', 'limit':4}
        result = second.request(sync)
        assert result['report_imports'] == [{'research_id':research['research_id'], 'report_id':report['report_id'], 'status':'imported'}]
        assert second.request({'action':'get', 'profile_id':'self', 'research_id':research['research_id']})['research']['title'] == 'Duration research'
        listing = second.request({'action':'list_reports', 'profile_id':'self', 'research_id':research['research_id'], 'limit':10, 'offset':0})
        assert [item['report_id'] for item in listing['reports']] == [report['report_id']]
        assert private['report_id'] not in json.dumps(store.docs) and 'private notes' not in json.dumps(store.docs)
        head = second.request({'action':'get_report', **publication})['version']
        second.request({'action':'add_report_component', **publication, 'component_id':'section', 'kind':'chapter',
                        'parent_id':'', 'title':'From second device', 'body':'', **head})
        assert second.request(sync)['reports'][0]['status'] == 'published'
        assert first.request(sync)['reports'][0]['status'] == 'updated'
        index = first.request({'action':'get_report', **publication})['index']
        assert [item['title'] for item in index['chapters']] == ['From second device']
        auth['write'] = False
        readonly = service.owned_page(session=SESSION)['reports'][0]
        assert readonly['editable'] is False and readonly['authoring'] is None
        third = client('readonly')
        result = third.request(sync)
        assert result['report_imports'] == [] and result['report_scans'][0]['status'] == 'denied'
        assert third.request({'action':'get', 'profile_id':'self', 'research_id':research['research_id']})['code'] == 'local_research_not_found'
        auth['write'] = True
        auth['read'] = False
        assert service.owned_page(session=SESSION)['reports'] == []
        assert second.request(sync)['reports'][0]['status'] == 'denied'
        assert [item['title'] for item in second.request({'action':'get_report', **publication})['index']['chapters']] == ['From second device']
        auth['read'] = True
        assert second.request(sync)['reports'][0]['status'] == 'unchanged'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)

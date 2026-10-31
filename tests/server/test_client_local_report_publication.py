"""Real client HTTP transport to the single-report Keycloak/Couch service seam."""
import base64
import hashlib
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from tests.server.test_local_report_publication import SESSION, harness
from server.jobs.storage.couchdb_research_publication import ResearchPublicationConflict
from tools.cli.release.research_reporting.local_rpc import LocalResearchRPC
from tools.cli.release.research_reporting.authoring.tree_bundle import export_report_bundle
from tools.cli.release.research_reporting.authoring.tree_projection import load_snapshot
from tools.cli.release.research_reporting.public_research.projection import build_upload_projection


def test_explicit_local_publication_transfers_only_selected_report_and_rechecks_access(tmp_path, monkeypatch):
    service, _manager, store, auth = harness(tmp_path / 'manager')
    transport = {'tamper': False, 'metadata': 0, 'downloads': 0, 'posts': 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if self.path == '/api/session' and self.headers.get('Authorization') == 'Bearer test-token':
                return self.reply(200, SESSION)
            if self.headers.get('Authorization') != 'Bearer test-token':
                return self.reply(401, {})
            parsed = urlsplit(self.path); query = parse_qs(parsed.query); parts = parsed.path.strip('/').split('/')
            if not parsed.path.startswith('/api/research/local-report-publication'):
                return self.reply(404, {})
            try:
                args = {'session': SESSION, 'research_id': query['research_id'][0], 'report_id': query['report_id'][0]}
                if len(parts) == 3:
                    metadata_only = query.get('metadata_only') == ['1']
                    if metadata_only: transport['metadata'] += 1
                    value = service.read(**args, branch_ref=query['branch_ref'][0], metadata_only=metadata_only,
                                         requires_publish=query.get('requires_publish') == ['1'])
                    return self.reply(200, {'success': True, **value})
                if len(parts) == 7 and parts[4] == 'attachments':
                    transport['downloads'] += 1
                    value = service.read(**args, publication_ref=parts[3], attachment=parts[5] + '/' + parts[6])
                    raw = value['content']
                    if transport['tamper']: raw = raw[:-1] + bytes([raw[-1] ^ 1])
                    self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw); return
                self.reply(404, {})
            except PermissionError:
                self.reply(403, {})
        def do_POST(self):
            if self.path != '/api/research/local-report-publication' or self.headers.get('Authorization') != 'Bearer test-token':
                return self.reply(401, {})
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            transport['posts'] += 1
            try:
                value = service.publish_local(session=SESSION, **data)
                self.reply(201, {'success': True, 'publication': value})
            except PermissionError:
                self.reply(403, {})
            except ResearchPublicationConflict:
                self.reply(409, {})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    manager = {'endpoint': f'http://127.0.0.1:{server.server_port}', 'subject': SESSION['keycloak_subject'], 'token': 'test-token', 'certificate_pem': '', 'cookies': []}
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
        manager['subject'] = 'different-subject'
        with pytest.raises(PermissionError): rpc.request(request)
        assert not store.docs
        manager['subject'] = SESSION['keycloak_subject']
        published = rpc.request(request)['publication']
        assert rpc.request(request)['publication'] == published
        auto = {'action': 'sync_reports', 'profile_id': 'self', 'after_report_id': '', 'limit': 4}
        metadata_before = transport['metadata']
        auto_result = rpc.request(auto)
        assert auto_result['reports'] == [{'research_id': research['research_id'], 'report_id': selected['report_id'], 'status': 'unchanged'}]
        assert auto_result['next_report_id'] is None and transport['metadata'] == metadata_before + 1 and transport['downloads'] == 0
        published_view = service.read(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'], branch_ref='main')
        authoring_path = 'report_authoring/' + published_view['authoring']['sha256']
        assert service.read(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'], branch_ref='main', attachment=authoring_path)['content']
        auth['write'] = False
        assert service.read(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'], branch_ref='main')['projection']['report_id'] == selected['report_id']
        with pytest.raises(PermissionError):
            service.read(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'], branch_ref='main', attachment=authoring_path)
        auth['write'] = True
        documents = [doc for doc in store.docs.values() if doc['kind'] == 'research_report']
        assert len(documents) == 1 and documents[0]['report_id'] == selected['report_id']
        assert private['report_id'] not in json.dumps(store.docs)
        head = rpc.request({'action': 'get_report', 'profile_id': 'self', 'research_id': research['research_id'], 'report_id': selected['report_id']})['version']
        edit = {'action': 'add_report_component', 'profile_id': 'self', 'research_id': research['research_id'],
                'report_id': selected['report_id'], 'component_id': 'chapter-1', 'kind': 'chapter', 'parent_id': '',
                'title': 'First', 'body': '', **head}
        next_head = rpc.request(edit)['version']
        auth['share'] = False
        posts_before = transport['posts']
        assert rpc.request(auto)['reports'][0]['status'] == 'denied'
        assert transport['posts'] == posts_before
        auth['share'] = True
        assert rpc.request(auto)['reports'][0]['status'] == 'published'
        second = service.read(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'], branch_ref='main', metadata_only=True)['publication']
        assert second['generation'] == 1 and second['revision'] != published['revision']
        shutil.copytree(tmp_path / 'client', tmp_path / 'client-2')
        other = LocalResearchRPC(tmp_path / 'client-2', issuer=SESSION['keycloak_issuer'], identity_id=SESSION['tr_identity_id'],
                                 profiles=[{'profile_id': 'self', 'display_name': 'Alice'}], manager=manager)
        remote = service.read(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'], branch_ref='main')['projection']
        with pytest.raises(ResearchPublicationConflict):
            service.publish_local(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'],
                branch_ref='main', projection=remote, expected_revision=second['revision'])
        latest = other.request({**edit, **next_head, 'component_id': 'chapter-2', 'title': 'Second'})['version']
        _report, root = other.store._report_root('self', research['research_id'], selected['report_id'])
        snapshot = load_snapshot(package_root=root, branch_id='main')
        bundle = export_report_bundle(package_root=root, branch_id='main', expected_generation=latest['generation'], expected_root_ref=latest['root_ref'])
        remote = build_upload_projection(snapshot)
        authoring = {'sha256': hashlib.sha256(bundle).hexdigest(), 'root_ref': latest['root_ref'], 'content_base64': base64.b64encode(bundle).decode()}
        with pytest.raises(ValueError):
            service.publish_local(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'],
                branch_ref='main', projection=remote, expected_revision=second['revision'], authoring={**authoring, 'sha256': '0' * 64})
        with pytest.raises(ValueError):
            service.publish_local(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'],
                branch_ref='another', projection=remote, expected_revision=None, authoring=authoring)
        service.publish_local(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'],
            branch_ref='main', projection=remote, expected_revision=second['revision'], authoring=authoring)
        pull = {'action': 'pull_report', 'profile_id': 'self', 'research_id': research['research_id'], 'report_id': selected['report_id']}
        auth['write'] = False
        assert rpc.request(pull) == {'success': False, 'code': 'local_report_publication_denied'}
        assert [chapter['title'] for chapter in rpc.request({'action':'get_report', 'profile_id':'self', 'research_id':research['research_id'], 'report_id':selected['report_id']})['index']['chapters']] == ['First']
        auth['write'] = True
        transport['tamper'] = True
        with pytest.raises(ValueError, match='checksum'): rpc.request(pull)
        assert [chapter['title'] for chapter in rpc.request({'action':'get_report', 'profile_id':'self', 'research_id':research['research_id'], 'report_id':selected['report_id']})['index']['chapters']] == ['First']
        transport['tamper'] = False
        from tools.cli.release.research_reporting import local_pull
        original_commit = local_pull.commit_report_workspace
        def fail_after_staging(workspace, **_kwargs):
            subprocess.run(['git', '-C', str(workspace), 'add', '--all'], check=True)
            raise OSError('commit failed')
        monkeypatch.setattr(local_pull, 'commit_report_workspace', fail_after_staging)
        with pytest.raises(OSError, match='commit failed'): rpc.request(pull)
        assert [chapter['title'] for chapter in rpc.request({'action':'get_report', 'profile_id':'self', 'research_id':research['research_id'], 'report_id':selected['report_id']})['index']['chapters']] == ['First']
        _local_report, local_root = rpc.store._report_root('self', research['research_id'], selected['report_id'])
        assert subprocess.check_output(['git', '-C', str(local_root), 'status', '--porcelain'], text=True).strip() == ''
        monkeypatch.setattr(local_pull, 'commit_report_workspace', original_commit)
        assert rpc.request(auto)['reports'][0]['status'] == 'updated'
        assert rpc.request(pull)['status'] == 'up_to_date'
        index = rpc.request({'action':'get_report', 'profile_id':'self', 'research_id':research['research_id'], 'report_id':selected['report_id']})
        assert [chapter['title'] for chapter in index['index']['chapters']] == ['First', 'Second']
        rpc.request({**edit, **index['version'], 'component_id': 'chapter-3', 'title': 'Third'})
        divergent = other.request({**edit, **latest, 'component_id': 'remote-3', 'title': 'Remote third'})['version']
        snapshot = load_snapshot(package_root=root, branch_id='main')
        bundle = export_report_bundle(package_root=root, branch_id='main', expected_generation=divergent['generation'], expected_root_ref=divergent['root_ref'])
        authoring = {'sha256': hashlib.sha256(bundle).hexdigest(), 'root_ref': divergent['root_ref'], 'content_base64': base64.b64encode(bundle).decode()}
        remote_revision = service.read(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'], branch_ref='main')['publication']['revision']
        service.publish_local(session=SESSION, research_id=research['research_id'], report_id=selected['report_id'],
            branch_ref='main', projection=build_upload_projection(snapshot), expected_revision=remote_revision, authoring=authoring)
        assert rpc.request(request) == {'success': False, 'code': 'local_report_publication_conflict'}
        assert rpc.request(pull) == {'success': False, 'code': 'local_report_sync_conflict'}
        assert rpc.request(auto)['reports'][0]['status'] == 'conflict'
        assert [chapter['title'] for chapter in rpc.request({'action':'get_report', 'profile_id':'self', 'research_id':research['research_id'], 'report_id':selected['report_id']})['index']['chapters']] == ['First', 'Second', 'Third']
        auth['admit'] = False
        assert rpc.request(request) == {'success': False, 'code': 'local_report_publication_denied'}
        assert len([doc for doc in store.docs.values() if doc['kind'] == 'research_report']) == 1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)

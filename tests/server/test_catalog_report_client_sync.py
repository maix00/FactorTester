"""Client synchronizes a catalog-owned report through its real publication service."""
import base64
import hashlib
import json
import os

import pytest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from tests.server.test_research_couchdb_publication import SESSION, harness
from tools.cli.release.research_reporting.authoring.tree_bundle import bundle_from_snapshot
from tools.cli.release.research_reporting.authoring.tree_projection import load_snapshot
from tools.cli.release.research_reporting.local_publication import ensure_publication_table
from tools.cli.release.research_reporting.local_rpc import LocalResearchRPC
from tools.cli.release.research_reporting.public_research.projection import build_upload_projection


def test_catalog_report_uses_catalog_authority_for_sync_and_live_permissions(tmp_path, monkeypatch):
    service, catalog, store, auth = harness()
    ids = {}
    catalog._keycloak_share_target = lambda research, kind, report: (
        ('research_report', report) if (research, kind, report) == (ids['research'], 'report', ids['report'])
        else (_ for _ in ()).throw(ValueError('wrong report')))
    counts = {'posts': 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if self.headers.get('Authorization') != 'Bearer test-token': return self.reply(401, {})
            if self.path == '/api/session': return self.reply(200, SESSION)
            parsed = urlsplit(self.path); parts = [unquote(item) for item in parsed.path.strip('/').split('/')]
            query = parse_qs(parsed.query)
            if len(parts) not in (6, 10) or parts[:2] != ['api', 'research'] or parts[3] != 'reports' or parts[5] != 'couchdb-publication':
                return self.reply(404, {})
            try:
                if len(parts) == 10 and parts[7] == 'attachments':
                    value = service.read(session=SESSION, research_id=parts[2], report_id=parts[4],
                        publication_ref=parts[6], attachment=parts[8] + '/' + parts[9])
                    raw = value['content']
                    self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw); return
                value = service.read(session=SESSION, research_id=parts[2], report_id=parts[4],
                    branch_ref=query['branch_ref'][0], metadata_only=query.get('metadata_only') == ['1'],
                    requires_publish=query.get('requires_publish') == ['1'], requires_edit=query.get('requires_edit') == ['1'])
                self.reply(200, {'success': True, **value})
            except PermissionError: self.reply(403, {})
        def do_POST(self):
            if self.headers.get('Authorization') != 'Bearer test-token': return self.reply(401, {})
            parts = [unquote(item) for item in urlsplit(self.path).path.strip('/').split('/')]
            if len(parts) != 6 or parts[5] != 'couchdb-publication': return self.reply(404, {})
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            try:
                value = service.publish(session=SESSION, research_id=parts[2], report_id=parts[4], **data)
                counts['posts'] += 1
                self.reply(201, {'success': True, 'publication': value})
            except PermissionError: self.reply(403, {})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    endpoint = f'http://127.0.0.1:{server.server_port}'
    manager = {'endpoint': endpoint, 'subject': SESSION['keycloak_subject'], 'token': 'test-token', 'certificate_pem': '', 'cookies': []}
    rpc = LocalResearchRPC(tmp_path / 'client', issuer=SESSION['keycloak_issuer'], identity_id=SESSION['tr_identity_id'],
        profiles=[{'profile_id': 'self', 'display_name': 'Alice'}], manager=manager)
    try:
        research = rpc.request({'action': 'create', 'profile_id': 'self', 'title': 'Research', 'description': '', 'operation_id': 'r'})['research']
        report = rpc.request({'action': 'create_report', 'profile_id': 'self', 'research_id': research['research_id'], 'title': 'Report', 'operation_id': 'p'})['report']
        ids.update(research=research['research_id'], report=report['report_id'])
        _item, root = rpc.store._report_root('self', ids['research'], ids['report'])
        snapshot = load_snapshot(package_root=root, branch_id='main')
        bundle = bundle_from_snapshot(snapshot, package_root=root, branch_id='main')
        authoring = {'sha256': hashlib.sha256(bundle).hexdigest(), 'root_ref': snapshot['head']['root_ref'],
                     'content_base64': base64.b64encode(bundle).decode('ascii')}
        receipt = service.publish(session=SESSION, research_id=ids['research'], report_id=ids['report'], branch_ref='main',
            projection=build_upload_projection(snapshot), authoring=authoring, expected_revision=None)
        second = LocalResearchRPC(tmp_path / 'second', issuer=SESSION['keycloak_issuer'], identity_id=SESSION['tr_identity_id'],
            profiles=[{'profile_id': 'self', 'display_name': 'Alice'}], manager=manager)
        with second.store._connect() as db:
            db.execute('INSERT INTO researches VALUES (?,?,?,?,?,?,?)', (ids['research'], 'self', 'Research', '', 'server-r', 1, 1))
            db.execute('INSERT INTO server_research_origins VALUES (?,?,?,?,?,?)',
                (ids['research'], hashlib.sha256(endpoint.encode()).hexdigest(), 'self', 'Research', '', 1))
        import_request = {'action': 'import_catalog_report', 'profile_id': 'self',
                          'research_id': ids['research'], 'report_id': ids['report']}
        auth['write'] = False
        assert second.request(import_request)['code'] == 'local_report_publication_denied'
        assert second.store.list_reports(profile_id='self', research_id=ids['research'], limit=10, offset=0)['reports'] == []
        auth['write'] = True
        # A crash after rename must be recoverable without replacing the tree.
        real_rename = os.rename
        def interrupted_rename(source, destination):
            real_rename(source, destination)
            raise RuntimeError('simulated interruption')
        monkeypatch.setattr('tools.cli.release.research_reporting.local_catalog_import.os.rename', interrupted_rename)
        with pytest.raises(RuntimeError, match='simulated interruption'):
            second.request(import_request)
        assert second.store.list_reports(profile_id='self', research_id=ids['research'], limit=10, offset=0)['reports'] == []
        monkeypatch.setattr('tools.cli.release.research_reporting.local_catalog_import.os.rename', real_rename)
        assert second.request(import_request)['status'] == 'imported'
        assert second.request(import_request)['status'] == 'already_imported'
        assert second.request({'action': 'get_report', 'profile_id': 'self', 'research_id': ids['research'],
                               'report_id': ids['report']})['version']['generation'] == snapshot['head']['generation']
        ensure_publication_table(rpc.store)
        with rpc.store._connect() as db:
            db.execute('''INSERT INTO report_publications (report_id, manager_hash, publication_id, revision, generation,
                       projection_hash, local_root_ref, source_kind) VALUES (?,?,?,?,?,?,?,?)''',
                       (ids['report'], hashlib.sha256(endpoint.encode()).hexdigest(), receipt['publication_id'], receipt['revision'],
                        receipt['generation'], receipt['projection_hash'], snapshot['head']['root_ref'], 'catalog'))
        auto = {'action': 'sync_reports', 'profile_id': 'self', 'after_report_id': '', 'limit': 4}
        assert rpc.request(auto)['reports'][0]['status'] == 'unchanged'
        head = rpc.request({'action': 'get_report', 'profile_id': 'self', 'research_id': ids['research'], 'report_id': ids['report']})['version']
        rpc.request({'action': 'add_report_component', 'profile_id': 'self', 'research_id': ids['research'], 'report_id': ids['report'],
            'component_id': 'chapter-1', 'kind': 'chapter', 'parent_id': '', 'title': 'Changed', 'body': '', **head})
        auth['share'] = False
        assert rpc.request(auto)['reports'][0]['status'] == 'denied' and counts['posts'] == 0
        auth['share'] = True
        assert rpc.request(auto)['reports'][0]['status'] == 'published' and counts['posts'] == 1
        assert second.request(auto)['reports'][0]['status'] == 'updated'
        imported_index = second.request({'action': 'get_report', 'profile_id': 'self', 'research_id': ids['research'], 'report_id': ids['report']})
        assert imported_index['index']['chapters'][0]['title'] == 'Changed'
        assert len(store.docs) == 1
        with rpc.store._connect() as db:
            assert db.execute('SELECT source_kind FROM report_publications').fetchone()['source_kind'] == 'catalog'
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_existing_local_receipts_remain_local_when_source_is_added(tmp_path):
    from tools.cli.release.research_reporting.local_catalog import LocalResearchCatalog
    catalog = LocalResearchCatalog(tmp_path, issuer='https://issuer', identity_id='stable', profiles={'self'})
    with catalog._connect() as db:
        db.execute('''CREATE TABLE report_publications (
            report_id TEXT NOT NULL, manager_hash TEXT NOT NULL, publication_id TEXT NOT NULL,
            revision TEXT NOT NULL, generation INTEGER NOT NULL, projection_hash TEXT NOT NULL,
            local_root_ref TEXT NOT NULL DEFAULT '', PRIMARY KEY(report_id, manager_hash))''')
        db.execute('INSERT INTO report_publications VALUES (?,?,?,?,?,?,?)',
                   ('report', 'manager', 'publication', 'revision', 1, 'hash', 'root'))
    ensure_publication_table(catalog)
    with catalog._connect() as db:
        row = db.execute('SELECT * FROM report_publications').fetchone()
        assert (row['revision'], row['source_kind']) == ('revision', 'local')

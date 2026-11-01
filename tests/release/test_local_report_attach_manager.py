import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from tools.cli.release.research_reporting import local_catalog_import
from tools.cli.release.research_reporting.authoring.tree_bundle import bundle_from_snapshot
from tools.cli.release.research_reporting.authoring.tree_paths import report_tree_paths
from tools.cli.release.research_reporting.authoring.tree_projection import project_snapshot
from tools.cli.release.research_reporting.authoring.tree_store import load_head, tree_lock
from tools.cli.release.research_reporting.local_publication import ensure_publication_table
from tools.cli.release.research_reporting.local_pull import LocalReportSyncConflict
from tools.cli.release.research_reporting.local_rpc import LocalResearchRPC
from tools.cli.release.research_reporting.public_research.object_uploads import detach_object_bytes
from tools.cli.release.research_reporting.public_research.projection import build_upload_projection


@pytest.fixture
def report(tmp_path, monkeypatch):
    rpc = LocalResearchRPC(tmp_path, issuer='https://id.test/realm', identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Self'}])
    research = rpc.request({'action': 'create', 'profile_id': 'self', 'title': 'Research',
                            'description': '', 'operation_id': 'research'})['research']
    row = rpc.request({'action': 'create_report', 'profile_id': 'self', 'research_id': research['research_id'],
                       'title': 'Report', 'operation_id': 'report'})['report']
    store = rpc.store
    ensure_publication_table(store)
    existing, root = store._report_root('self', research['research_id'], row['report_id'])
    paths = report_tree_paths(root, 'main')
    with tree_lock(paths):
        head = load_head(paths)
        snapshot = project_snapshot(paths, head)
        data = bundle_from_snapshot(snapshot, package_root=root, branch_id='main')
        projection, _ = detach_object_bytes(build_upload_projection(snapshot))
    record = {'report_id': row['report_id'], 'publication_id': 'p-' + 'a' * 64, 'revision': 'revision',
              'generation': head['generation'], 'projection_hash': projection['projection_hash'],
              'owner_ref': 'alice', 'title': 'Report'}
    bundle = {'generation': head['generation'], 'root_ref': head['root_ref'],
              'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    metadata = {'publication': record, 'authoring': bundle}
    identity = {'username': 'alice', 'keycloak_issuer': 'https://id.test/realm',
                'keycloak_subject': 'subject', 'tr_identity_id': 'stable'}
    class Session:
        def get(self, path):
            assert path == '/api/session'
            return identity
        def download(self, _path, *, maximum_bytes):
            assert maximum_bytes == 8 * 1024 * 1024
            return SimpleNamespace(content=data)
    owner_metadata = {'research_title': 'Research', 'revision': 'owner-revision'}
    monkeypatch.setattr(local_catalog_import, '_remote', lambda *_args, **_kwargs: metadata)
    monkeypatch.setattr(local_catalog_import, '_owner_metadata', lambda *_args: owner_metadata)
    return dict(store=store, root=root, existing=existing, metadata=metadata,
                remote={**metadata, 'projection': projection}, owner_metadata=owner_metadata,
                session=Session(), identity=identity, research_id=research['research_id'],
                report_id=row['report_id'], manager_hash='manager-b')


def test_attaches_identical_second_manager_without_rewriting_report(report):
    result = local_catalog_import._attach_identical_shared_report(**report)
    assert result['status'] == 'attached'
    with report['store']._connect() as db:
        receipt = db.execute('SELECT * FROM report_publications WHERE report_id=? AND manager_hash=?',
                             (report['report_id'], 'manager-b')).fetchone()
    assert receipt['revision'] == 'revision' and receipt['source_kind'] == 'local'
    assert receipt['local_root_ref'] == report['metadata']['authoring']['root_ref']


def test_rejects_different_source_bytes_without_creating_receipt(report):
    changed = {**report['remote'], 'authoring': {**report['remote']['authoring'], 'sha256': 'f' * 64}}
    report['remote'] = changed
    with pytest.raises(LocalReportSyncConflict, match='source bytes differ'):
        local_catalog_import._attach_identical_shared_report(**report)
    with report['store']._connect() as db:
        assert db.execute('SELECT count(*) FROM report_publications').fetchone()[0] == 0


def test_equivalent_imported_head_can_attach_after_validating_remote_bundle(report):
    from tools.cli.release.research_reporting.authoring.tree_schema import canonical_bytes
    original = report['session'].download('', maximum_bytes=8 * 1024 * 1024).content
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        objects = [(name, archive.read(name)) for name in archive.namelist() if name != 'manifest.json']
    manifest['head']['changed_node_ids'] = [] if manifest['head']['changed_node_ids'] else ['root']
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, content in [('manifest.json', canonical_bytes(manifest)), *objects]:
            archive.writestr(zipfile.ZipInfo(name), content)
    data = output.getvalue()
    assert data != original
    bundle = {**report['metadata']['authoring'], 'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data)}
    report['metadata']['authoring'] = bundle
    report['remote']['authoring'] = bundle
    report['session'].download = lambda _path, maximum_bytes: SimpleNamespace(content=data)
    assert local_catalog_import._attach_identical_shared_report(**report)['status'] == 'attached'


def test_denied_when_session_changes_before_receipt(report):
    report['session'].get = lambda _path: {**report['identity'], 'keycloak_subject': 'other'}
    with pytest.raises(PermissionError, match='authorization or version changed'):
        local_catalog_import._attach_identical_shared_report(**report)
    with report['store']._connect() as db:
        assert db.execute('SELECT count(*) FROM report_publications').fetchone()[0] == 0


def test_local_edit_during_authorization_recheck_cannot_create_stale_receipt(report, monkeypatch):
    version = report['metadata']['authoring']
    def change_then_confirm(*_args, **_kwargs):
        report['store'].add_report_component(profile_id='self', research_id=report['research_id'],
            report_id=report['report_id'], component_id='concurrent', kind='chapter', parent_id='',
            title='Concurrent edit', body='', generation=version['generation'], root_ref=version['root_ref'])
        return report['metadata']
    monkeypatch.setattr(local_catalog_import, '_remote', change_then_confirm)
    with pytest.raises(LocalReportSyncConflict, match='changed during attachment'):
        local_catalog_import._attach_identical_shared_report(**report)
    with report['store']._connect() as db:
        assert db.execute('SELECT count(*) FROM report_publications').fetchone()[0] == 0


def test_discovery_queue_attaches_existing_report_to_second_manager(report, monkeypatch):
    from tools.cli.release.research_reporting.local_server_reports import sync_server_reports
    endpoint = 'https://manager-b.test'
    manager_hash = hashlib.sha256(endpoint.encode()).hexdigest()
    store = report['store']
    with store._connect() as db:
        db.execute('''INSERT INTO server_report_pending
            (research_id,report_id,manager_hash,profile_id,source_kind) VALUES (?,?,?,?,?)''',
            (report['research_id'], report['report_id'], manager_hash, 'self', 'local'))
    monkeypatch.setattr(local_catalog_import, 'manager_session', lambda *_args: (endpoint, report['session']))
    monkeypatch.setattr(local_catalog_import, '_remote', lambda *_args, **kwargs:
                        report['metadata'] if kwargs.get('metadata_only') else report['remote'])
    results, more, errors = sync_server_reports(store, binding={}, manager={}, profile_id='self', limit=4,
                                                endpoint=endpoint, session=report['session'])
    assert [row['status'] for row in results] == ['attached']
    assert not more and errors == []
    with store._connect() as db:
        assert db.execute('SELECT count(*) FROM server_report_pending').fetchone()[0] == 0
        receipt = db.execute('SELECT * FROM report_publications WHERE manager_hash=?', (manager_hash,)).fetchone()
    assert receipt['revision'] == 'revision'

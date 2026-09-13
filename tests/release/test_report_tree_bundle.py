import hashlib
import io
import json
import zipfile

import pytest

from tools.cli.release.research_reporting.authoring.tree_bundle import export_report_bundle, import_report_bundle
from tools.cli.release.research_reporting.authoring.tree_model import initialize_tree, add_component, add_asset, load_snapshot


def _source(tmp_path):
    source = tmp_path / 'source'
    initialize_tree(package_root=source, branch_id='main', report_id='same-report', title='Report')
    file = source / 'branches/main/evidence.txt'
    file.write_text('complete evidence')
    add_component(package_root=source, branch_id='main', component_id='chapter', kind='chapter',
                  title='Chapter', parent_id=None, body='', content=None, display_kind='')
    add_component(package_root=source, branch_id='main', component_id='entry', kind='entry',
                  title='', parent_id='chapter', body='See [evidence](evidence.txt)', content=None, display_kind='')
    add_component(package_root=source, branch_id='main', component_id='math', kind='math',
                  title='', parent_id='chapter', body='', content={'latex': r'x^2 + y^2', 'fallback': 'sum of squares'}, display_kind='')
    image = source / 'assets/plot.png'
    image.parent.mkdir()
    image.write_bytes(b'image bytes')
    add_asset(package_root=source, branch_id='main', asset={
        'asset_ref': 'asset:plot', 'media_type': 'image/png', 'filename': 'plot.png',
        'caption': 'caption', 'alt_text': 'plot', 'local_ref': 'assets/plot.png',
        'content_hash': hashlib.sha256(image.read_bytes()).hexdigest(),
    })
    head = load_snapshot(package_root=source, branch_id='main')['head']
    return source, head


def test_bundle_preserves_editable_tree_resources_and_retry(tmp_path):
    source, head = _source(tmp_path)
    args = dict(package_root=source, branch_id='main', expected_generation=head['generation'], expected_root_ref=head['root_ref'])
    payload = export_report_bundle(**args)
    assert payload == export_report_bundle(**args)
    target = tmp_path / 'target'
    options = dict(payload=payload, expected_sha256=hashlib.sha256(payload).hexdigest(), package_root=target,
                   branch_id='review', report_id='same-report', source_generation=head['generation'], source_root_ref=head['root_ref'])
    assert import_report_bundle(**options)['inherited']
    snapshot = load_snapshot(package_root=target, branch_id='review')
    assert len(snapshot['components']) == 3
    assert snapshot['components'][2]['content'] == {'latex': r'x^2 + y^2', 'fallback': 'sum of squares'}
    assert '](resources/' in snapshot['components'][1]['body']
    assert list((target / 'branches/review/resources').glob('*/evidence.txt'))[0].read_text() == 'complete evidence'
    assert (target / snapshot['head']['assets'][0]['local_ref']).read_bytes() == b'image bytes'
    add_component(package_root=target, branch_id='review', component_id='new', kind='entry', title='',
                  parent_id='chapter', body='target only', content=None, display_kind='')
    assert not import_report_bundle(**options)['inherited']
    assert len(load_snapshot(package_root=target, branch_id='review')['components']) == 4
    assert load_snapshot(package_root=source, branch_id='main')['head'] == head


def test_bundle_rejects_tampered_resource_before_publishing_head(tmp_path):
    source, head = _source(tmp_path)
    payload = export_report_bundle(package_root=source, branch_id='main', expected_generation=head['generation'], expected_root_ref=head['root_ref'])
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as old, zipfile.ZipFile(output, 'w') as new:
        for name in old.namelist():
            new.writestr(name, b'corrupt' if name.startswith('objects/') else old.read(name))
    corrupt = output.getvalue()
    with pytest.raises(ValueError, match='checksum'):
        import_report_bundle(payload=corrupt, expected_sha256=hashlib.sha256(corrupt).hexdigest(),
                             package_root=tmp_path / 'target', branch_id='review', report_id='same-report',
                             source_generation=head['generation'], source_root_ref=head['root_ref'])
    assert not (tmp_path / 'target/branches/review/authoring/HEAD.json').exists()
    (source / 'branches/main/evidence.txt').unlink()
    with pytest.raises(ValueError, match='resource is unavailable'):
        export_report_bundle(package_root=source, branch_id='main', expected_generation=head['generation'], expected_root_ref=head['root_ref'])


def test_bundle_publication_is_detached_private_and_immutable(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tools.cli.release.research_reporting.public_research import client as module
    from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary
    from tools.cli.release.research_reporting.public_research.object_store import PublicResearchObjectStore
    source, head = _source(tmp_path)
    client = module.PublicResearchClient(tmp_path / 'client', manager_url='http://unused')
    monkeypatch.setattr(module, 'resolve_branch_report_scope', lambda **kwargs: SimpleNamespace(
        package_root=source, profile={'session_binding': {'principal_ref': 'alice'}}))
    monkeypatch.setattr(client, 'sync_pending', lambda **kwargs: [{'status': 'pending_sync'}])
    client.publish(profile_id='self', work_package_id='source', branch_id='main', visibility='private', include_authoring=True)
    operation = client.outbox.load(client.outbox.pending()[0]['operation_id'])
    projection = operation['projection']
    descriptor = projection['authoring_bundle']
    assert descriptor['root_ref'] == head['root_ref']
    assert ':revision:' in operation['manifest']['publication_key']
    assert all('content_base64' not in resource for resource in projection['local_resources'])
    library = PublicResearchLibrary(tmp_path / 'manager', authoring_authorizer=lambda record, viewer: viewer == 'bob')
    publication = library.sync({'report_id': 'same-report', 'owner_ref': 'alice', 'projection': projection})
    publication_id = publication['publication_id']
    assert library.index(publication_id, 'alice')['authoring_bundle'] == descriptor
    store = PublicResearchObjectStore(library)
    upload = next(item for item in operation['manifest']['objects'] if item['object_id'] == descriptor['resource_id'])
    path = client.outbox.root / operation['manifest']['operation_id'] / upload['path']
    staged = tmp_path / 'upload-staging'
    staged.write_bytes(path.read_bytes())
    store.store_from_file(publication_id, 'research_local_resource', descriptor['resource_id'], staged,
                          owner_ref='alice', expected_size=descriptor['size_bytes'], expected_sha256=descriptor['content_hash'])
    library.configure(owner_ref='alice', report_id='same-report', projection=None, visibility='public',
                      auto_sync=True, relay_local_files=False, authorized_users=[])
    assert library.local_resource(publication_id, descriptor['resource_id'], 'bob')[0] == path.read_bytes()
    with pytest.raises(PermissionError, match='active research membership'):
        store.resolve(publication_id, 'research_local_resource', descriptor['resource_id'], None)
    with pytest.raises(PermissionError):
        library.local_resource(publication_id, descriptor['resource_id'], 'outside-reader')
    with pytest.raises(ValueError, match='immutable'):
        library.sync({'report_id': 'same-report', 'owner_ref': 'alice',
                      'projection': {**projection, 'generation': head['generation'] + 1, 'projection_hash': 'different'}})
    with pytest.raises(ValueError, match='private'):
        client.publish(profile_id='self', work_package_id='source', branch_id='main', visibility='public', include_authoring=True)

import hashlib
import io
import json
import zipfile

import pytest

from tools.cli.release.research_reporting.authoring.tree_bundle import export_report_bundle, import_report_bundle
from tools.cli.release.research_reporting.authoring.tree_model import initialize_tree, add_component, add_asset, load_snapshot


def _source(tmp_path, *, external_ref=None):
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
        **({'external_ref': external_ref} if external_ref else {}),
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


@pytest.mark.parametrize("external_ref", [None, "factortester-artifact://jobs/job-1/plot.png"])
def test_imported_bundle_projection_matches_original_with_assets_and_local_links(tmp_path, external_ref):
    from tools.cli.release.research_reporting.local_projection_validation import bundle_matches_projection
    from tools.cli.release.research_reporting.public_research.object_uploads import detach_object_bytes, projection_hash
    from tools.cli.release.research_reporting.public_research.projection import build_upload_projection

    source, head = _source(tmp_path, external_ref=external_ref)
    assets = source / 'branches/main/assets'
    assets.mkdir()
    (assets / 'plot.png').write_bytes((source / 'assets/plot.png').read_bytes())
    projection, _ = detach_object_bytes(build_upload_projection(load_snapshot(package_root=source, branch_id='main')))
    assert projection['local_resources'][0]['available'] is True
    payload = export_report_bundle(package_root=source, branch_id='main',
        expected_generation=head['generation'], expected_root_ref=head['root_ref'])
    target = tmp_path / 'target'
    imported = import_report_bundle(payload=payload, expected_sha256=hashlib.sha256(payload).hexdigest(),
        package_root=target, branch_id='main', report_id='same-report',
        source_generation=head['generation'], source_root_ref=head['root_ref'])
    assert bundle_matches_projection(package_root=target, source_manifest=imported['source_manifest'],
        remote_projection=projection, expected_hash=projection['projection_hash'])
    altered = {**projection, 'title': 'Another title'}
    assert not bundle_matches_projection(package_root=target, source_manifest=imported['source_manifest'],
        remote_projection=altered, expected_hash=projection_hash(altered))


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
    client.publish(profile_id='self', report_workspace_id='source', branch_id='main', visibility='private', include_authoring=True)
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
        client.publish(profile_id='self', report_workspace_id='source', branch_id='main', visibility='public', include_authoring=True)


def test_bundle_preserves_full_job_table_beyond_preview(tmp_path, monkeypatch):
    from tools.cli.release.job_cache import cache_job_artifact, cached_job_artifact
    from tools.cli.release.research_reporting.job_artifact_tables import table_content
    source_cache, target_cache = tmp_path / 'source-cache', tmp_path / 'target-cache'
    monkeypatch.setenv('FACTORTESTER_JOB_CACHE_ROOT', str(source_cache))
    raw = ('value\n' + '\n'.join(str(i) for i in range(350))).encode()
    digest = hashlib.sha256(raw).hexdigest()
    cache_job_artifact(job_id='job-1', name='statistics', filename='statistics.csv', content_type='text/csv',
                       raw=raw, server_url='http://source-manager')
    source, _ = _source(tmp_path)
    add_component(package_root=source, branch_id='main', component_id='job-table', kind='table', title='',
        parent_id='chapter', body='[Full data](factortester-artifact://jobs/job-1/statistics)',
        content=table_content(raw, 'text/csv', source={'job_id': 'job-1', 'artifact_ref': 'job-artifact:job-1:statistics',
                             'filename': 'statistics.csv', 'content_hash': digest, 'content_type': 'text/csv'}), display_kind='')
    snapshot = load_snapshot(package_root=source, branch_id='main')
    assert len(snapshot['components'][-1]['content']['rows']) == 200
    payload = export_report_bundle(package_root=source, branch_id='main', expected_generation=snapshot['head']['generation'],
                                    expected_root_ref=snapshot['head']['root_ref'])
    monkeypatch.setenv('FACTORTESTER_JOB_CACHE_ROOT', str(target_cache))
    options = dict(payload=payload, expected_sha256=hashlib.sha256(payload).hexdigest(), package_root=tmp_path / 'target',
                   branch_id='review', report_id='same-report', source_generation=snapshot['head']['generation'],
                   source_root_ref=snapshot['head']['root_ref'])
    staged = import_report_bundle(**options, restore_artifacts=False)
    assert staged['inherited']
    # Staging and rejecting a report must not mutate the shared Job cache.
    assert cached_job_artifact(job_id='job-1', name='statistics') is None
    imported = load_snapshot(package_root=tmp_path / 'target', branch_id='review')
    assert '](resources/' in imported['components'][-1]['body']
    from tools.cli.release.research_reporting.public_research.projection import build_upload_projection
    projected = build_upload_projection(imported)
    assert projected['local_resources'][-1]['available'] is True
    from tools.cli.release.research_reporting.authoring.bundle_job_artifacts import restore_job_artifacts
    restore_job_artifacts(*staged['deferred_job_artifacts'])
    assert cached_job_artifact(job_id='job-1', name='statistics', expected_hash=digest)['raw'] == raw
    assert b'349' in cached_job_artifact(job_id='job-1', name='statistics')['raw']
    cache_job_artifact(job_id='job-1', name='statistics', filename='statistics.csv', content_type='text/csv',
                       raw=b'different version', server_url='http://target-manager')
    with pytest.raises(ValueError, match='conflicts'):
        import_report_bundle(**{**options, 'branch_id': 'conflicting'})
    assert not (tmp_path / 'target/branches/conflicting/authoring/HEAD.json').exists()


def test_branch_diff_detects_resource_changes_without_text_changes():
    from copy import deepcopy
    from tools.cli.release.research_reporting.authoring.tree_diff import diff_report_manifests
    base = {'head': {'report_id': 'r', 'generation': 1}, 'nodes': {}, 'assets': [],
            'links': [{'target': 'data.csv', 'sha256': 'a' * 64}],
            'job_artifacts': [{'job_id': 'job', 'name': 'table', 'sha256': 'b' * 64}]}
    other = deepcopy(base)
    other['links'][0]['sha256'] = 'c' * 64
    other['job_artifacts'][0]['sha256'] = 'd' * 64
    result = diff_report_manifests(base, other)
    assert result['component_change_count'] == 0
    assert result['resource_change_count'] == 2
    assert {item['resource_ref'] for item in result['resource_changes']} == {'data.csv', 'job:table'}


def test_job_artifact_restore_preserves_existing_files_and_cache_metadata(tmp_path, monkeypatch):
    from tools.cli.release.job_cache import cache_job_artifact, cached_job_artifact
    from tools.cli.release.research_reporting.authoring.bundle_job_artifacts import restore_job_artifacts

    monkeypatch.setenv('TRADERESEARCH_JOB_CACHE_ROOT', str(tmp_path / 'cache'))
    existing = b'existing artifact'
    cache_job_artifact(job_id='job-1', name='original', filename='same.csv',
        content_type='text/csv', raw=existing, server_url='https://original.example')
    digest = hashlib.sha256(existing).hexdigest()
    item = {'job_id': 'job-1', 'name': 'original', 'filename': 'same.csv',
            'content_type': 'text/csv', 'sha256': digest, 'size_bytes': len(existing)}
    manifest = tmp_path / 'cache' / 'job-1' / '.artifacts.json'
    before = manifest.read_bytes()
    restore_job_artifacts([item], {digest: existing})
    assert manifest.read_bytes() == before
    incoming = b'different artifact'
    incoming_digest = hashlib.sha256(incoming).hexdigest()
    collision = {**item, 'name': 'another', 'sha256': incoming_digest, 'size_bytes': len(incoming)}
    with pytest.raises(ValueError, match='filename conflicts'):
        restore_job_artifacts([collision], {incoming_digest: incoming})
    fresh = {**collision, 'name': 'fresh', 'filename': 'fresh.csv'}
    with pytest.raises(ValueError, match='filename conflicts'):
        restore_job_artifacts([fresh, collision], {incoming_digest: incoming})
    assert cached_job_artifact(job_id='job-1', name='fresh') is None
    assert cached_job_artifact(job_id='job-1', name='original')['raw'] == existing
    assert manifest.read_bytes() == before


def test_job_cache_writers_wait_for_report_restore_lock(tmp_path, monkeypatch):
    import threading
    from tools.cli.release.job_cache import (
        cache_job_artifact, cached_job_artifact, job_cache_write_lock,
    )

    monkeypatch.setenv('TRADERESEARCH_JOB_CACHE_ROOT', str(tmp_path / 'cache'))
    started = threading.Event()
    completed = threading.Event()
    errors = []

    def write():
        try:
            started.set()
            cache_job_artifact(job_id='job-1', name='evidence', filename='evidence.txt',
                               content_type='text/plain', raw=b'new', server_url='')
        except Exception as error:
            errors.append(error)
        finally:
            completed.set()

    with job_cache_write_lock('job-1'):
        worker = threading.Thread(target=write)
        worker.start()
        assert started.wait(2)
        assert not completed.wait(.1)
        assert cached_job_artifact(job_id='job-1', name='evidence') is None
    worker.join(timeout=2)
    assert completed.is_set() and not errors
    assert cached_job_artifact(job_id='job-1', name='evidence')['raw'] == b'new'


def test_job_cache_rejects_dot_directories(tmp_path, monkeypatch):
    from tools.cli.release.job_cache import job_cache_write_lock
    monkeypatch.setenv('TRADERESEARCH_JOB_CACHE_ROOT', str(tmp_path / 'cache'))
    for job_id in ('.', '..'):
        with pytest.raises(ValueError, match='job_id'):
            with job_cache_write_lock(job_id):
                pass

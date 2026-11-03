from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.cli.release.research_reporting.authoring.tree_bundle import bundle_from_snapshot, import_report_bundle
from tools.cli.release.research_reporting.authoring.tree_model import initialize_tree, add_component
from tools.cli.release.research_reporting.authoring.tree_paths import report_tree_paths
from tools.cli.release.research_reporting.authoring.tree_projection import load_snapshot
from tools.cli.release.research_reporting.authoring.tree_schema import canonical_bytes, digest
from tools.cli.release.research_reporting.migration_report_tree import upgrade_historical_report


def legacy_source(root):
    initialize_tree(package_root=root, branch_id='main', report_id='report-1', title='Original report')
    add_component(package_root=root, branch_id='main', component_id='chapter', kind='chapter', title='Chapter',
                  parent_id=None, body='', content=None, display_kind='')
    add_component(package_root=root, branch_id='main', component_id='entry', kind='entry', title='',
                  parent_id='chapter', body='original', content=None, display_kind='')
    paths = report_tree_paths(root, 'main')
    head = json.loads(paths['head'].read_text())
    def change(ref):
        value = json.loads((paths['root'] / ref).read_text())
        if value['node_id'] == 'entry':
            value['body'] = 'Before [原始结论](factortester://checkpoint/checkpoint%3Aold) after.'
            value['bindings'] = [{'binding_id': 'original-binding', 'kind': 'checkpoint',
                'target_ref': 'checkpoint:old', 'label': '原始结论',
                'data': {'private_source': '/Users/private/code.py', 'decision': 'original'}}]
        for child in value['children']:
            child['ref'] = change(child['ref'])
        sha = digest(value); new_ref = f'nodes/{sha[:2]}/{sha}.json'
        target = paths['root'] / new_ref; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(canonical_bytes(value))
        return new_ref
    head['root_ref'] = change(head['root_ref'])
    paths['head'].write_bytes(canonical_bytes(head))
    return paths, head


def test_inert_successor_preserves_source_identity_content_and_private_binding(tmp_path):
    from tools.cli.release.research_reporting.public_research.projection import build_upload_projection
    from tools.cli.release.research_reporting.references.authority import validate_declared_reference
    from tools.cli.release.research_reporting.authoring.declared_links import DeclaredReportReference
    root = tmp_path / 'source'; paths, head = legacy_source(root)
    before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    snapshot, receipt = upgrade_historical_report(paths, head=head)
    assert receipt['changed'] and receipt['converted_references'] == 1
    assert snapshot['head']['report_id'] == head['report_id'] and snapshot['head']['generation'] == head['generation'] + 1
    binding = snapshot['bindings'][0]
    assert binding['binding_id'] == 'original-binding' and binding['kind'] == 'historical_reference'
    assert binding['data']['historical_reference']['data']['decision'] == 'original'
    assert 'Before [原始结论]' in snapshot['components'][1]['body']
    projection = build_upload_projection(snapshot)
    assert projection['bindings'][0]['data'] == {'status': 'unavailable', 'original_kind': 'checkpoint'}
    assert '/Users/private' not in json.dumps(projection) and not projection['related_objects']
    payload = bundle_from_snapshot(snapshot, package_root=root, branch_id='main')
    target = tmp_path / 'cache'
    imported = import_report_bundle(payload=payload, expected_sha256=hashlib.sha256(payload).hexdigest(),
        package_root=target, branch_id='main', report_id='report-1', source_generation=snapshot['head']['generation'],
        source_root_ref=snapshot['head']['root_ref'])
    restored = load_snapshot(package_root=target, branch_id='main')
    assert restored['bindings'][0]['data'] == binding['data']
    from tools.cli.release.research_reporting.authoring.tree_bundle import validate_report_bundle
    manifest, files = validate_report_bundle(payload=payload, expected_sha256=hashlib.sha256(payload).hexdigest(),
        report_id='report-1', source_generation=snapshot['head']['generation'], source_root_ref=snapshot['head']['root_ref'])
    assert manifest['schema_version'] == 4
    archived = json.loads(files[manifest['migration_source']['sha256']])
    assert archived == receipt and archived['source_head'] == head
    # Subsequent edits/exports keep the original evidence even when the old
    # source workspace is no longer available to the cache reader.
    add_component(package_root=target, branch_id='main', component_id='later-entry', kind='entry', title='',
                  parent_id='chapter', body='New work after migration', content=None, display_kind='')
    restored = load_snapshot(package_root=target, branch_id='main')
    again = bundle_from_snapshot(restored, package_root=target, branch_id='main')
    reexported, resources = validate_report_bundle(payload=again, expected_sha256=hashlib.sha256(again).hexdigest(),
        report_id='report-1', source_generation=restored['head']['generation'], source_root_ref=restored['head']['root_ref'])
    assert resources[reexported['migration_source']['sha256']] == canonical_bytes(receipt)
    evidence_file = report_tree_paths(target, 'main')['root'] / 'migration-source.json'
    evidence_file.write_bytes(b'{}')
    with pytest.raises(ValueError, match='cached report migration source checksum differs'):
        bundle_from_snapshot(restored, package_root=target, branch_id='main')
    class NoNetwork:
        def __getattr__(self, _name): raise AssertionError('historical citations have no live authority')
    reference = DeclaredReportReference(kind=binding['kind'], target_ref=binding['target_ref'], label=binding['label'])
    result = validate_declared_reference(reference=reference, scope=SimpleNamespace(package_root=target, branch_id='main'), client=NoNetwork())
    assert result['data'] == binding['data']
    after = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    assert before == after
    repeated, mapping = upgrade_historical_report(paths, head=head)
    assert repeated['head'] == snapshot['head'] and mapping['node_ref_mapping'] == receipt['node_ref_mapping']


def test_corrupt_or_unclassified_source_fails_without_writing_it(tmp_path):
    paths, head = legacy_source(tmp_path / 'source')
    root_file = paths['root'] / head['root_ref']; raw = root_file.read_bytes()
    value = json.loads(raw); value['title'] = 'corrupt after addressing'
    root_file.write_bytes(canonical_bytes(value))
    with pytest.raises(ValueError, match='checksum differs'):
        upgrade_historical_report(paths, head=head)
    assert root_file.read_bytes() == canonical_bytes(value)


def test_recovery_keeps_observed_variant_and_does_not_overwrite_source(tmp_path):
    import base64
    paths, head = legacy_source(tmp_path / 'source')
    path = paths['root'] / head['root_ref']
    original = path.read_bytes(); value = json.loads(original)
    value['title'] = 'observed content with a wrong filename checksum'
    observed = canonical_bytes(value); path.write_bytes(observed)
    recovered = []
    def recover(candidate):
        recovered.append(candidate)
        return original, {'kind': 'git_blob', 'object_id': hashlib.sha1(b'blob ' + str(len(original)).encode() + b'\0' + original).hexdigest()}
    snapshot, receipt = upgrade_historical_report(paths, head=head, recover_node=recover)
    assert recovered == [path] and path.read_bytes() == observed
    assert receipt['source_variants'][0]['observed_sha256'] == hashlib.sha256(observed).hexdigest()
    assert base64.b64decode(receipt['source_variants'][0]['observed_content_base64']) == observed
    from tools.cli.release.research_reporting.authoring.bundle_migration_source import validate_migration_source
    validate_migration_source(receipt, report_id=head['report_id'])
    tampered = deepcopy(receipt); tampered['source_nodes'][head['root_ref']]['title'] = 'tampered'
    with pytest.raises(ValueError, match='checksum differs'):
        validate_migration_source(tampered, report_id=head['report_id'])


def test_rejected_submission_is_preserved_without_replay_and_skips_reserved_generation(tmp_path):
    paths, head = legacy_source(tmp_path / 'source')
    pending = {'phase': 'rejected', 'base_generation': head['generation'],
               'submission_sequence': head['generation'] + 1, 'published_generation': None,
               'sidecars': [], 'logical_identity': {'intent': 'original rejected edit'}}
    snapshot, receipt = upgrade_historical_report(paths, head=head, pending_submission=pending)
    assert snapshot['head']['generation'] == head['generation'] + 2
    assert receipt['rejected_submission'] == pending
    assert 'original rejected edit' not in json.dumps(snapshot['components'])
    from tools.cli.release.research_reporting.authoring.bundle_migration_source import validate_migration_source
    validate_migration_source(receipt, report_id=head['report_id'])
    receipt['rejected_submission']['phase'] = 'published'
    with pytest.raises(ValueError, match='requires reconciliation'):
        validate_migration_source(receipt, report_id=head['report_id'])

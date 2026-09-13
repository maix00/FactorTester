"""Two isolated Profile stores using real catalog, tree, publication and object stores.

Only network transport is replaced; this is not a deployed/browser acceptance.
"""
from pathlib import Path
import pytest
from types import SimpleNamespace

from server.manager.services.research_catalog import ResearchCatalog
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting import collaboration as workflow
from tools.cli.release.research_reporting.report_space import initialize_report_space
from tools.cli.release.research_reporting.authoring.tree_model import add_component, load_snapshot
from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary
from tools.cli.release.research_reporting.public_research.object_store import PublicResearchObjectStore


def test_two_profiles_fork_edit_publish_same_report(tmp_path, monkeypatch):
    catalog = ResearchCatalog(tmp_path / 'catalog.sqlite')
    research_id = catalog.create_research(owner_ref='alice', title='Shared')['research_id']
    owner_workspace = catalog.create_workspace(research_id, actor='alice', principal_ref='alice', profile_ref='self', title='Owner')
    report = catalog.register_report(research_id, actor='alice', report_id='same-report', title='Report', profile_ref='self', workspace_id=owner_workspace['workspace_id'])
    catalog.add_membership(research_id, actor='alice', principal_ref='bob', profile_ref='self', role='editor')
    library = PublicResearchLibrary(tmp_path / 'publications', storage_server_id='source-server',
        read_authorizer=catalog.can_read_publication, authoring_authorizer=catalog.can_read_authoring_publication)
    objects = PublicResearchObjectStore(library)
    stores = {}
    for user in ('alice', 'bob'):
        store = LocalProfileStore(tmp_path / user)
        profile = new_local_profile(profile_id='self', display_name=user, server_url='http://manager',
                                    workspace_root=tmp_path / user / 'workspace')
        profile['session_binding'] = {'principal_ref': user, 'session_ref': 'session-binding:test'}
        store.save(profile)
        stores[user] = store

    class Client:
        def __init__(self, actor):
            self.actor = actor
            self.session = SimpleNamespace(base_url='http://manager', request=self.request)
        def request(self, method, path, payload=None, **kwargs):
            assert path == '/api/research-publications/publish'
            assert payload['owner_ref'] == self.actor
            result = library.sync(payload)
            library.configure(owner_ref=self.actor, report_id=payload['report_id'], publication_key=payload['publication_key'],
                              projection=None, visibility='private', auto_sync=True, relay_local_files=False, authorized_users=[])
            return {**result, 'storage_server_id': 'source-server'}
        def report_branch_status(self, report_id):
            return {'branches': catalog.list_report_branches(report_id, viewer=self.actor)}
        def reserve_report_branch(self, report_id, payload):
            return {'branch': catalog.reserve_report_branch(report_id, actor=self.actor, **payload)}
        def publish_report_branch(self, report_id, branch_id, payload):
            record = library.publication_metadata(payload['publication_id'])
            return {'branch': catalog.publish_report_branch(report_id, branch_id, actor=self.actor, **payload,
                generation=record['generation'], revision=record['projection_hash'], storage_server_id=record['storage_server_id'])}
        def read_publication_branch(self, publication_id):
            return library.index(publication_id, self.actor)
        def create_research_workspace(self, research_id, payload):
            return catalog.create_workspace(research_id, actor=self.actor, **payload)

    def upload(self, *, publication_id, owner_ref, storage_server_id, upload):
        path = tmp_path / 'staging'
        path.write_bytes(upload.content)
        objects.store_from_file(publication_id, upload.object_kind, upload.object_id, path,
                                 owner_ref=owner_ref, expected_size=upload.size_bytes, expected_sha256=upload.content_hash)
    monkeypatch.setattr(workflow.PublicResearchClient, '_upload_object', upload)
    monkeypatch.setattr(workflow, 'download_bundle', lambda client, pid, desc:
                        library.local_resource(pid, desc['resource_id'], client.actor)[0])
    alice, bob = Client('alice'), Client('bob')
    initialized = initialize_report_space(stores['alice'], 'self', report)
    package_id = initialized['work_package_id']
    package = tmp_path / 'alice/workspace/research' / package_id
    add_component(package_root=package, branch_id='main', component_id='chapter', kind='chapter', title='Chapter',
                  parent_id=None, body='', content=None, display_kind='')
    published = workflow.publish_local_branch(alice, stores['alice'], profile_id='self', work_package_id=package_id, branch_id='main')
    original = published['branch']
    forked = workflow.fork_remote_branch(bob, stores['bob'], profile_id='self', report_id='same-report', source_branch_id='main', branch_id='bob-review')
    assert forked['branch']['report_id'] == original['report_id']
    assert forked['branch']['principal_ref'] == 'bob'
    assert forked['branch']['workspace_id'] != original['workspace_id']
    target = tmp_path / 'bob/workspace/research' / package_id
    add_component(package_root=target, branch_id='bob-review', component_id='bob-note', kind='entry', title='',
                  parent_id='chapter', body='Bob edits independently', content=None, display_kind='')
    updated = workflow.publish_local_branch(bob, stores['bob'], profile_id='self', work_package_id=package_id, branch_id='bob-review')
    assert updated['branch']['generation'] == forked['branch']['generation'] + 1
    assert updated['publication_id'] != forked['publication_id']
    assert len(load_snapshot(package_root=package, branch_id='main')['components']) == 1
    assert {b['branch_id'] for b in alice.report_branch_status('same-report')['branches']} == {'main', 'bob-review'}
    assert len(library.projection(updated['publication_id'], 'alice')['components']) == 2

    add_component(package_root=package, branch_id='main', component_id='alice-later', kind='entry', title='',
                  parent_id='chapter', body='Source advances after the fork', content=None, display_kind='')
    workflow.publish_local_branch(alice, stores['alice'], profile_id='self', work_package_id=package_id, branch_id='main')
    retried = workflow.fork_remote_branch(bob, stores['bob'], profile_id='self', report_id='same-report', source_branch_id='main', branch_id='bob-review')
    assert not retried['inherited']
    assert retried['source_revision'] == original['revision']
    assert len(load_snapshot(package_root=target, branch_id='bob-review')['components']) == 2
    # A failed first download must resume the exact reserved snapshot, including
    # an editor-owned publication that is no longer that editor's current head.
    real_download = workflow.download_bundle
    monkeypatch.setattr(workflow, 'download_bundle', lambda *a, **k: (_ for _ in ()).throw(ConnectionError('interrupted')))
    with pytest.raises(ConnectionError, match='interrupted'):
        workflow.fork_remote_branch(alice, stores['alice'], profile_id='self', report_id='same-report', source_branch_id='bob-review', branch_id='owner-review')
    add_component(package_root=target, branch_id='bob-review', component_id='bob-after-reservation', kind='entry', title='',
                  parent_id='chapter', body='Not part of the reserved source', content=None, display_kind='')
    workflow.publish_local_branch(bob, stores['bob'], profile_id='self', work_package_id=package_id, branch_id='bob-review')
    monkeypatch.setattr(workflow, 'download_bundle', real_download)
    imported = workflow.fork_remote_branch(alice, stores['alice'], profile_id='self', report_id='same-report', source_branch_id='bob-review', branch_id='owner-review')
    assert imported['source_revision'] == updated['branch']['revision']
    assert 'bob-after-reservation' not in {n['component_id'] for n in load_snapshot(package_root=package, branch_id='owner-review')['components']}

    from tools.cli.release.research_reporting.authoring.tree_copy import plan_subtree_copy, apply_subtree_copy
    from tools.cli.release.research_reporting.authoring.tree_paths import report_tree_paths
    source_snapshot = load_snapshot(package_root=package, branch_id='owner-review')
    target_snapshot = load_snapshot(package_root=package, branch_id='main')
    preview = plan_subtree_copy(source_snapshot, target_snapshot, component_ids=['bob-note'],
                                parent_id='chapter', copy_id='owner-selects-one-note')
    apply_subtree_copy(report_tree_paths(package, 'main'), preview, staged_assets=[])
    selected = load_snapshot(package_root=package, branch_id='main')
    assert [item['body'] for item in selected['components'] if item['kind'] == 'entry'] == [
        'Source advances after the fork', 'Bob edits independently']
    assert len(load_snapshot(package_root=target, branch_id='bob-review')['components']) == 3

    comparison = workflow.diff_remote_branches(alice, report_id='same-report', base_branch_id='main',
                                               other_branch_id='bob-review', include_content=True)
    assert {change['component_id'] for change in comparison['changes']} == {'chapter', 'alice-later', 'bob-note', 'bob-after-reservation'}
    assert 'root' not in {change['component_id'] for change in comparison['changes']}
    assert any(change['status'] == 'added' and change['after']['body'] == 'Bob edits independently'
               for change in comparison['changes'])

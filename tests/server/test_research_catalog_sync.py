from __future__ import annotations

import pytest

from server.manager.services.research_catalog import ResearchCatalog
from server.manager.storage.account_domain import AccountDomainSyncService
from server.manager.storage.account_domain.research_sync import backfill_researches
from tests.scripts.test_worktree_manager_account_domain_sync import MemoryControlStore


def replicas(tmp_path):
    control = MemoryControlStore()
    values = []
    for name in ('public', 'internal'):
        path = tmp_path / (name + '.sqlite')
        catalog = ResearchCatalog(path)
        sync = AccountDomainSyncService(sqlite_path=path, control_store=control, manager_id=name)
        catalog.set_synchronizer(sync)
        values.append((catalog, sync))
    return values, control


def test_research_relationships_and_revocations_converge_without_granting_public_access(tmp_path):
    ((author, outgoing), (mirror, incoming)), _ = replicas(tmp_path)
    item = author.create_research(owner_ref='alice', title='private research')
    rid = item['research_id']
    author.add_membership(rid, actor='alice', principal_ref='bob', profile_ref='bob-profile', role='viewer')
    author.register_report(rid, actor='alice', report_id='report:v1:one', profile_ref='self', title='report')
    assert outgoing.flush(principal='alice')['sent'] == 1
    assert incoming.pull(principal='bob')['applied'] == 1
    assert mirror.get_research_summary(rid, viewer='alice')['research_id'] == rid
    assert mirror.list_members(rid, viewer='bob')
    assert mirror.list_reports(rid, viewer='bob')[0]['report_id'] == 'report:v1:one'
    assert mirror.list_researches(viewer='stranger') == []
    assert mirror.list_reports_for_scope(viewer='stranger') == []
    assert backfill_researches(incoming, 'alice') == 0
    assert incoming.local.pending(principal='alice') == []
    author.remove_membership(rid, actor='alice', profile_ref='bob-profile')
    outgoing.flush(principal='alice'); incoming.pull(principal='bob')
    assert mirror.list_researches(viewer='bob') == []
    with pytest.raises(PermissionError):
        mirror.list_members(rid, viewer='bob')
    author.update_research(rid, actor='alice', title='renamed', status='archived')
    outgoing.flush(principal='alice'); incoming.pull(principal='alice')
    result = mirror.get_research_summary(rid, viewer='alice')
    assert result['title'] == 'renamed' and result['status'] == 'archived'


def test_research_outbox_failure_rolls_back_authored_change(tmp_path, monkeypatch):
    ((catalog, sync), _), _control = replicas(tmp_path)
    def reject(**kwargs):
        raise ValueError('too large')
    monkeypatch.setattr(sync.local, 'upsert_local', reject)
    with pytest.raises(ValueError, match='too large'):
        catalog.create_research(owner_ref='alice', title='not committed')
    assert catalog.list_researches(viewer='alice') == []


def test_redeemed_access_syncs_without_replicating_share_token(tmp_path):
    ((author, outgoing), (mirror, incoming)), _ = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='shared')['research_id']
    link = author.create_share_link(target_kind='research', research_id=rid,
                                    actor='alice', mode='one_time')
    outgoing.flush(principal='alice'); incoming.pull(principal='bob')
    assert mirror.list_researches(viewer='bob') == []
    author.redeem_share_link(link['token'], actor='bob')
    outgoing.flush(principal='alice'); incoming.pull(principal='bob')
    assert mirror.get_research_summary(rid, viewer='bob')['research_id'] == rid
    envelope = incoming.local.get_entity('alice', 'research_catalog', rid)
    assert link['token'] not in str(envelope)
    assert 'token_hash' not in str(envelope)


def test_replication_cannot_reassign_an_existing_research_owner(tmp_path):
    from server.manager.storage.account_domain.research_sync import materialize_research
    ((author, outgoing), (mirror, incoming)), _ = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='owned')['research_id']
    outgoing.flush(principal='alice'); incoming.pull(principal='alice')
    envelope = outgoing.local.get_entity('alice', 'research_catalog', rid)
    envelope['principal'] = 'mallory'
    envelope['payload']['research']['owner_ref'] = 'mallory'
    with pytest.raises(ValueError, match='another identity'):
        materialize_research(incoming.local.path, envelope)
    assert mirror.get_research_summary(rid, viewer='alice')['owner_ref'] == 'alice'


def test_incomplete_snapshot_cannot_remove_memberships(tmp_path):
    from server.manager.storage.account_domain.research_sync import materialize_research
    ((author, outgoing), (mirror, incoming)), _ = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='owned')['research_id']
    author.add_membership(rid, actor='alice', principal_ref='bob', profile_ref='bob')
    outgoing.flush(principal='alice'); incoming.pull(principal='alice')
    envelope = outgoing.local.get_entity('alice', 'research_catalog', rid)
    del envelope['payload']['members']
    with pytest.raises(ValueError, match='incomplete'):
        materialize_research(incoming.local.path, envelope)
    assert mirror.get_research_summary(rid, viewer='bob')['research_id'] == rid


def test_offline_and_conflicting_research_edits_preserve_local_work(tmp_path):
    ((author, outgoing), (mirror, incoming)), control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='initial')['research_id']
    outgoing.flush(principal='alice'); incoming.pull(principal='alice')
    outgoing.control_store = None
    author.update_research(rid, actor='alice', title='offline edit')
    assert outgoing.local.pending(principal='alice')
    mirror.update_research(rid, actor='alice', title='peer edit')
    incoming.flush(principal='alice')
    outgoing.control_store = control
    assert outgoing.flush(principal='alice')['conflicts'] == 1
    outgoing.pull(principal='alice')
    assert author.get_research_summary(rid, viewer='alice')['title'] == 'offline edit'
    assert mirror.get_research_summary(rid, viewer='alice')['title'] == 'peer edit'
    # Apply an explicit choice through the existing conflict resolver, then
    # rebuild only the changed projection even when the pull cursor is current.
    from server.manager.storage.account_domain.research_sync import materialize_pending_researches
    local = outgoing.local.get_entity('alice', 'research_catalog', rid)
    remote = control.rows[('alice', 'research_catalog', rid)]
    outgoing.local.resolve_conflict(
        principal='alice', entity_type='research_catalog', entity_id=rid,
        expected_payload=local['payload'], remote_revision=remote['revision'],
        payload=remote['payload'], manager_id='public',
    )
    outgoing.flush(principal='alice')
    assert materialize_pending_researches(outgoing) == 1
    assert author.get_research_summary(rid, viewer='alice')['title'] == 'peer edit'
    assert materialize_pending_researches(outgoing) == 0


def test_selected_remote_snapshot_removes_local_only_grants_and_workspace_collision(tmp_path):
    from server.manager.storage.account_domain.research_sync import materialize_pending_researches
    ((author, outgoing), (mirror, incoming)), control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='initial')['research_id']
    author.add_membership(rid, actor='alice', principal_ref='alice', profile_ref='analysis')
    outgoing.flush(principal='alice'); incoming.pull(principal='alice')
    author.add_membership(rid, actor='alice', principal_ref='bob', profile_ref='bob')
    local_workspace = author.create_workspace(rid, actor='alice', principal_ref='alice', profile_ref='analysis')
    remote_workspace = mirror.create_workspace(rid, actor='alice', principal_ref='alice', profile_ref='analysis')
    assert local_workspace['workspace_id'] != remote_workspace['workspace_id']
    incoming.flush(principal='alice')
    assert outgoing.flush(principal='alice')['conflicts'] == 1
    remote = control.rows[('alice', 'research_catalog', rid)]
    local = outgoing.local.get_entity('alice', 'research_catalog', rid)
    outgoing.local.resolve_conflict(
        principal='alice', entity_type='research_catalog', entity_id=rid,
        expected_payload=local['payload'], remote_revision=remote['revision'],
        payload=remote['payload'], manager_id='public',
    )
    outgoing.flush(principal='alice')
    assert materialize_pending_researches(outgoing) == 1
    assert author.list_researches(viewer='bob') == []
    assert author.create_workspace(rid, actor='alice', principal_ref='alice', profile_ref='analysis')['workspace_id'] == remote_workspace['workspace_id']


def test_same_named_profile_members_replicate_and_revoke_independently(tmp_path):
    ((author, outgoing), (mirror, incoming)), _ = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='Shared')['research_id']
    author.add_membership(rid, actor='alice', principal_ref='bob', profile_ref='self', role='editor')
    author.create_workspace(rid, actor='alice', principal_ref='bob', profile_ref='self')
    outgoing.flush(principal='alice'); incoming.pull(principal='bob')
    assert {(m['principal_ref'], m['profile_ref']) for m in mirror.list_members(rid, viewer='bob')} == {
        ('alice', 'self'), ('bob', 'self'),
    }
    assert len(mirror.list_workspaces(rid, viewer='bob')) == 2
    author.remove_membership(rid, actor='alice', principal_ref='bob', profile_ref='self')
    outgoing.flush(principal='alice'); incoming.pull(principal='bob')
    assert mirror.list_researches(viewer='bob') == []
    assert {(m['principal_ref'], m['profile_ref']) for m in mirror.list_members(rid, viewer='alice')} == {('alice', 'self')}


def test_shared_report_branches_sync_without_changing_report_owner(tmp_path):
    from copy import deepcopy
    from server.manager.storage.account_domain.research_sync import materialize_research
    ((author, outgoing), (mirror, incoming)), _ = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='shared')['research_id']
    author.register_report(rid, actor='alice', report_id='report', profile_ref='self')
    author.add_membership(rid, actor='alice', principal_ref='bob', profile_ref='self', role='editor')
    author.create_workspace(rid, actor='alice', principal_ref='bob', profile_ref='self', title='bob')
    author.reserve_report_branch('report', actor='bob', profile_ref='self', branch_id='bob-branch')
    author.publish_report_branch('report', 'bob-branch', actor='bob', profile_ref='self',
                                 expected_generation=0, expected_revision='', generation=1,
                                 revision='a' * 64, publication_id='p' * 24, storage_server_id='client-cache')
    outgoing.flush(principal='alice')
    incoming.pull(principal='bob')
    branches = mirror.list_report_branches('report', viewer='bob')
    assert len(branches) == 1 and branches[0]['principal_ref'] == 'bob'
    assert mirror.list_reports(rid, viewer='bob')[0]['owner_ref'] == 'alice'
    envelope = deepcopy(outgoing.local.get_entity('alice', 'research_catalog', rid))
    envelope['payload']['schema_version'] = 1
    envelope['payload'].pop('branches')
    with pytest.raises(ValueError, match='legacy research snapshot'):
        materialize_research(incoming.local.path, envelope)
    assert mirror.list_report_branches('report', viewer='bob') == branches

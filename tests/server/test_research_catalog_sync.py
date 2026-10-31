from __future__ import annotations

import pytest

from server.manager.services.research_catalog import ResearchCatalog
from server.manager.storage.account_domain import AccountDomainSyncService
from server.manager.storage.account_domain.research_sync import backfill_researches
from tests.scripts.test_worktree_manager_account_domain_sync import MemoryControlStore


def replicas(tmp_path, *, exercise_legacy=True):
    control = MemoryControlStore()
    values = []
    for name in ('public', 'internal'):
        path = tmp_path / (name + '.sqlite')
        catalog = ResearchCatalog(path)
        sync = AccountDomainSyncService(sqlite_path=path, control_store=control, manager_id=name)
        catalog.set_synchronizer(sync)
        if exercise_legacy:
            # Isolated migration compatibility tests only; production does not
            # enable the legacy graph publisher.
            sync.research_legacy_sharing = True
        values.append((catalog, sync))
    return values, control


def test_private_research_and_owner_only_workspaces_never_enter_automatic_outbox(tmp_path):
    ((author, outgoing), (mirror, incoming)), control = replicas(tmp_path, exercise_legacy=False)
    rid = author.create_research(owner_ref='alice', title='local', profile_ref='work')['research_id']
    author.register_report(rid, actor='alice', report_id='private-report', profile_ref='self')
    author.update_research(rid, actor='alice', title='local edit')
    assert outgoing.local.pending(principal='alice') == []
    assert backfill_researches(outgoing, 'alice') == 0
    assert outgoing.flush(principal='alice')['sent'] == 0
    assert incoming.pull(principal='alice')['applied'] == 0
    assert mirror.list_researches(viewer='alice') == [] and control.rows == {}
    assert author.get_research_summary(rid, viewer='alice')['title'] == 'local edit'


def test_shared_research_graph_is_not_automatically_published_without_destination_authorization(tmp_path):
    ((author, outgoing), (_mirror, _incoming)), control = replicas(tmp_path, exercise_legacy=False)
    rid = author.create_research(owner_ref='alice', title='shared', visibility='public')['research_id']
    author.register_report(rid, actor='alice', report_id='selected')
    assert outgoing.local.pending(principal='alice') == []
    assert backfill_researches(outgoing, 'alice') == 0
    _queue_old_private_projection(outgoing, rid)
    assert outgoing.flush(principal='alice')['blocked'] == 1
    assert control.rows == {}


def test_large_private_research_does_not_hit_shared_envelope_limit(tmp_path):
    from tools.data.sqlite.db import connect_sqlite
    ((author, outgoing), (_mirror, _incoming)), _control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='private')['research_id']
    with connect_sqlite(outgoing.local.path) as db:
        db.executemany('INSERT INTO research_catalog_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', [
            (f'report-{i}', rid, 'alice', 'title', 'self', '', 'client', '', 'private', '[]', 'active', '', 0, 0)
            for i in range(2000)
        ])
    assert author.update_research(rid, actor='alice', title='private edit')['title'] == 'private edit'
    assert outgoing.local.pending(principal='alice') == []


def test_old_accidentally_replicated_private_projection_is_preserved_without_further_sync(tmp_path):
    from server.manager.storage.account_domain.research_sync import snapshot
    from tools.data.sqlite.db import connect_sqlite
    ((author, outgoing), (_mirror, _incoming)), control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='old private')['research_id']
    with connect_sqlite(outgoing.local.path, readonly=True) as conn:
        old = snapshot(conn, rid)
    outgoing.local.upsert_local(principal='alice', entity_type='research_catalog', entity_id=rid,
        payload={'schema_version': 2, 'visibility': 'public', 'replication_scope': 'trusted_managers',
                 'storage_server_id': 'public', **old}, manager_id='public')
    # Simulate a private projection already pushed by the old implementation.
    old_item = outgoing.local.pending(principal='alice')[0]
    receipt = control.push_account_domain_entity(principal=old_item['principal'], entity_type=old_item['entity_type'],
        entity_id=old_item['entity_id'], payload=old_item['payload'], deleted=False,
        base_revision=old_item['base_revision'], origin_manager_id=outgoing.manager_id,
        operation_id=old_item['operation_id'])
    outgoing.local.acknowledge(old_item['operation_id'], revision=receipt['revision'], sent_item=old_item)
    author.update_research(rid, actor='alice', title='new private')
    assert outgoing.local.pending(principal='alice') == []
    assert control.rows[('alice', 'research_catalog', rid)]['payload']['research']['title'] == 'old private'
    assert not control.rows[('alice', 'research_catalog', rid)]['deleted']
    assert author.get_research_summary(rid, viewer='alice')['title'] == 'new private'


def _queue_old_private_projection(sync, research_id, *, deleted=False):
    from server.manager.storage.account_domain.research_sync import snapshot
    from tools.data.sqlite.db import connect_sqlite
    with connect_sqlite(sync.local.path, readonly=True) as conn:
        value = snapshot(conn, research_id)
    return sync.local.upsert_local(
        principal='alice', entity_type='research_catalog', entity_id=research_id,
        payload={'schema_version': 2, 'visibility': 'public', 'replication_scope': 'trusted_managers',
                 'storage_server_id': sync.manager_id, **value},
        manager_id=sync.manager_id, deleted=deleted,
    )


@pytest.mark.parametrize('deleted', [False, True])
def test_old_private_outbox_is_retained_for_review_and_cannot_starve_other_kinds(tmp_path, deleted):
    ((author, outgoing), _), control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='legacy private')['research_id']
    operation = _queue_old_private_projection(outgoing, rid, deleted=deleted)
    before = outgoing.local.pending(principal='alice')[0]
    outgoing.upsert('alice', 'product_group', 'unrelated', {'id': 'unrelated'}, flush=False)

    result = outgoing.flush(principal='alice', limit=1)

    assert result['sent'] == 1 and result['blocked'] == 1
    assert ('alice', 'product_group', 'unrelated') in control.rows
    assert ('alice', 'research_catalog', rid) not in control.rows
    assert outgoing.local.pending(principal='alice') == []
    retained = outgoing.local.pending(principal='alice', include_blocked=True)
    assert len(retained) == 1 and retained[0]['operation_id'] == operation
    assert retained[0]['payload'] == before['payload'] and retained[0]['deleted'] == deleted
    assert retained[0]['last_error'] == 'research_sync_needs_review'


def test_explicit_research_link_replaces_a_blocked_private_snapshot(tmp_path):
    ((author, outgoing), _), control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='private')['research_id']
    operation = _queue_old_private_projection(outgoing, rid)
    assert outgoing.flush(principal='alice')['blocked'] == 1
    author.create_share_link(target_kind='research', research_id=rid, actor='alice')
    pending = outgoing.local.pending(principal='alice')
    assert len(pending) == 1 and pending[0]['operation_id'] != operation
    assert outgoing.flush(principal='alice')['sent'] == 1
    assert ('alice', 'research_catalog', rid) in control.rows


def test_keycloak_mode_never_uploads_queued_legacy_shared_snapshot(tmp_path):
    ((author, outgoing), _), control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='legacy share',
                                 visibility='authorized', authorized_users=['bob'])['research_id']
    assert outgoing.local.pending(principal='alice')
    outgoing.research_legacy_sharing = False
    assert outgoing.flush(principal='alice')['blocked'] == 1
    assert control.rows == {}
    assert outgoing.local.pending(principal='alice', include_blocked=True)[0]['entity_id'] == rid


def test_expired_link_does_not_release_a_queued_private_snapshot(tmp_path):
    from tools.data.sqlite.db import connect_sqlite
    ((author, outgoing), _), control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='private')['research_id']
    author.create_share_link(target_kind='research', research_id=rid, actor='alice')
    with connect_sqlite(outgoing.local.path) as conn:
        conn.execute('UPDATE research_catalog_share_links SET expires_at=1 WHERE research_id=?', (rid,))
    assert outgoing.flush(principal='alice')['blocked'] == 1
    assert control.rows == {}


@pytest.mark.parametrize('change', ['revoked', 'private_edit'])
def test_stale_previously_shared_queue_entry_does_not_override_current_state(tmp_path, change):
    from tools.data.sqlite.db import connect_sqlite
    ((author, outgoing), _), control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='shared', visibility='public')['research_id']
    # Models an old queue entry after external recovery or an interrupted old
    # writer: it was shared when queued, but no longer matches live data.
    with connect_sqlite(outgoing.local.path) as conn:
        if change == 'revoked':
            conn.execute("UPDATE research_catalog_researches SET visibility='private' WHERE research_id=?", (rid,))
        else:
            conn.execute("UPDATE research_catalog_researches SET title='new local edit' WHERE research_id=?", (rid,))
    assert outgoing.flush(principal='alice')['blocked'] == 1
    assert control.rows == {}


def test_revoke_serializes_with_in_flight_shared_snapshot(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    ((author, outgoing), (mirror, incoming)), control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='shared')['research_id']
    author.add_membership(rid, actor='alice', principal_ref='bob', profile_ref='bob-profile', role='viewer')
    entered, release = Event(), Event()
    original_push = control.push_account_domain_entity

    def blocked_push(**item):
        entered.set()
        assert release.wait(5)
        return original_push(**item)

    control.push_account_domain_entity = blocked_push
    with ThreadPoolExecutor(max_workers=2) as pool:
        sending = pool.submit(outgoing.flush, principal='alice')
        try:
            assert entered.wait(5)
            removing = pool.submit(author.remove_membership, rid, actor='alice', profile_ref='bob-profile')
            assert not removing.done()
        finally:
            release.set()
        assert sending.result(timeout=5)['sent'] == 1
        removing.result(timeout=5)

    control.push_account_domain_entity = original_push
    assert outgoing.flush(principal='alice')['sent'] == 1
    incoming.pull(principal='bob')
    assert mirror.list_researches(viewer='bob') == []


def test_single_report_share_never_queues_the_whole_research_graph(tmp_path):
    ((author, outgoing), (_mirror, _incoming)), _control = replicas(tmp_path)
    report_research = author.create_research(owner_ref='alice', title='report')['research_id']
    author.register_report(report_research, actor='alice', report_id='shared-report',
                           visibility='authorized', authorized_users=['bob'])
    author.register_report(report_research, actor='alice', report_id='private-report', title='private sentinel')
    author.create_share_link(target_kind='report', research_id=report_research,
                             report_id='shared-report', actor='alice')
    assert outgoing.local.pending(principal='alice') == []
    # An old pending report-only snapshot is retained for review, not sent.
    _queue_old_private_projection(outgoing, report_research)
    assert outgoing.flush(principal='alice')['blocked'] == 1
    link_research = author.create_research(owner_ref='alice', title='link')['research_id']
    author.create_share_link(target_kind='research', research_id=link_research, actor='alice')
    assert {row['entity_id'] for row in outgoing.local.pending(principal='alice')} == {link_research}
    assert backfill_researches(outgoing, 'alice') == 0
    outgoing.research_legacy_sharing = False
    strict_research = author.create_research(owner_ref='alice', title='stale legacy ACL',
                                             visibility='authorized', authorized_users=['bob'])['research_id']
    assert not any(row['entity_id'] == strict_research for row in outgoing.local.pending(principal='alice'))
    assert backfill_researches(outgoing, 'alice') == 0


def test_research_withdrawal_never_publishes_a_new_private_report(tmp_path):
    ((author, outgoing), (_mirror, _incoming)), control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='shared', visibility='public')['research_id']
    author.register_report(rid, actor='alice', report_id='previously-shared')
    assert outgoing.flush(principal='alice')['sent'] == 1
    author.update_research(rid, actor='alice', visibility='private')
    author.register_report(rid, actor='alice', report_id='new-private', title='new private sentinel')
    assert outgoing.flush(principal='alice')['sent'] == 1
    remote = control.rows[('alice', 'research_catalog', rid)]['payload']
    assert {item['report_id'] for item in remote['reports']} == {'previously-shared'}
    assert 'new private sentinel' not in str(remote)
    assert remote['research']['visibility'] == 'private'


def test_archive_sends_one_final_shared_snapshot_even_with_a_live_link(tmp_path):
    ((author, outgoing), (mirror, incoming)), _control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='shared', visibility='public')['research_id']
    author.create_share_link(target_kind='research', research_id=rid, actor='alice')
    outgoing.flush(principal='alice'); incoming.pull(principal='alice')
    author.update_research(rid, actor='alice', status='archived')
    assert outgoing.flush(principal='alice')['sent'] == 1
    incoming.pull(principal='alice')
    assert mirror.get_research_summary(rid, viewer='alice')['status'] == 'archived'
    author.update_research(rid, actor='alice', title='private archived edit')
    assert outgoing.local.pending(principal='alice') == []


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
    # After the revocation snapshot, subsequent private edits remain local.
    assert result['title'] == 'private research' and result['status'] == 'active'
    assert outgoing.local.pending(principal='alice') == []


def test_research_outbox_failure_rolls_back_authored_change(tmp_path, monkeypatch):
    ((catalog, sync), _), _control = replicas(tmp_path)
    def reject(**kwargs):
        raise ValueError('too large')
    monkeypatch.setattr(sync.local, 'upsert_local', reject)
    with pytest.raises(ValueError, match='too large'):
        catalog.create_research(owner_ref='alice', title='not committed',
                                visibility='authorized', authorized_users=['bob'])
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
    rid = author.create_research(owner_ref='alice', title='owned',
                                 visibility='authorized', authorized_users=['bob'])['research_id']
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
    rid = author.create_research(owner_ref='alice', title='initial',
                                 visibility='authorized', authorized_users=['bob'])['research_id']
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
    rid = author.create_research(owner_ref='alice', title='initial',
                                 visibility='authorized', authorized_users=['charlie'])['research_id']
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


def test_resolved_snapshot_is_not_sent_after_a_newer_local_change(tmp_path):
    from tools.data.sqlite.db import connect_sqlite
    ((author, outgoing), (mirror, incoming)), control = replicas(tmp_path)
    rid = author.create_research(owner_ref='alice', title='initial',
                                 visibility='authorized', authorized_users=['bob'])['research_id']
    outgoing.flush(principal='alice'); incoming.pull(principal='alice')
    author.update_research(rid, actor='alice', title='local edit')
    mirror.update_research(rid, actor='alice', title='peer edit')
    incoming.flush(principal='alice')
    assert outgoing.flush(principal='alice')['conflicts'] == 1
    remote = control.rows[('alice', 'research_catalog', rid)]
    local = outgoing.local.get_entity('alice', 'research_catalog', rid)
    outgoing.local.resolve_conflict(
        principal='alice', entity_type='research_catalog', entity_id=rid,
        expected_payload=local['payload'], remote_revision=remote['revision'],
        payload=remote['payload'], manager_id='public',
    )
    with connect_sqlite(outgoing.local.path) as conn:
        conn.execute("UPDATE research_catalog_researches SET title='newer local edit' WHERE research_id=?", (rid,))
    assert outgoing.flush(principal='alice')['blocked'] == 1
    assert control.rows[('alice', 'research_catalog', rid)]['payload']['research']['title'] == 'peer edit'
    assert author.get_research_summary(rid, viewer='alice')['title'] == 'newer local edit'


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

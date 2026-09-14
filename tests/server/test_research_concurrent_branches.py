import copy
import pytest
from tests.server.test_research_catalog_sync import replicas


def setup_pair(tmp_path, role="editor"):
    pair, control = replicas(tmp_path)
    (a, sa), (b, sb) = pair
    original_push = control.push_account_domain_entity
    def push(**kw):
        receipt = original_push(**kw)
        if receipt['status'] == 'conflict':
            row = control.rows[(kw['principal'], kw['entity_type'], kw['entity_id'])]
            receipt.update(payload=copy.deepcopy(row['payload']), deleted=row['deleted'])
        return receipt
    control.push_account_domain_entity = push
    rid = a.create_research(owner_ref='alice', title='shared')['research_id']
    a.register_report(rid, actor='alice', report_id='report', title='report', profile_ref='self')
    for profile in ('left', 'right'):
        a.add_membership(rid, actor='alice', principal_ref='alice', profile_ref=profile, role=role)
    sa.flush(principal='alice'); sb.pull(principal='alice')
    return pair, rid


@pytest.mark.parametrize('role', ['editor', 'contributor'])
@pytest.mark.parametrize('pull_first', [False, True])
def test_independent_workspace_and_branch_writes_converge(tmp_path, pull_first, role):
    ((a, sa), (b, sb)), rid = setup_pair(tmp_path, role)
    # Valid hex revisions.
    def write(catalog, profile, marker):
        catalog.create_workspace(rid, actor='alice', principal_ref='alice', profile_ref=profile)
        catalog.reserve_report_branch('report', actor='alice', profile_ref=profile, branch_id=profile)
        catalog.publish_report_branch('report', profile, actor='alice', profile_ref=profile,
            expected_generation=0, expected_revision='', generation=1, revision=marker*64,
            publication_id=marker*24, storage_server_id=profile)
    write(a, 'left', 'a'); write(b, 'right', 'b')
    sa.flush(principal='alice')
    if pull_first:
        assert sb.pull(principal='alice')['conflicts'] == 0
    else:
        assert sb.flush(principal='alice')['conflicts'] == 0
    assert {x['branch_id'] for x in b.list_report_branches('report', viewer='alice')} == {'left', 'right'}
    sb.flush(principal='alice'); sa.pull(principal='alice')
    assert a.list_report_branches('report', viewer='alice') == b.list_report_branches('report', viewer='alice')
    assert sa.local.conflicts(principal='alice') == sb.local.conflicts(principal='alice') == []
    assert sa.local.pending() == sb.local.pending() == []


def test_remote_revocation_blocks_concurrent_new_branch(tmp_path):
    ((a, sa), (b, sb)), rid = setup_pair(tmp_path)
    b.create_workspace(rid, actor='alice', principal_ref='alice', profile_ref='left')
    b.reserve_report_branch('report', actor='alice', profile_ref='left', branch_id='left')
    a.remove_membership(rid, actor='alice', principal_ref='alice', profile_ref='left')
    sa.flush(principal='alice')
    assert sb.flush(principal='alice')['conflicts'] == 1
    assert sb.local.conflicts(principal='alice')
    assert b.list_report_branches('report', viewer='alice')[0]['branch_id'] == 'left'


def test_delayed_projection_cannot_overwrite_new_local_edit(tmp_path):
    from server.manager.storage.account_domain.research_sync import materialize_research
    ((a, sa), (b, sb)), rid = setup_pair(tmp_path)
    stale = sb.local.get_entity('alice', 'research_catalog', rid)
    b.update_research(rid, actor='alice', title='new local title')
    materialize_research(sb.local.path, stale)
    assert b.get_research_summary(rid, viewer='alice')['title'] == 'new local title'
    assert sb.local.pending(principal='alice')


def test_overlapping_research_edits_are_not_auto_resolved(tmp_path):
    ((a, sa), (b, sb)), rid = setup_pair(tmp_path)
    a.update_research(rid, actor='alice', title='left title')
    b.update_research(rid, actor='alice', title='right title')
    sa.flush(principal='alice')
    assert sb.flush(principal='alice')['conflicts'] == 1
    assert b.get_research_summary(rid, viewer='alice')['title'] == 'right title'


def test_idempotent_member_timestamp_touches_do_not_conflict(tmp_path):
    ((a, sa), (b, sb)), rid = setup_pair(tmp_path)
    for catalog in (a, b):
        catalog.add_membership(rid, actor='alice', principal_ref='alice', profile_ref='left', role='editor')
    sa.flush(principal='alice')
    assert sb.flush(principal='alice')['conflicts'] == 0
    sb.flush(principal='alice'); sa.pull(principal='alice')
    assert sa.local.conflicts(principal='alice') == sb.local.conflicts(principal='alice') == []

"""Legacy Research graphs cannot be published, merged or materialized."""
import json
import sqlite3
import pytest
from server.manager.storage.account_domain import AccountDomainSyncService
from tests.scripts.test_worktree_manager_account_domain_sync import MemoryControlStore


def service(tmp_path, control=None):
    return AccountDomainSyncService(sqlite_path=tmp_path / 'metadata.sqlite', control_store=control, manager_id='local')


def envelope():
    return {'principal':'alice','entity_type':'research_catalog','entity_id':'r',
            'payload':{'research':{'research_id':'r','visibility':'public'}},
            'revision':1,'deleted':False,'origin_manager_id':'peer'}


def test_new_graph_writes_and_conflict_resolution_fail_before_storage(tmp_path):
    sync = service(tmp_path)
    with pytest.raises(ValueError, match='retired'):
        sync.upsert('alice', 'research_catalog', 'r', envelope()['payload'])
    with pytest.raises(ValueError, match='migration review'):
        sync.local.resolve_conflict(principal='alice',entity_type='research_catalog',entity_id='r',
            expected_payload={},remote_revision=1,payload={},manager_id='local')
    assert sync.local.get_entity('alice','research_catalog','r') is None


@pytest.mark.parametrize('deleted', [False, True])
def test_legacy_inbound_cannot_overwrite_existing_projection(tmp_path, deleted):
    sync = service(tmp_path)
    row = envelope(); row['deleted'] = deleted
    assert sync.local.apply_remote(row) == 'retired'
    assert sync.local.apply_remote(row) == 'retired'
    conflicts = sync.local.conflicts(principal='alice')
    assert len(conflicts) == 1
    import hashlib
    digest = hashlib.sha256(json.dumps(row['payload'],ensure_ascii=False,sort_keys=True,separators=(',', ':')).encode()).hexdigest()
    assert json.loads(conflicts[0]['remote_payload_json']) == {'retired_entity_type':'research_catalog','payload_sha256':digest}
    assert 'visibility' not in conflicts[0]['remote_payload_json']
    assert bool(conflicts[0]['remote_deleted']) is deleted
    assert sync.local.get_entity('alice','research_catalog','r') is None
    with sqlite3.connect(sync.local.path) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='research_catalog_researches'").fetchone()[0] == 0


def test_legacy_outbox_is_preserved_and_blocked_without_transmission(tmp_path):
    control = MemoryControlStore()
    sync = service(tmp_path, control)
    payload = json.dumps(envelope()['payload'])
    with sqlite3.connect(sync.local.path) as db:
        db.execute('''INSERT INTO account_domain_outbox
            (operation_id,principal,entity_type,entity_id,payload_json,deleted,base_revision,created_at)
            VALUES ('old','alice','research_catalog','r',?,0,0,1)''', (payload,))
    sync.research_legacy_sharing = True  # Even a stale flag cannot reactivate it.
    result = sync.flush(principal='alice')
    assert result['sent'] == 0 and result['blocked'] == 1 and control.rows == {}
    rows = sync.local.pending(principal='alice',include_blocked=True)
    assert len(rows) == 1 and rows[0]['payload'] == envelope()['payload']
    assert rows[0]['deleted'] is False and rows[0]['last_error'] == 'research_sync_needs_review'


def test_pull_reports_retired_records_and_advances_without_materializing(tmp_path):
    class Control:
        def pull_account_domain_entities(self, **kwargs):
            return {'entities':[envelope()], 'next_revision':1}
    sync = service(tmp_path, Control())
    result = sync.pull(principal='alice')
    assert result['retired'] == 1 and result['applied'] == 0
    assert result['next_revision'] == 1
    assert sync.local.get_entity('alice','research_catalog','r') is None


def test_historical_projection_stays_stored_but_not_in_live_directory(tmp_path):
    sync = service(tmp_path)
    payload = json.dumps(envelope()['payload'])
    with sqlite3.connect(sync.local.path) as db:
        db.execute("INSERT INTO account_domain_entities (principal,entity_type,entity_id,payload_json,deleted,remote_revision,base_revision,origin_manager_id,updated_at) VALUES ('alice','research_catalog','r',?,0,1,1,'peer',1)", (payload,))
    assert sync.entities('alice',sync=False) == []
    assert sync.entities('alice',entity_type='research_catalog',sync=False) == []
    assert sync.local.get_entity('alice','research_catalog','r')['payload'] == envelope()['payload']


def test_new_store_does_not_install_retired_graph_merge_tables(tmp_path):
    sync = service(tmp_path)
    with sqlite3.connect(sync.local.path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
    assert "account_domain_research_bases" not in tables
    assert "account_domain_research_sync_intents" not in tables
    assert "account_domain_research_sync_intent_cleanup" not in tables

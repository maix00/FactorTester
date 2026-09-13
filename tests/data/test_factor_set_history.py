import pytest
import settings
from tools.data.sqlite.account_manager.factor_set import (
    save_factor_set, delete_factor_set, list_factor_sets, get_factor_set, factor_set_history)
from tools.factors.formula_identity import freeze_factor_identity
from tools.factors.factor_set_identity import freeze_factor_set_identity


def member(alias):
    return freeze_factor_identity(owner_ref='public',family_alias=alias,factor_alias=alias,
        family_formula_fingerprint='a'*64,self_formula_fingerprint='b'*64,params={})


def version(*aliases):
    return freeze_factor_set_identity(owner_ref='principal:alice',set_id='test',alias='集合',
        members=[member(a) for a in aliases])


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'CACHE_DB_PATH', tmp_path/'test.sqlite')


def test_history_survives_removal_readdition_and_unregister(database):
    first, second = version('CA','OA'),version('OA')
    save_factor_set('alice',first)
    save_factor_set('alice',second)
    assert [v['ref'] for v in list_factor_sets('alice')] == [second['ref']]
    assert get_factor_set('alice',first['ref'])['identity'] == first['identity']
    save_factor_set('alice',first)
    events = factor_set_history('alice', first['ref'])['items']
    assert len(events) == 4
    assert sum(e['action']=='added' and e['member']['ref']==member('CA')['ref'] for e in events)==2
    assert delete_factor_set('alice',first['ref'])
    assert list_factor_sets('alice') == []
    assert get_factor_set('alice',first['ref'])['identity'] == first['identity']
    assert len(factor_set_history('alice',first['ref'])['items']) == 6
    assert not delete_factor_set('alice',first['ref'])
    assert factor_set_history('bob',first['ref']) is None


def test_pagination_and_identical_save_do_not_add_events(database):
    value=version('A','B','C')
    save_factor_set('alice',value)
    save_factor_set('alice',value)
    page=factor_set_history('alice',value['ref'],limit=2)
    assert page['has_more'] and page['next_offset']==2
    rest=factor_set_history('alice',value['ref'],offset=2,limit=2)
    assert len(rest['items'])==1 and not rest['has_more']
    assert not {e['event_id'] for e in page['items']} & {e['event_id'] for e in rest['items']}


def test_event_failure_rolls_back_current_and_previous_versions(database,monkeypatch):
    first,second=version('A','B'),version('B')
    save_factor_set('alice',first)
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    original=LocalAccountDomainStore.upsert_local
    def fail(self,**kwargs):
        if kwargs['entity_type']=='factor_set_event':
            raise RuntimeError('outbox failure')
        return original(self,**kwargs)
    monkeypatch.setattr(LocalAccountDomainStore,'upsert_local',fail)
    with pytest.raises(RuntimeError):
        save_factor_set('alice',second)
    assert [v['ref'] for v in list_factor_sets('alice')]==[first['ref']]
    assert get_factor_set('alice',second['ref']) is None

def test_family_delete_versions_sets_and_retains_removed_factor(database):
    from tools.data.sqlite.account_manager.factor_param_config import delete_factor_family_configs
    from tools.data.sqlite.account_manager.factor_set import historical_factor
    first = version('CA','OA')
    save_factor_set('alice',first)
    delete_factor_family_configs('CA')
    active = list_factor_sets('alice')
    assert len(active)==1
    assert active[0]['identity']['members']==[member('OA')]
    assert historical_factor('alice',active[0]['ref'],member('CA')['ref'])==member('CA')
    assert historical_factor('bob',active[0]['ref'],member('CA')['ref']) is None
    assert get_factor_set('alice',first['ref'])['identity']==first['identity']
    assert any(e['action']=='removed' and e['reason']=='family_deleted'
        for e in factor_set_history('alice',first['ref'])['items'])

def test_history_and_retired_members_sync_to_cold_peer(tmp_path,monkeypatch):
    from server.manager.storage.account_domain import AccountDomainSyncService
    from tests.scripts.test_worktree_manager_account_domain_sync import MemoryControlStore
    from tools.data.sqlite.account_manager.factor_set import historical_factor
    control=MemoryControlStore()
    left=AccountDomainSyncService(sqlite_path=tmp_path/'left.sqlite',control_store=control,manager_id='left')
    right=AccountDomainSyncService(sqlite_path=tmp_path/'right.sqlite',control_store=control,manager_id='right')
    monkeypatch.setattr(settings,'CACHE_DB_PATH',left.local.path)
    old,new=version('CA','OA'),version('OA')
    save_factor_set('alice',old)
    save_factor_set('alice',new)
    expected={e['event_id'] for e in factor_set_history('alice',new['ref'])['items']}
    left.flush(principal='alice')
    right.pull(principal='alice')
    monkeypatch.setattr(settings,'CACHE_DB_PATH',right.local.path)
    assert {v['ref'] for v in list_factor_sets('alice')}=={new['ref']}
    assert {e['event_id'] for e in factor_set_history('alice',new['ref'])['items']}==expected
    assert historical_factor('alice',new['ref'],member('CA')['ref'])==member('CA')
    delete_factor_set('alice',new['ref'])
    right.flush(principal='alice')
    left.pull(principal='alice')
    monkeypatch.setattr(settings,'CACHE_DB_PATH',left.local.path)
    assert list_factor_sets('alice')==[]
    assert get_factor_set('alice',old['ref'])['identity']==old['identity']

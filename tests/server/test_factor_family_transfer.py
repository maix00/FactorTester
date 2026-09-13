import pytest
import settings
from tools.data.sqlite.factor_source_store import upsert_factor_source, load_factor_source
from tools.data.sqlite.factor_source_versions import record_factor_formula_version, load_factor_formula_version
from tools.data.sqlite.account_manager.factor_param_config import save_factor_param_config
from tools.data.sqlite.account_manager.factor_set import save_factor_set, list_factor_sets, factor_set_history
from server.modules.custom_factors.family_transfer import family_change_impact, transfer_family
from server.modules.custom_factors.factor_library_store import load_factor_param_config
from tools.factors.formula_identity import freeze_factor_identity
from tools.factors.factor_set_identity import freeze_factor_set_identity

SOURCE='class CA(FactorFamily):\n    @staticmethod\n    def factor_expr():\n        return OPEN\n'


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'CACHE_DB_PATH',tmp_path/'db.sqlite')
    monkeypatch.setattr(settings,'CACHE_DIR',tmp_path)
    monkeypatch.setattr('server.modules.custom_factors.crud_routes._family_formula_fingerprint',lambda *a:'a'*64)
    upsert_factor_source('public','','CA','CA',SOURCE,family_formula_fingerprint='a'*64)
    record_factor_formula_version('public','','CA',SOURCE,family_formula_fingerprint='a'*64)
    f=freeze_factor_identity(owner_ref='public',family_alias='CA',factor_alias='CA|N:1',
        family_formula_fingerprint='a'*64,self_formula_fingerprint='b'*64,params={'N':1})
    for user in ['alice','bob']:
        save_factor_param_config(user,'CA',[{'N':1}],resolved_factors=[f])
        save_factor_set(user,freeze_factor_set_identity(owner_ref='principal:'+user,set_id='set',alias='集合',members=[f]))
    return f


def test_transfer_keeps_own_params_versions_and_set_history(setup):
    impact=family_change_impact('public','alice','CA')
    result=transfer_family('public','alice','CA',expected_revision=impact['revision'])
    assert result['target_kind']=='custom'
    own=load_factor_param_config('alice','CA')
    assert own['params_list']==[{'N':1}]
    assert own['resolved_factors'][0]['owner_ref']=='alice'
    assert own['resolved_factors'][0]['ref']!=setup['ref']
    assert load_factor_param_config('bob','CA') is None
    assert list_factor_sets('bob')==[]
    current=list_factor_sets('alice')[0]
    assert current['identity']['members'][0]['owner_ref']=='alice'
    assert {e['action'] for e in factor_set_history('alice',current['ref'])['items']}=={'added','removed'}
    assert load_factor_source('public','','CA') is None
    assert load_factor_source('custom','alice','CA')
    assert load_factor_formula_version('public','','CA','a'*64)
    assert load_factor_formula_version('custom','alice','CA','a'*64)
    revision=family_change_impact('custom','alice','CA')['revision']
    transfer_family('custom','alice','CA',expected_revision=revision)
    assert load_factor_param_config('alice','CA')['resolved_factors'][0]['owner_ref']=='public'


def test_stale_confirmation_and_collision_preserve_source(setup):
    with pytest.raises(ValueError,match='依赖已变化'):
        transfer_family('public','alice','CA',expected_revision='old')
    impact=family_change_impact('public','alice','CA')
    upsert_factor_source('custom','alice','CA','CA',SOURCE)
    with pytest.raises(ValueError,match='同名'):
        transfer_family('public','alice','CA',expected_revision=impact['revision'])
    assert load_factor_source('public','','CA')
    assert load_factor_param_config('bob','CA')


def test_transfer_rolls_back_all_writes_on_event_failure(setup,monkeypatch):
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    impact=family_change_impact('public','alice','CA')
    original=LocalAccountDomainStore.upsert_local
    def fail(self,**kwargs):
        if kwargs['entity_type']=='factor_set_event': raise RuntimeError('failure')
        return original(self,**kwargs)
    monkeypatch.setattr(LocalAccountDomainStore,'upsert_local',fail)
    with pytest.raises(RuntimeError):
        transfer_family('public','alice','CA',expected_revision=impact['revision'])
    assert load_factor_source('public','','CA')
    assert load_factor_source('custom','alice','CA') is None
    assert load_factor_param_config('bob','CA')
    assert list_factor_sets('alice')[0]['identity']['members'][0]['ref']==setup['ref']

def test_transfer_endpoint_denies_non_admin_before_touching_source(monkeypatch):
    from flask import Flask
    from server.modules.custom_factors import crud_routes
    monkeypatch.setattr(crud_routes,'_current_user_is_super_admin',lambda:False)
    app=Flask(__name__)
    with app.test_request_context(json={'revision':'x'}):
        response,status=crud_routes.api_transfer_family.__wrapped__('public','CA')
    assert status==403


def test_delete_preserves_same_alias_other_owner(setup):
    from server.modules.custom_factors.family_transfer import delete_family
    other=freeze_factor_identity(owner_ref='charlie',family_alias='CA',factor_alias='CA|N:2',
        family_formula_fingerprint='c'*64,self_formula_fingerprint='d'*64,params={'N':2})
    save_factor_param_config('charlie','CA',[{'N':2}],resolved_factors=[other])
    revision=family_change_impact('public','alice','CA')['revision']
    delete_family('public','alice','CA',expected_revision=revision)
    assert load_factor_param_config('charlie','CA')['resolved_factors'][0]['ref']==other['ref']
    assert load_factor_param_config('bob','CA') is None


def test_transfer_public_catalog_does_not_revive_peer_source(setup):
    """A remote byte provider remains available for historical frozen refs."""
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    from server.manager.services.public_catalog import public_factor_library
    mirror = LocalAccountDomainStore(settings.CACHE_DB_PATH)
    mirror.upsert_local(principal='__public__', entity_type='factor_source',
        entity_id='public:CA@peer', manager_id='peer', payload={
            'source_kind': 'public', 'factor_id': 'CA', 'factor_name': 'CA',
            'family_formula_fingerprint': 'a' * 64,
            'storage_server_id': 'peer', 'catalog': {'description': 'old provider'},
        })
    assert 'CA' in {f['factor_family_alias'] for f in public_factor_library()['families']}
    revision = family_change_impact('public', 'alice', 'CA')['revision']
    transfer_family('public', 'alice', 'CA', expected_revision=revision)
    assert 'CA' not in {f['factor_family_alias'] for f in public_factor_library()['families']}
    assert load_factor_formula_version('public', '', 'CA', 'a' * 64)
    revision = family_change_impact('custom', 'alice', 'CA')['revision']
    transfer_family('custom', 'alice', 'CA', expected_revision=revision)
    assert 'CA' in {f['factor_family_alias'] for f in public_factor_library()['families']}

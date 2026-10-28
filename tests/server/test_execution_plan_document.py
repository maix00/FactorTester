from copy import deepcopy
import pytest
from server.services.execution_plans import document,encode,strip_selection


def configuration():
    return {'schema_version':3,'shared':{'factors':[]},'analyses':{'backtest':{'execution':{'settings':{}}}},'ui':{}}


def test_single_document_roundtrip_without_duplicate_configuration_or_source_selection_in_runspec():
    plan=document(configuration())
    plan['execution'].update(manager_id='manager-a',bundles=[{'bundle_id':'Local','owner':'platform'}])
    stored=encode(plan)
    assert document(stored)==plan
    assert strip_selection(stored)==plan['run_spec']['configuration']
    assert '_execution_plan' not in strip_selection(stored)['ui']
    assert 'configuration' not in stored['ui']['_execution_plan']


def test_plan_rejects_second_editable_configuration_or_generated_identity():
    plan=document(configuration())
    with pytest.raises(ValueError):encode({**plan,'configuration':configuration()})
    plan['run_spec']['run_spec_hash']='fake'
    with pytest.raises(ValueError):encode(plan)


def test_bundle_multiselect_is_identity_scoped_and_independent_of_products_and_time():
    plan=document(configuration())
    plan['execution']['bundles']=[{'bundle_id':'a','owner':'platform'},{'bundle_id':'b','owner':'alice'}]
    assert len(document(encode(plan))['execution']['bundles'])==2
    assert 'start_ns' not in plan['execution']
    plan['execution']['bundles'].append(deepcopy(plan['execution']['bundles'][0]))
    with pytest.raises(ValueError,match='duplicate'):encode(plan)


def test_factor_template_product_groups_share_the_execution_scope_projection(monkeypatch):
    from server.services.configuration_strategies import execution_groups
    from server.services.frozen_product_scope import freeze_product_scope
    from server.modules.shared.run_spec_resolution.freezing import _backtest_product_scope_refs
    monkeypatch.setattr('server.modules.products.product_category_paths.resolve_product_scope_paths',lambda paths,**_:paths)
    configuration={'payload':{'schema_version':3,'shared':{'factors':[], 'product_selections':{'inline:products':{'paths':['T','TL']}}},
        'analyses':{'backtest':{'factor_strategy_bindings':[{'strategy_id':'s','product_group_ref':'inline:products'}]}},'ui':{}}}
    backtest=configuration['payload']['analyses']['backtest']
    assert execution_groups(backtest)==[{'id':'s','product_path_selection_id':'inline:products'}]
    frozen=freeze_product_scope(configuration,owner='alice',analyses=['backtest'])
    assert frozen['payload']['shared']['product_selections']['inline:products']['paths']==['T','TL']
    assert _backtest_product_scope_refs(backtest)==('inline:products',)

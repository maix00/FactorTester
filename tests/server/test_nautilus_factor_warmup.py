import pytest
from alpha.factor import warmup_requirements
from server.services.nautilus_bridge.warmup import bind_observed_source_clock,freeze_warmup_settings,require_observed_clock_runtime,resolve_run_warmup,warmup_configuration_schema


def test_observed_clock_binds_frozen_ordinal_only_when_product_clocks_and_phases_match():
    spec = {'nodes': [{'kind': 'column', 'index': 0},
                      {'kind': 'signal', 'child': 0, 'observed_period': 30, 'signal_ns': 30}], 'outputs': [1]}
    a = {'source_ordinal_start': 15, 'selected_count': 4, 'selected_clock_sha256': 'a' * 64}
    b = {**a, 'source_ordinal_start': 45}
    bound = bind_observed_source_clock(spec, {'A': a, 'B': b})
    assert bound['nodes'][1]['source_ordinal'] == 15
    assert 'source_ordinal' not in spec['nodes'][1]
    with pytest.raises(ValueError, match='phases differ'):
        bind_observed_source_clock(spec, {'A': a, 'B': {**b, 'source_ordinal_start': 46}})
    with pytest.raises(ValueError, match='identical product clocks'):
        bind_observed_source_clock(spec, {'A': a, 'B': {**b, 'selected_clock_sha256': 'b' * 64}})
    with pytest.raises(ValueError, match='restage'):
        bind_observed_source_clock(spec, {'A': {**a, 'source_ordinal_start': None}})
    assert bind_observed_source_clock({'nodes': [{'kind': 'column'}]}, {}) == {'nodes': [{'kind': 'column'}]}


def test_old_native_runtime_cannot_silently_ignore_observed_clock():
    from types import SimpleNamespace
    spec = {'nodes': [{'kind': 'signal', 'observed_period': 30}]}
    with pytest.raises(RuntimeError, match='rebuild the composed extension'):
        require_observed_clock_runtime(spec, SimpleNamespace())
    require_observed_clock_runtime(spec, SimpleNamespace(FACTOR_OBSERVED_SOURCE_ORDINAL_VERSION=1))
    require_observed_clock_runtime({'nodes': [{'kind': 'column'}]}, SimpleNamespace())


def test_settings_and_schema_are_shared_and_disabled_is_explicitly_diagnostic():
    assert freeze_warmup_settings().mode=='auto'
    with pytest.raises(ValueError,match='diagnostic_only'):freeze_warmup_settings({'mode':'disabled'})
    assert freeze_warmup_settings({'mode':'disabled','diagnostic_only':True}).manifest()['diagnostic_only']
    assert 'factor_warmup.mode' in {r['path'] for r in warmup_configuration_schema()}


def test_calendar_history_is_checked_before_engine_and_formal_window_is_distinct():
    spec={'nodes':[{'kind':'column','index':0},{'kind':'rolling','child':0,'window':3}], 'outputs':[1]}
    receipt={'first_available_ns':10,'last_available_ns':290,'session_summaries':[
        {'start_ns':0,'end_ns':90,'bar_count':10}, {'start_ns':100,'end_ns':190,'bar_count':10},
        {'start_ns':200,'end_ns':290,'bar_count':10}]}
    policy=freeze_warmup_settings()
    result=resolve_run_warmup(spec,{'A':receipt},policy=policy,trading_start_utc='1970-01-01T00:00:00.000000200Z',end_utc='1970-01-01T00:00:00.000000290Z')
    assert result['sources']['A']['required_start_ns']==100
    assert result['trading_start_ns']==result['performance_start_ns']==200
    assert result['performance_eligible']
    with pytest.raises(ValueError,match='insufficient warmup'):
        resolve_run_warmup(spec,{'A':receipt},policy=policy,trading_start_utc='1970-01-01T00:00:00.000000010Z',end_utc='1970-01-01T00:00:00.000000290Z')


def test_paper_requires_composed_250_plus_20_days_not_250_calendar_days():
    spec={'nodes':[{'kind':'column','index':0},{'kind':'session_rolling','child':0,'lookback_sessions':250},
        {'kind':'session_rolling','child':1,'lookback_sessions':20}],'outputs':[2]}
    assert warmup_requirements(spec)['combined']['trading_days']==270


def test_authoring_does_not_mark_nested_warmup_policy_as_unknown():
    from server.services.nautilus_bridge.run_spec import _complete_authoring_field_coverage
    fields=[];blockers=[]
    _complete_authoring_field_coverage({'factor_warmup':{'mode':'auto'}},fields,blockers,source_adapter_available=True)
    assert blockers==[]

import pytest
from alpha.factor import warmup_requirements
from server.services.nautilus_bridge.warmup import freeze_warmup_settings,resolve_run_warmup,warmup_configuration_schema


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

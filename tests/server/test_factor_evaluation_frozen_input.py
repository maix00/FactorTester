import pytest

from server.modules.single_factor_test.evaluation import FactorEvaluation
from server.modules.shared import factor_param_resolver
from tools.factors.formula_identity import freeze_factor_identity


def frozen(alias, family, params):
    return freeze_factor_identity(owner_ref='principal:alice', family_alias=family,
                                 factor_alias=alias, family_formula_fingerprint='a'*64,
                                 self_formula_fingerprint='b'*64, params=params)


def test_evaluation_resolves_primary_and_nested_factor_from_run_snapshot(monkeypatch):
    child = frozen('Child|N:20d', 'Child', {'N': '20d'})
    parent = frozen('Parent|P:[Child|N:20d]', 'Parent', {'P': child['ref']})
    calls = []
    monkeypatch.setattr(factor_param_resolver, 'resolve_factor_param_value',
                        lambda value, **kwargs: calls.append((value, kwargs)) or 'resolved')
    monkeypatch.setattr('server.services.factor_registry.factor_from_alias',
                        lambda *args, **kwargs: pytest.fail('must not consult the mutable catalog'))
    evaluation = FactorEvaluation(selection=None, factor_family_alias='Parent',
                                  factor_alias=parent['alias'], page_uuid='', owner='alice',
                                  frozen_factors=[child, parent], factor_ref=parent['ref'])
    assert evaluation._resolve_run_factor() == 'resolved'
    value, kwargs = calls[0]
    assert value['ref'] == parent['ref']
    assert kwargs['frozen_by_ref'][child['ref']]['identity']['params'] == {'N': '20d'}
    evaluation.factor_ref = 'factor:v2:missing'
    with pytest.raises(ValueError, match='唯一确定'):
        evaluation._resolve_run_factor()


def test_from_run_spec_retains_frozen_graph(monkeypatch):
    parent = frozen('Parent', 'Parent', {})
    monkeypatch.setattr('server.modules.single_factor_test.evaluation.selection_from_request',
                        lambda *args, **kwargs: None)
    evaluation = FactorEvaluation.from_run_spec({
        '_owner': 'alice', 'run_id': 'test-run', 'factor_family_alias': 'Parent',
        'factor_alias': 'Parent', 'factor_ref': parent['ref'],
        'run_spec': {'configuration': {'shared': {'factors': [parent]}}},
    })
    assert evaluation.frozen_factors == [parent]
    assert evaluation.factor_ref == parent['ref']


def test_backtest_result_sink_uses_frozen_root_factor_series(monkeypatch):
    from types import SimpleNamespace
    from server.modules.single_factor_test.process_runners import _factor_series_sink

    child = frozen('Child', 'Child', {})
    parent = frozen('Parent', 'Parent', {'P': child['ref']})
    requests = []
    received = []

    def evaluate(request):
        requests.append(request)
        return SimpleNamespace(run=lambda: {
            'factor': {'freq': '1m'},
            'series': [{'product': 'TEST', 'dates': [1, 2], 'values': [3.0, 4.0]}],
        })

    monkeypatch.setattr(FactorEvaluation, 'from_run_spec', evaluate)
    sink = SimpleNamespace(emit_result=lambda data, **kw: received.append((data, kw)))
    payload = {
        'output_requests': ['factor_series'], 'factors': [child, parent, parent],
        'groups': [{'factor_candidate_refs': [parent['ref']]}],
        'product_selections': {
            'first': {'paths': ['Product/_products/A', 'Product/_products/B']},
            'second': {'paths': ['Product/_products/B', 'Product/_products/C']},
        },
    }
    _factor_series_sink(payload, sink).emit_result({'completed': True}, source='backtest')
    assert len(requests) == 1
    assert requests[0]['factor_ref'] == parent['ref']
    assert requests[0]['selected_paths'] == [
        'Product/_products/A', 'Product/_products/B', 'Product/_products/C',
    ]
    result, metadata = received[0]
    assert result['completed'] is True and metadata == {'source': 'backtest'}
    assert result['factor_series']['factors'][0]['ref'] == parent['ref']
    assert result['factor_series']['series'][0]['values'] == [3.0, 4.0]
    assert _factor_series_sink({'output_requests': []}, sink) is sink

import numpy as np
import pandas as pd

from alpha.factor import (
    ColumnRef,
    EvalContext,
    FactorExpr,
    Parameter,
    TypeParam,
    ParamRef,
    _to_expr,
)


def _ctx(values):
    return EvalContext(
        products=('A',),
        preloaded={'A': pd.DataFrame({'CLOSE': values})},
    )


def test_alpha_factor_public_api_evaluates_without_factortester_objects():
    values = np.arange(20, dtype=float)
    expression = ColumnRef('CLOSE').rolling(3).mean()
    result = expression.evaluate(_ctx(values))
    expected = pd.Series(values).rolling(3, min_periods=1).mean().to_numpy()
    np.testing.assert_allclose(result['A'].to_numpy(), expected)


def test_alpha_factor_public_api_supports_parameters_and_composition():
    parameter = TypeParam('N', default_value=3, typ=int)
    resolved = ParamRef(parameter).resolve()
    assert resolved.value == 3
    expression = (ColumnRef('CLOSE').rolling(3).mean() + 1.0).shift(1)
    result = expression.evaluate(_ctx(np.arange(10, dtype=float)))
    assert np.isnan(result['A'].iloc[0])
    assert result['A'].iloc[1] == 1.0


def test_alpha_factor_window_semantics():
    from alpha.factor import NanPolicy

    values = np.array([1.0, np.nan, 3.0, 4.0])
    ctx = _ctx(values)
    default = ColumnRef('CLOSE').rolling(2).mean().evaluate(ctx)['A'].to_numpy()
    skip = (
        ColumnRef('CLOSE').rolling(2)
        .semantics(min_periods=1, nan_policy=NanPolicy.SKIP)
        .mean()
        .evaluate(ctx)['A'].to_numpy()
    )
    np.testing.assert_allclose(default, [1.0, np.nan, np.nan, 3.5], equal_nan=True)
    np.testing.assert_allclose(skip, [1.0, 1.0, 3.0, 3.5])


def test_alpha_factor_cross_sectional_executes_in_rust():
    frame_a = pd.DataFrame({'CLOSE': [1.0, 2.0, 3.0]})
    frame_b = pd.DataFrame({'CLOSE': [3.0, 2.0, 1.0]})
    ctx = EvalContext(products=('A', 'B'), preloaded={'A': frame_a, 'B': frame_b})
    result = ColumnRef('CLOSE').cs_zscore().evaluate(ctx)
    np.testing.assert_allclose(result['A'].to_numpy(), [-0.70710678, 0.0, 0.70710678])
    np.testing.assert_allclose(result['B'].to_numpy(), [0.70710678, 0.0, -0.70710678])


def test_alpha_factor_family_owns_versioned_identity():
    from alpha.factor import FactorFamily

    class Momentum(FactorFamily):
        alias = 'momentum'

        @staticmethod
        def factor_expr():
            return ColumnRef('CLOSE').rolling(3).mean()

    definition = Momentum.get_factor(owner_ref='tester')
    assert definition.ref.startswith('factor:v2:')
    assert definition.identity.factor_ref == definition.ref
    assert definition.identity.family_ref.startswith('factor-family:v2:')
    first = definition
    second = Momentum.get_factor(owner_ref='tester')
    assert first.ref == second.ref
    other = Momentum.get_factor(owner_ref='other')
    assert other.ref != first.ref


def test_alpha_factor_bar_count_scope_executes_in_rust():
    from alpha.factor import scope_bars

    values = np.arange(10, dtype=float)
    result = ColumnRef('CLOSE').groupby_scope(scope_bars(3)).mean().evaluate(_ctx(values))
    expected = []
    for start in range(0, 10, 3):
        group = values[start:start + 3]
        expected.extend(np.cumsum(group) / np.arange(1, len(group) + 1))
    np.testing.assert_allclose(result['A'].to_numpy(), expected)


def test_alpha_factor_bar_since_executes_in_rust():
    from alpha.factor import bar_since, scope_bars

    values = np.arange(12, dtype=float)
    condition = ColumnRef('CLOSE') > 4
    result = bar_since(condition, scope=scope_bars(5)).evaluate(_ctx(values))
    expected = []
    for start in range(0, 12, 5):
        last = None
        for index in range(start, min(start + 5, 12)):
            if values[index] > 4:
                last = index
            expected.append(index - last if last is not None else index - start)
    np.testing.assert_allclose(result['A'].to_numpy(), expected)






def test_alpha_factor_trading_day_scope_is_cumulative():
    from alpha.factor import scope_trading_day

    index = pd.date_range('2026-01-05 09:30', periods=8, freq='min')
    values = np.arange(8, dtype=float)
    frame = pd.DataFrame({'CLOSE': values}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    result = ColumnRef('CLOSE').groupby_scope(scope_trading_day()).mean().evaluate(ctx)
    np.testing.assert_allclose(result['A'].to_numpy(), np.cumsum(values) / np.arange(1, 9))


def test_alpha_factor_session_scope_resets_after_gap():
    from alpha.factor import TradingSession, scope_session

    index = pd.DatetimeIndex([
        '2026-01-05 09:30', '2026-01-05 09:31',
        '2026-01-05 10:30', '2026-01-05 10:31',
    ])
    frame = pd.DataFrame({'CLOSE': [0.0, 1.0, 2.0, 3.0]}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    sessions = (
        TradingSession(pd.Timestamp('2026-01-05 09:30').value, pd.Timestamp('2026-01-05 09:31').value),
        TradingSession(pd.Timestamp('2026-01-05 10:30').value, pd.Timestamp('2026-01-05 10:31').value),
    )
    result = ColumnRef('CLOSE').groupby_scope(scope_session(sessions)).mean().evaluate(ctx)
    np.testing.assert_allclose(result['A'].to_numpy(), [0.0, 0.5, 2.0, 2.5])


def test_alpha_factor_serializes_to_rust_plan_spec():
    close = ColumnRef('CLOSE')
    spec = (close.rolling(3).mean() + 1.0).to_plan_spec()
    assert spec is not None
    assert spec['columns'] == ['CLOSE']
    kinds = [node['kind'] for node in spec['nodes']]
    assert kinds == ['column', 'rolling', 'const', 'binary']
    assert spec['nodes'][1]['op'] == 'mean'


def test_alpha_factor_incremental_plan_uses_shared_rust_kernel():
    from alpha.factor import IncrementalFactorPlan

    close = ColumnRef('CLOSE')
    plan = IncrementalFactorPlan(
        {'mean': close.rolling(2).mean(), 'sum': close.rolling(2).sum()},
        ('A',),
    )
    assert plan.update([1.0]) == {'mean': {'A': 1.0}, 'sum': {'A': 1.0}}
    assert plan.update([3.0]) == {'mean': {'A': 2.0}, 'sum': {'A': 4.0}}


def test_signal_align_uses_last_completed_value_only():
    index = pd.date_range('2026-01-05 09:30', periods=6, freq='min')
    frame = pd.DataFrame({'CLOSE': np.arange(6, dtype=float)}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    aligned = ColumnRef('CLOSE').signal_align('2min').evaluate(ctx)
    np.testing.assert_allclose(aligned['A'].to_numpy(), [0.0, 2.0, 4.0])


def test_nested_signal_align_uses_causal_inner_signal():
    index = pd.date_range('2026-01-05 09:30', periods=8, freq='min')
    frame = pd.DataFrame({'CLOSE': np.arange(8, dtype=float)}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    nested = (
        ColumnRef('CLOSE').signal_align('2min').signal_align('4min')
    ).evaluate(ctx)
    np.testing.assert_allclose(nested['A'].to_numpy(), [2.0, 6.0])


def test_unsupported_plan_nodes_are_explicit():
    from alpha.factor import plan_blockers

    expression = ColumnRef('CLOSE').signal_align('2min')
    assert 'SignalAlign' in plan_blockers(expression)


def test_signal_align_rejects_unsupported_basepoint_explicitly():
    import pytest

    with pytest.raises(ValueError):
        ColumnRef('CLOSE').signal_align('2min', basepoint='middle')


def test_incremental_plan_negation_and_multi_product_columns():
    import json
    from alpha import FactorPlanState

    neg = (-ColumnRef('CLOSE')).to_plan_spec()
    state = FactorPlanState(json.dumps(neg), 1)
    np.testing.assert_allclose(state.update(np.array([3.0])), [-3.0])

    col = ColumnRef('CLOSE').to_plan_spec()
    state = FactorPlanState(json.dumps(col), 2)
    np.testing.assert_allclose(state.update(np.array([2.0, 4.0])), [2.0, 4.0])


def test_signal_align_first_and_exclude_current_boundary():
    index = pd.date_range('2026-01-05 09:30', periods=6, freq='min')
    frame = pd.DataFrame({'CLOSE': np.arange(6, dtype=float)}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    first = ColumnRef('CLOSE').signal_align('2min', basepoint='first').evaluate(ctx)
    np.testing.assert_allclose(first['A'].to_numpy()[:4], [0.0, 1.0, 3.0])
    excluded = ColumnRef('CLOSE').signal_align('2min', include_current=False).evaluate(ctx)
    assert np.isnan(excluded['A'].iloc[0])


def test_signal_align_daily_basepoint_selects_clock_time():
    index = pd.date_range('2026-01-05 09:00', periods=120, freq='min')
    frame = pd.DataFrame({'CLOSE': np.arange(120, dtype=float)}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    aligned = ColumnRef('CLOSE').signal_align('1d', daily_basepoint='10:00').evaluate(ctx)
    assert list(aligned.index) == [pd.Timestamp('2026-01-05 10:00')]
    assert aligned['A'].iloc[0] == 60.0


def test_signal_align_scope_none_keeps_continuous_frequency_grid():
    index = pd.DatetimeIndex([
        '2026-01-05 09:30', '2026-01-05 09:31',
        '2026-01-05 09:32', '2026-01-06 09:30',
    ])
    frame = pd.DataFrame({'CLOSE': [0.0, 1.0, 2.0, 3.0]}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    aligned = ColumnRef('CLOSE').signal_align('2min').evaluate(ctx)
    assert list(aligned.index[:2]) == [pd.Timestamp('2026-01-05 09:30'), pd.Timestamp('2026-01-05 09:32')]


def test_signal_align_trading_day_scope_restarts_each_day():
    from alpha.factor import scope_trading_day

    index = pd.DatetimeIndex([
        '2026-01-05 09:30', '2026-01-05 09:31', '2026-01-05 09:32',
        '2026-01-06 09:30', '2026-01-06 09:31', '2026-01-06 09:32',
    ])
    frame = pd.DataFrame({'CLOSE': np.arange(6, dtype=float)}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    aligned = ColumnRef('CLOSE').signal_align('2min', scope=scope_trading_day()).evaluate(ctx)
    assert list(aligned.index) == [
        pd.Timestamp('2026-01-05 09:30'), pd.Timestamp('2026-01-05 09:32'),
        pd.Timestamp('2026-01-06 09:30'), pd.Timestamp('2026-01-06 09:32'),
    ]
    np.testing.assert_allclose(aligned['A'].to_numpy(), [0.0, 2.0, 3.0, 5.0])


def test_signal_align_scope_anchor_positions_grid_inside_scope():
    index = pd.date_range('2026-01-05 09:31', periods=4, freq='min')
    frame = pd.DataFrame({'CLOSE': np.arange(4, dtype=float)}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    from_start = ColumnRef('CLOSE').signal_align('2min').evaluate(ctx)
    assert list(from_start.index) == [pd.Timestamp('2026-01-05 09:32'), pd.Timestamp('2026-01-05 09:34')]
    from_end = ColumnRef('CLOSE').signal_align('2min', scope_anchor='end').evaluate(ctx)
    assert list(from_end.index) == [pd.Timestamp('2026-01-05 09:31'), pd.Timestamp('2026-01-05 09:33')]


def test_signal_align_legacy_positional_basepoint():
    index = pd.date_range('2026-01-05 09:30', periods=6, freq='min')
    frame = pd.DataFrame({'CLOSE': np.arange(6, dtype=float)}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    aligned = ColumnRef('CLOSE').signal_align('2min', 'last').evaluate(ctx)
    np.testing.assert_allclose(aligned['A'].to_numpy(), [0.0, 2.0, 4.0])


def test_signal_align_session_scope_uses_calendar_boundaries():
    from alpha.factor import TradingSession, scope_session

    index = pd.DatetimeIndex([
        '2026-01-05 09:30', '2026-01-05 09:31', '2026-01-05 09:32',
        '2026-01-06 09:30', '2026-01-06 09:31', '2026-01-06 09:32',
    ])
    frame = pd.DataFrame({'CLOSE': np.arange(6, dtype=float)}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    sessions = (
        TradingSession(pd.Timestamp('2026-01-05 09:30').value, pd.Timestamp('2026-01-05 09:32').value),
        TradingSession(pd.Timestamp('2026-01-06 09:30').value, pd.Timestamp('2026-01-06 09:32').value),
    )
    aligned = ColumnRef('CLOSE').signal_align('2min', scope=scope_session(sessions), partial='emit').evaluate(ctx)
    assert list(aligned.index) == [pd.Timestamp(ts) for ts in [
        '2026-01-05 09:30', '2026-01-05 09:32',
        '2026-01-06 09:30', '2026-01-06 09:32',
    ]]
    np.testing.assert_allclose(aligned['A'].to_numpy(), [0.0, 2.0, 3.0, 5.0])

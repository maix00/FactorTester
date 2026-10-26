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


def test_signal_align_session_scope_serializes_to_rust_plan():
    import json
    from alpha import FactorPlanState
    from alpha.factor import TradingSession, scope_session

    session = TradingSession(
        pd.Timestamp('2026-01-05 09:30').value,
        pd.Timestamp('2026-01-05 09:32').value,
    )
    close = ColumnRef('CLOSE')
    expression = close.signal_align('2min', scope=scope_session((session,)))
    spec = expression.to_plan_spec()
    assert spec is not None
    signal = next(node for node in spec['nodes'] if node['kind'] == 'signal')
    assert signal['signal_ns'] == 120_000_000_000
    assert signal['sessions'] == [[session.start_ns, session.end_ns, session.start_ns]]

    state = FactorPlanState(json.dumps(spec), 1)
    outputs = [
        float(state.update_at(pd.Timestamp(timestamp).value, np.array([value]))[0])
        for timestamp, value in [
            ('2026-01-05 09:30', 0.0),
            ('2026-01-05 09:31', 1.0),
            ('2026-01-05 09:32', 2.0),
        ]
    ]
    np.testing.assert_allclose(outputs, [0.0, 0.0, 2.0])


def test_signal_align_anchor_bar_is_inclusive_by_default():
    index = pd.DatetimeIndex(['2026-01-05 09:30'])
    frame = pd.DataFrame({'CLOSE': [7.0]}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    included = ColumnRef('CLOSE').signal_align('2min').evaluate(ctx)
    assert included['A'].iloc[0] == 7.0
    excluded = ColumnRef('CLOSE').signal_align('2min', include_current=False).evaluate(ctx)
    assert np.isnan(excluded['A'].iloc[0])


def test_session_groupby_scope_serializes_and_executes_in_rust():
    import json
    from alpha import FactorPlanState
    from alpha.factor import TradingSession, scope_session

    index = pd.DatetimeIndex([
        '2026-01-05 09:30', '2026-01-05 09:31',
        '2026-01-06 09:30', '2026-01-06 09:31',
    ])
    frame = pd.DataFrame({'CLOSE': [1.0, 3.0, 10.0, 30.0]}, index=index)
    ctx = EvalContext(products=('A',), preloaded={'A': frame})
    sessions = (
        TradingSession(pd.Timestamp('2026-01-05 09:30').value, pd.Timestamp('2026-01-05 09:31').value),
        TradingSession(pd.Timestamp('2026-01-06 09:30').value, pd.Timestamp('2026-01-06 09:31').value),
    )
    expression = ColumnRef('CLOSE').groupby_scope(scope_session(sessions)).mean()
    spec = expression.to_plan_spec()
    node = next(node for node in spec['nodes'] if node['kind'] == 'scope')
    assert node['sessions'] == [[sessions[0].start_ns, sessions[0].end_ns, sessions[0].start_ns],
                                [sessions[1].start_ns, sessions[1].end_ns, sessions[1].start_ns]]
    state = FactorPlanState(json.dumps(spec), 1)
    outputs = [
        float(state.update_at(pd.Timestamp(timestamp).value, np.array([value]))[0])
        for timestamp, value in [
            ('2026-01-05 09:30', 1.0), ('2026-01-05 09:31', 3.0),
            ('2026-01-06 09:30', 10.0), ('2026-01-06 09:31', 30.0),
        ]
    ]
    np.testing.assert_allclose(outputs, [1.0, 2.0, 10.0, 20.0])


def test_sessions_from_trading_calendar_window():
    from alpha.factor import sessions_from_calendar
    from tools.factors.expr.streaming.calendar_window import TradingCalendarWindow, TradingSession as ToolsSession

    calendar = TradingCalendarWindow((
        ToolsSession('2026-01-05', 100, 200, 2),
        ToolsSession('2026-01-06', 300, 400, 2),
    ))
    scope = sessions_from_calendar(calendar)
    assert [(item.start_ns, item.end_ns) for item in scope.sessions] == [(100, 200), (300, 400)]


def test_plan_spec_carries_structural_node_keys():
    close = ColumnRef('CLOSE')
    spec = (close.rolling(3).mean() + close.rolling(3).mean()).to_plan_spec()
    assert len(spec['keys']) == len(spec['nodes'])
    assert spec['nodes'][1]['kind'] == 'rolling'
    assert spec['keys'][1].startswith("('alpha.factor.Rolling")


def test_signal_align_legacy_identity_is_unchanged_by_new_parameters():
    from alpha.factor import scope_trading_day

    close = ColumnRef('CLOSE')
    legacy = close.signal_align('2min')
    assert legacy._structural_key() == (
        'alpha.factor.SignalAlign', '2min', 'last', close._structural_key(),
    )
    scoped = close.signal_align('2min', scope=scope_trading_day())
    assert scoped._structural_key()[0] == 'alpha.factor.SignalAlign:v2'
    assert scoped.semantic_fingerprint() != legacy.semantic_fingerprint()


def _signal_state(expression):
    import json
    from alpha import FactorPlanState
    return FactorPlanState(json.dumps(expression.to_plan_spec()), 1)


def test_signal_align_first_include_false_and_emit_in_rust():
    from alpha.factor import TradingSession, scope_session

    session = TradingSession(0, 250)
    close = ColumnRef('CLOSE')
    bars = [(0, 0.0), (50, 1.0), (100, 2.0), (150, 3.0), (200, 4.0), (250, 5.0)]

    first = _signal_state(close.signal_align('100ns', scope=scope_session((session,)), basepoint='first'))
    first_values = [float(first.update_at(timestamp, np.array([value]))[0]) for timestamp, value in bars]
    np.testing.assert_allclose(first_values, [0.0, 0.0, 1.0, 1.0, 3.0, 3.0])

    excluded = _signal_state(close.signal_align('100ns', scope=scope_session((session,)), include_current=False))
    excluded_values = [float(excluded.update_at(timestamp, np.array([value]))[0]) for timestamp, value in bars]
    assert np.isnan(excluded_values[0])
    assert excluded_values[2] == 1.0

    emitted = _signal_state(close.signal_align('100ns', scope=scope_session((session,)), partial='emit'))
    emitted_values = [float(emitted.update_at(timestamp, np.array([value]))[0]) for timestamp, value in bars]
    assert emitted_values[-1] == 5.0


def test_trading_day_scope_anchor_end_enters_rust_plan():
    from alpha.factor import TradingSession, scope_trading_day

    session = TradingSession(0, 250)
    expression = ColumnRef('CLOSE').signal_align(
        '100ns', scope=scope_trading_day((session,)), scope_anchor='end',
    )
    spec = expression.to_plan_spec()
    assert spec is not None
    state = _signal_state(expression)
    values = [
        float(state.update_at(timestamp, np.array([value]))[0])
        for timestamp, value in [(0, 0.0), (100, 1.0), (200, 2.0), (250, 3.0)]
    ]
    assert np.isnan(values[0])
    assert values[2] == 2.0


def test_tools_incremental_uses_rust_facade_for_simple_rolling():
    from tools.data.types import DataColumn
    from tools.factors.expr.leaf import ColumnRef as ToolColumnRef
    from tools.factors.expr.streaming.incremental import compile_incremental_factor

    expression = ToolColumnRef(DataColumn.CLOSE).rolling(2).mean()
    executor = compile_incremental_factor('mean', expression, ('A',))
    assert getattr(executor._multi, 'uses_rust', False) is True
    executor.on_bar(pd.Timestamp('2026-01-05 09:30'), {'A': {DataColumn.CLOSE.name: 1.0}})
    executor.on_bar(pd.Timestamp('2026-01-05 09:31'), {'A': {DataColumn.CLOSE.name: 3.0}})
    assert executor.on_signal(pd.Timestamp('2026-01-05 09:31')) == {'A': 2.0}


def test_tools_incremental_rust_facade_supports_multiple_columns():
    from tools.data.types import DataColumn
    from tools.factors.expr.leaf import ColumnRef as ToolColumnRef
    from tools.factors.expr.streaming.incremental import compile_incremental_factor

    expression = ToolColumnRef(DataColumn.CLOSE) + ToolColumnRef(DataColumn.VOLUME)
    executor = compile_incremental_factor('sum', expression, ('A',))
    assert getattr(executor._multi, 'uses_rust', False) is True
    executor.on_bar(pd.Timestamp('2026-01-05 09:30'),
                    {'A': {DataColumn.CLOSE.name: 2.0, DataColumn.VOLUME.name: 3.0}})
    assert executor.on_signal(pd.Timestamp('2026-01-05 09:30')) == {'A': 5.0}


def test_alpha_factor_bar_distance_is_not_falsely_claimed_as_migrated():
    from alpha.factor import bar_distance, scope_bars

    condition = ColumnRef('CLOSE') > 0
    expression = bar_distance(condition, scope=scope_bars(3), default=3.0)
    spec = expression.to_plan_spec()
    assert spec is None


def test_alpha_factor_ema_executes_in_rust_kernel():
    import json
    from alpha import FactorPlanState

    spec = ColumnRef('CLOSE').rolling(3).ema().to_plan_spec()
    state = FactorPlanState(json.dumps(spec), 1)
    values = [float(state.update(np.array([value]))[0]) for value in (1.0, 3.0, 5.0)]
    assert values[0] == 1.0
    assert values[1] > values[0]
    assert values[2] > values[1]


def test_tools_linreg_uses_single_pass_rust_state():
    from tools.data.types import DataColumn
    from tools.factors.expr.leaf import ColumnRef as ToolColumnRef
    from tools.factors.expr.streaming.incremental import compile_incremental_factor

    expression = ToolColumnRef(DataColumn.CLOSE).rolling(3).linreg_slope()
    executor = compile_incremental_factor('slope', expression, ('A',))
    assert getattr(executor._multi, 'uses_rust', False) is True
    for timestamp, value in zip(
        pd.date_range('2026-01-05 09:30', periods=4, freq='min'), (1.0, 2.0, 3.0, 4.0),
    ):
        executor.on_bar(timestamp, {'A': {DataColumn.CLOSE.name: value}})
    assert executor.on_signal(pd.Timestamp('2026-01-05 09:33'))['A'] == 1.0


def test_tools_incremental_facade_uses_global_cse():
    from tools.data.types import DataColumn
    from tools.factors.expr.leaf import ColumnRef as ToolColumnRef
    from tools.factors.expr.streaming.incremental import compile_incremental_factors

    close = ToolColumnRef(DataColumn.CLOSE)
    expression = close.rolling(2).mean()
    executor = compile_incremental_factors({'a': expression, 'b': expression}, ('A',))
    assert executor.node_count == 2


def test_batch_and_incremental_cross_rank_ties_reconcile():
    from alpha.factor import IncrementalFactorPlan

    index = pd.date_range('2026-01-05 09:30', periods=2, freq='min')
    frames = {
        'A': pd.DataFrame({'CLOSE': [1.0, 3.0]}, index=index),
        'B': pd.DataFrame({'CLOSE': [1.0, 5.0]}, index=index),
    }
    expression = ColumnRef('CLOSE').cs_rank()
    batch = expression.evaluate(EvalContext(products=('A', 'B'), preloaded=frames))
    incremental = IncrementalFactorPlan({'r': expression}, ('A', 'B'))
    assert incremental.update([1.0, 1.0]) == {'r': {'A': 0.25, 'B': 0.25}}
    np.testing.assert_allclose(batch.iloc[0].to_numpy(), [0.25, 0.25])


def test_alpha_factor_category_bool_leaf_evaluates_publicly():
    from alpha.factor import CategoryBoolRef, plan_blockers

    class Category:
        alias = 'Sector'
        categories = ('metal',)

        def is_in_category(self, label, product):
            return label == 'metal' and product == 'A'

    index = pd.date_range('2026-01-05', periods=2, freq='min')
    ctx = EvalContext(
        products=('A', 'B'),
        preloaded={
            'A': pd.DataFrame({'CLOSE': [1.0, 2.0]}, index=index),
            'B': pd.DataFrame({'CLOSE': [3.0, 4.0]}, index=index),
        },
    )
    result = CategoryBoolRef(Category(), 'metal').evaluate(ctx)
    np.testing.assert_array_equal(result['A'].to_numpy(), [True, True])
    np.testing.assert_array_equal(result['B'].to_numpy(), [False, False])
    assert 'CategoryBoolRef' in plan_blockers(CategoryBoolRef(Category(), 'metal'))


def test_alpha_factor_unary_pointwise_compiles_to_rust():
    import json
    from alpha import FactorPlanState

    expression = ColumnRef('CLOSE').abs() + ColumnRef('CLOSE').sign()
    spec = expression.to_plan_spec()
    assert [node['kind'] for node in spec['nodes']] == ['column', 'unary', 'unary', 'binary']
    state = FactorPlanState(json.dumps(spec), 1)
    assert float(state.update(np.array([-3.0]))[0]) == 2.0


def test_tools_window_bars_compiles_to_rust():
    from tools.data.types import DataColumn
    from tools.factors import window_bars
    from tools.factors.expr.leaf import ColumnRef as ToolColumnRef
    from tools.factors.expr.streaming.incremental import compile_incremental_factor

    from tools.data.types import DataFreq
    expression = ToolColumnRef(DataColumn.CLOSE).rolling(window_bars(5)).mean()
    executor = compile_incremental_factor('m', expression, ('A',), source_freq=DataFreq.MIN1)
    assert getattr(executor._multi, 'uses_rust', False) is True


def test_window_bars_250d_compiles_to_rust_session_window():
    from tools.data.types import DataColumn, DataFreq
    from tools.factors import window_bars
    from tools.factors.expr.leaf import ColumnRef as ToolColumnRef
    from tools.factors.expr.streaming.calendar_window import (
        TradingCalendarWindow, TradingSession as ToolsSession,
    )
    from tools.factors.expr.streaming.incremental import compile_incremental_factor

    calendar = TradingCalendarWindow((
        ToolsSession('2026-01-05', 0, 10, 2),
        ToolsSession('2026-01-06', 20, 30, 2),
    ))
    expression = ToolColumnRef(DataColumn.CLOSE).rolling(window_bars('250d')).mean()
    executor = compile_incremental_factor(
        'm', expression, ('A',), source_freq=DataFreq.MIN1, session_calendar=calendar,
    )
    assert getattr(executor._multi, 'uses_rust', False) is True


def test_alpha_factor_category_bool_compiles_to_rust_product_node():
    from alpha.factor import CategoryBoolRef, IncrementalFactorPlan

    class Category:
        alias = 'Sector'
        categories = ('metal',)
        def is_in_category(self, label, product):
            return product == 'A'

    plan = IncrementalFactorPlan({'metal': CategoryBoolRef(Category(), 'metal')}, ('A', 'B'))
    assert plan.update([0.0, 0.0]) == {'metal': {'A': 1.0, 'B': 0.0}}


def test_batch_and_incremental_shift_where_since_reconcile():
    from alpha.factor import IncrementalFactorPlan

    index = pd.date_range('2026-01-05 09:30', periods=5, freq='min')
    frames = {
        'A': pd.DataFrame({'CLOSE': [1.0, 2.0, 3.0, 4.0, 5.0]}, index=index),
        'B': pd.DataFrame({'CLOSE': [-1.0, -2.0, -3.0, -4.0, -5.0]}, index=index),
    }
    ctx = EvalContext(products=('A', 'B'), preloaded=frames)
    expressions = {
        'shift': ColumnRef('CLOSE').shift(1),
        'where': ColumnRef('CLOSE').where(ColumnRef('CLOSE') > 0, 0.0),
        'since': __import__('alpha.factor', fromlist=['bar_since']).bar_since(
            ColumnRef('CLOSE') > 0, scope=__import__('alpha.factor', fromlist=['scope_bars']).scope_bars(3),
            default=3.0,
        ),
    }
    plan = IncrementalFactorPlan(expressions, ('A', 'B'))
    for row, timestamp in enumerate(index):
        increment = plan.update([frames[p]['CLOSE'].iloc[row] for p in ('A', 'B')])
        for alias, expression in expressions.items():
            batch = expression.evaluate(ctx).iloc[row]
            np.testing.assert_allclose(
                [increment[alias]['A'], increment[alias]['B']],
                [batch['A'], batch['B']], equal_nan=True, err_msg=alias,
            )


def test_alpha_factor_term_structure_public_leaf():
    import pandas as pd
    from alpha.factor import plan_blockers, term_spread

    index = pd.date_range('2026-01-05', periods=2, freq='min')
    curve = pd.DataFrame({
        'TERM_RANK': [0, 1],
        'DAYS_TO_MATURITY': [30, 90],
        'CLOSE': [10.0, 8.0],
    })
    ctx = EvalContext(
        products=('A',),
        preloaded={'A': pd.DataFrame({'CLOSE': [1.0, 2.0]}, index=index)},
        term_curves={'A': curve},
    )
    expression = term_spread()
    np.testing.assert_allclose(expression.evaluate(ctx)['A'].to_numpy(), [2.0, 2.0])
    assert 'TermStructureExpr' in plan_blockers(expression)


def test_lightweight_category_and_term_inputs_without_product_objects():
    from alpha.factor import CategoryBoolRef, TermCurve, TermPoint, term_spread

    index = pd.date_range('2026-01-05', periods=1, freq='min')
    ctx = EvalContext(
        products=('A', 'B'),
        preloaded={
            'A': pd.DataFrame({'CLOSE': [1.0]}, index=index),
            'B': pd.DataFrame({'CLOSE': [2.0]}, index=index),
        },
        categories={'A': frozenset({'metal'}), 'B': frozenset()},
        term_curves={
            'A': TermCurve('A', (
                TermPoint({'CLOSE': 10.0}, days_to_maturity=30, rank=0),
                TermPoint({'CLOSE': 8.0}, days_to_maturity=90, rank=1),
            )),
            'B': TermCurve('B', ()),
        },
    )
    category = CategoryBoolRef(label='metal').evaluate(ctx)
    np.testing.assert_array_equal(category['A'].to_numpy(), [True])
    np.testing.assert_array_equal(category['B'].to_numpy(), [False])
    spread = term_spread().evaluate(ctx)
    assert spread['A'].iloc[0] == 2.0
    assert np.isnan(spread['B'].iloc[0])

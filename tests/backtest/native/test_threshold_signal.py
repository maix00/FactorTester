from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.target import TargetStrategyModule
from tools.testers.backtest.modules.threshold_signal import (
    ThresholdSignalModule,
    _precompute_threshold_target_intents,
    _threshold_signal_target,
)


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def _state_and_ctx(strategy: Strategy, field_values: dict, signal_value: dict) -> tuple[BacktestRunState, FlowContext]:
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"threshold_signal_target"}),
        field_values={
            TargetStrategyModule.strategy_kind: "threshold",
            **field_values,
        },
    )
    state = BacktestRunState(strategy_configs={strategy: config})
    ctx = FlowContext(
        timestamp=None,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
        event_kind=EventKind.SIGNAL,
    )
    ctx.set_for(FactorSignalModule.signal_value, strategy, signal_value)
    return state, ctx


def test_long_only_absolute_threshold_selects_products_above_entry_threshold() -> None:
    strategy = Strategy(alias="threshold")
    products = [_product() for _ in range(3)]
    state, ctx = _state_and_ctx(
        strategy,
        {
            ThresholdSignalModule.threshold_mode: "absolute",
            ThresholdSignalModule.entry_threshold: 0.5,
            ThresholdSignalModule.exit_threshold: 0.2,
            ThresholdSignalModule.side_mode: "long_only",
        },
        {products[0]: 0.1, products[1]: 0.7, products[2]: 1.2},
    )

    _threshold_signal_target(state, ctx)

    weights = ctx.get_for(ThresholdSignalModule.target_weights, strategy)
    assert set(weights) == {products[1], products[2]}
    assert weights[products[1]] == pytest.approx(0.5)
    assert weights[products[2]] == pytest.approx(0.5)


def test_exit_threshold_keeps_existing_member_until_hysteresis_breaks() -> None:
    strategy = Strategy(alias="threshold")
    product = _product()
    state, ctx1 = _state_and_ctx(
        strategy,
        {
            ThresholdSignalModule.threshold_mode: "absolute",
            ThresholdSignalModule.entry_threshold: 0.7,
            ThresholdSignalModule.exit_threshold: 0.3,
            ThresholdSignalModule.side_mode: "long_only",
        },
        {product: 0.8},
    )

    _threshold_signal_target(state, ctx1)
    assert set(ctx1.get_for(ThresholdSignalModule.target_weights, strategy)) == {product}

    ctx2 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}))
    ctx2.set_for(FactorSignalModule.signal_value, strategy, {product: 0.5})
    _threshold_signal_target(state, ctx2)
    assert set(ctx2.get_for(ThresholdSignalModule.target_weights, strategy)) == {product}

    ctx3 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}))
    ctx3.set_for(FactorSignalModule.signal_value, strategy, {product: 0.2})
    _threshold_signal_target(state, ctx3)
    assert ctx3.get_for(ThresholdSignalModule.target_weights, strategy) == {}


def test_entry_and_exit_factor_roles_drive_separate_state_transitions() -> None:
    strategy = Strategy(alias="threshold")
    product = _product()
    state, ctx1 = _state_and_ctx(
        strategy,
        {
            ThresholdSignalModule.threshold_mode: "absolute",
            ThresholdSignalModule.entry_threshold: 0.7,
            ThresholdSignalModule.exit_threshold: 0.3,
            ThresholdSignalModule.side_mode: "long_only",
        },
        {product: -10.0},
    )
    ctx1.set_for(FactorModule.factor_role_values, strategy, {
        "entry": {product: 0.8},
        "exit": {product: 0.8},
    })
    _threshold_signal_target(state, ctx1)
    assert set(ctx1.get_for(ThresholdSignalModule.target_weights, strategy)) == {product}

    ctx2 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}))
    ctx2.set_for(FactorSignalModule.signal_value, strategy, {product: -10.0})
    ctx2.set_for(FactorModule.factor_role_values, strategy, {
        "entry": {product: 0.1},
        "exit": {product: 0.5},
    })
    _threshold_signal_target(state, ctx2)
    assert set(ctx2.get_for(ThresholdSignalModule.target_weights, strategy)) == {product}

    ctx3 = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}))
    ctx3.set_for(FactorSignalModule.signal_value, strategy, {product: 10.0})
    ctx3.set_for(FactorModule.factor_role_values, strategy, {
        "entry": {product: 0.1},
        "exit": {product: 0.2},
    })
    _threshold_signal_target(state, ctx3)
    assert ctx3.get_for(ThresholdSignalModule.target_weights, strategy) == {}


def test_threshold_policy_rejects_group_only_factor_role() -> None:
    strategy = Strategy(alias="invalid-role")
    state, ctx = _state_and_ctx(
        strategy,
        {FactorModule.factor_role_bindings: {"ranking": object()}},
        {},
    )

    with pytest.raises(ValueError, match="incompatible with threshold"):
        _threshold_signal_target(state, ctx)


def test_precomputed_factor_roles_match_ordered_event_state_machine() -> None:
    strategy = Strategy(alias="threshold")
    product = _product()
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    fields = {
        TargetStrategyModule.strategy_kind: "threshold",
        ThresholdSignalModule.threshold_mode: "absolute",
        ThresholdSignalModule.entry_threshold: 0.7,
        ThresholdSignalModule.exit_threshold: 0.3,
        ThresholdSignalModule.side_mode: "long_only",
    }
    config = StrategyConfig(strategy=strategy, field_values=fields)
    precomputed = BacktestRunState(strategy_configs={strategy: config})
    precomputed.market_data_store.current_prices_table = pd.DataFrame({product: [10.0] * 3}, index=idx)
    tables = {
        "primary": pd.DataFrame({product: [-10.0] * 3}, index=idx),
        "entry": pd.DataFrame({product: [0.8, 0.1, 0.1]}, index=idx),
        "exit": pd.DataFrame({product: [0.8, 0.5, 0.2]}, index=idx),
    }
    for key, table in tables.items():
        precomputed.factor_signal_store.put_precomputed_table(key, table)
    precomputed.factor_signal_store.bind_precomputed_table(strategy, "primary")
    precomputed.factor_signal_store.bind_precomputed_role_table(strategy, "entry", "entry")
    precomputed.factor_signal_store.bind_precomputed_role_table(strategy, "exit", "exit")

    _precompute_threshold_target_intents(precomputed, [strategy])

    event = BacktestRunState(strategy_configs={strategy: config})
    event_weights = []
    event_reasons = []
    for position, timestamp in enumerate(idx):
        ctx = FlowContext(timestamp=timestamp, event_queue=EventQueue(), active_strategies=frozenset({strategy}))
        ctx.set_for(FactorSignalModule.signal_value, strategy, {product: -10.0})
        ctx.set_for(FactorModule.factor_role_values, strategy, {
            "entry": {product: tables["entry"].iloc[position, 0]},
            "exit": {product: tables["exit"].iloc[position, 0]},
        })
        _threshold_signal_target(event, ctx)
        event_weights.append(ctx.get_for(ThresholdSignalModule.target_weights, strategy))
        event_reasons.append(ctx.get_for(TargetStrategyModule.trade_intent, strategy).reason)

    compiled = precomputed.target_store.precomputed_target_intents[strategy]
    assert [compiled[timestamp].weights for timestamp in idx] == event_weights
    assert [compiled[timestamp].reason for timestamp in idx] == event_reasons
    assert event_weights == [{product: 1.0}, {product: 1.0}, {}]
    assert event_reasons == ["threshold_entry", "threshold_hold", "threshold_exit"]


def test_missing_bound_entry_cannot_enter_and_missing_exit_closes() -> None:
    strategy = Strategy(alias="threshold")
    product = _product()
    state, first = _state_and_ctx(
        strategy,
        {
            ThresholdSignalModule.entry_threshold: 0.7,
            ThresholdSignalModule.exit_threshold: 0.3,
        },
        {product: 10.0},
    )
    first.set_for(FactorModule.factor_role_values, strategy, {"entry": {}, "exit": {product: 1.0}})
    _threshold_signal_target(state, first)
    assert first.get_for(ThresholdSignalModule.target_weights, strategy) == {}

    first.set_for(FactorModule.factor_role_values, strategy, {
        "entry": {product: 1.0}, "exit": {product: 1.0},
    })
    _threshold_signal_target(state, first)
    assert set(first.get_for(ThresholdSignalModule.target_weights, strategy)) == {product}

    missing_exit = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}))
    missing_exit.set_for(FactorSignalModule.signal_value, strategy, {product: 10.0})
    missing_exit.set_for(FactorModule.factor_role_values, strategy, {"entry": {}, "exit": {}})
    _threshold_signal_target(state, missing_exit)
    assert missing_exit.get_for(ThresholdSignalModule.target_weights, strategy) == {}


def test_future_role_values_cannot_change_past_compiled_intents() -> None:
    strategy = Strategy(alias="threshold")
    product = _product()
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    config = StrategyConfig(strategy=strategy, field_values={
        ThresholdSignalModule.entry_threshold: 0.7,
        ThresholdSignalModule.exit_threshold: 0.3,
    })

    def compile_with_future(future_entry: float):
        state = BacktestRunState(strategy_configs={strategy: config})
        state.market_data_store.current_prices_table = pd.DataFrame({product: [10.0] * 3}, index=idx)
        tables = {
            "primary": pd.DataFrame({product: [0.0] * 3}, index=idx),
            "entry": pd.DataFrame({product: [0.8, 0.1, future_entry]}, index=idx),
            "exit": pd.DataFrame({product: [0.8, 0.5, 0.2]}, index=idx),
        }
        for key, table in tables.items():
            state.factor_signal_store.put_precomputed_table(key, table)
        state.factor_signal_store.bind_precomputed_table(strategy, "primary")
        state.factor_signal_store.bind_precomputed_role_table(strategy, "entry", "entry")
        state.factor_signal_store.bind_precomputed_role_table(strategy, "exit", "exit")
        _precompute_threshold_target_intents(state, [strategy])
        return state.target_store.precomputed_target_intents[strategy]

    baseline = compile_with_future(0.1)
    perturbed = compile_with_future(10.0)

    assert [(baseline[ts].weights, baseline[ts].reason) for ts in idx[:2]] == [
        (perturbed[ts].weights, perturbed[ts].reason) for ts in idx[:2]
    ]


def test_cross_section_quantile_selects_top_and_bottom_from_same_batch() -> None:
    strategy = Strategy(alias="threshold")
    products = [_product() for _ in range(5)]
    state, ctx = _state_and_ctx(
        strategy,
        {
            ThresholdSignalModule.threshold_mode: "cross_section_quantile",
            ThresholdSignalModule.quantile_entry: 0.8,
            ThresholdSignalModule.quantile_exit: 0.6,
            ThresholdSignalModule.side_mode: "long_short_spread",
        },
        {product: float(i) for i, product in enumerate(products)},
    )

    _threshold_signal_target(state, ctx)

    weights = ctx.get_for(ThresholdSignalModule.target_weights, strategy)
    assert weights == {
        products[0]: pytest.approx(-0.5),
        products[4]: pytest.approx(0.5),
    }

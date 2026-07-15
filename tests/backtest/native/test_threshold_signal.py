from __future__ import annotations

import uuid

import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.target import TargetStrategyModule
from tools.testers.backtest.modules.threshold_signal import ThresholdSignalModule, _threshold_signal_target


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

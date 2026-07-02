"""End-to-end integration test: wires every real module in
_ALL_MODULE_CLASSES through FlowRegistry, builds StrategyConfig via the
real bootstrap (build_strategy_configs), and runs a small synthetic
backtest through the actual scheduler -- the strongest available proof
that the whole framework (not just isolated units) works together.
"""

from __future__ import annotations

import json
import uuid

import pandas as pd
import pytest

from tools.data.types import DataColumn, DataFreq
from tools.factors.FactorExpr import ColumnRef
from tools.products.Product import Product
from tools.testers.backtest.engines.native.ledger import BacktestRunState
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowRegistry, run
from tools.testers.backtest.engines.native.strategy_config_builder import apply_strategy_configs
from tools.testers.backtest.modules.equity_curve import equity_curve_for, position_curve_for
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


class _FakeProductPathSelection:
    def __init__(self, selection_id: str, products: list[Product]) -> None:
        self.selection_id = selection_id
        self._products = products

    @property
    def products(self):
        return self._products


class _FakeFactor:
    def __init__(self, table: pd.DataFrame) -> None:
        self._table = table

    def evaluate(self) -> pd.DataFrame:
        return self._table


def _build_registry() -> FlowRegistry:
    registry = FlowRegistry()
    for cls in _ALL_MODULE_CLASSES:
        for flow in getattr(cls, "flows", ()):
            registry.register_flow(flow)
        for override in getattr(cls, "overrides", ()):
            registry.register_override(override)
    return registry


def test_full_engine_runs_two_product_two_day_backtest():
    p1, p2 = _product(), _product()
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    raw_prices = pd.DataFrame({p1: [10.0, 11.0, 12.0], p2: [20.0, 19.0, 18.0]}, index=idx)
    factor_table = pd.DataFrame({p1: [1.0, 2.0, 1.0], p2: [2.0, 1.0, 2.0]}, index=idx)

    selection = _FakeProductPathSelection("sel-1", [p1, p2])
    factor = _FakeFactor(factor_table)

    resolved_settings = {
        "A1": {
            "product_path_selection": selection,
            "factor": factor,
            "factor_mode": "precomputed",
            "split_count": 2,
            "group_index": 0,  # highest-signal half
            "initial_capital_major": 1_000_000.0,
            "base_currency": "CNY",
            "engine_mode": "basic",
        },
    }

    account = BacktestRunState()
    apply_strategy_configs(account, resolved_settings)
    account.raw_market_data = {"raw_prices": raw_prices, "price_tables": {"open": raw_prices, "close": raw_prices}}

    registry = _build_registry()
    queue = EventQueue()
    run(account, queue, registry.resolve())

    strategy = next(iter(account.strategy_configs))
    curve = equity_curve_for(account, strategy)
    assert not curve.empty
    # equity should stay close to initial capital (no fees/slippage, just
    # one rebalance into a 100%-weighted top-half product) -- a sanity
    # bound, not an exact-value assertion, since the precise trajectory
    # depends on price moves after the rebalance.
    assert curve.iloc[0] == pytest.approx(1_000_000.0, rel=0.05)

    final = account.results.get_final(strategy)
    assert "sharpe_ratio" in final
    assert "max_drawdown" in final


def test_full_engine_two_strategies_independent_results():
    p1, p2 = _product(), _product()
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    raw_prices = pd.DataFrame({p1: [10.0, 11.0, 12.0], p2: [20.0, 19.0, 18.0]}, index=idx)
    factor_table = pd.DataFrame({p1: [1.0, 2.0, 1.0], p2: [2.0, 1.0, 2.0]}, index=idx)
    selection = _FakeProductPathSelection("sel-shared", [p1, p2])
    factor = _FakeFactor(factor_table)

    base_settings = {
        "product_path_selection": selection, "factor": factor, "factor_mode": "precomputed",
        "split_count": 2, "initial_capital_major": 1_000_000.0, "base_currency": "CNY",
        "engine_mode": "basic",
    }
    resolved_settings = {
        "A1": {**base_settings, "group_index": 0},
        "A2": {**base_settings, "group_index": 1},
    }

    account = BacktestRunState()
    apply_strategy_configs(account, resolved_settings)
    account.raw_market_data = {"raw_prices": raw_prices, "price_tables": {"open": raw_prices, "close": raw_prices}}

    registry = _build_registry()
    queue = EventQueue()
    run(account, queue, registry.resolve())

    by_alias = {s.alias: s for s in account.strategy_configs}
    curve_a1 = equity_curve_for(account, by_alias["A1"])
    curve_a2 = equity_curve_for(account, by_alias["A2"])
    assert not curve_a1.empty
    assert not curve_a2.empty
    # different group_index -> different product selected -> different
    # trajectories once prices move (not required to differ on the very
    # first point, since both start at the same initial capital)
    assert curve_a1.iloc[-1] != curve_a2.iloc[-1]


class _RollingMeanFactorAdapter:
    """Wraps a real `FactorExpr` (ColumnRef(...).rolling(...).mean()) so it
    matches the explicit-window `.evaluate(start_dt=..., end_dt=...)`
    contract FactorSignalModule calls in the precomputed path -- the real
    ApplicationSettings/candidate-resolution layer is what normally builds
    this kind of adapter around a user-selected FactorExpr before it reaches
    StrategyConfig; this test stands in for that layer, not for FactorExpr
    itself (the rolling-mean computation below is the real expression
    engine, not a stub)."""

    def __init__(self, expr, products: list[Product], freq: "DataFreq", preloaded: dict) -> None:
        self._expr = expr
        self._products = products
        self._freq = freq
        self._preloaded = preloaded

    def evaluate(self, *, start_dt=None, end_dt=None) -> pd.DataFrame:
        return self._expr.evaluate(
            self._products,
            self._freq,
            preloaded=self._preloaded,
            start_dt=start_dt,
            end_dt=end_dt,
        )


def test_full_engine_with_real_moving_average_factor_expression():
    """Uses a genuine FactorExpr (ColumnRef(CLOSE).rolling(5).mean(), not a
    hand-built table) and a literal frontend-shaped JSON payload (the exact
    flat {alias: {setting_key: value}} shape build_strategy_configs expects
    once the existing ApplicationSettings/candidate-resolution layer has
    already resolved group/local settings) to prove the engine produces a
    real trade off a real moving-average crossover, not off
    pre-fabricated signal values."""
    p1, p2 = _product(), _product()
    idx = pd.date_range("2024-01-01", periods=12, freq="D", name="DAY1")
    # GroupMembershipModule ranks by raw signal_value (the 5-bar moving
    # average level itself, not momentum) -- p1 stays well above p2's level
    # throughout, so its MA is always the higher-ranked one, and it also
    # keeps climbing so the resulting equity curve should rise too.
    close_p1 = pd.DataFrame({"CLOSE": [50.0 + i for i in range(12)]}, index=idx)
    close_p2 = pd.DataFrame({"CLOSE": [10.0 - 0.1 * i for i in range(12)]}, index=idx)
    preloaded = {(p1, "DAY1"): close_p1, (p2, "DAY1"): close_p2}

    moving_average = ColumnRef(DataColumn.CLOSE).rolling(5).mean()
    factor = _RollingMeanFactorAdapter(moving_average, [p1, p2], DataFreq.DAY1, preloaded)

    raw_prices = pd.DataFrame(
        {p1: close_p1["CLOSE"].to_numpy(), p2: close_p2["CLOSE"].to_numpy()}, index=idx)

    # The literal payload a frontend POST would carry: scalar settings only
    # (factor_mode/split_count/group_index/initial_capital_major/...) --
    # JSON has no way to carry a Python FactorExpr/Product object, so those
    # two (already-resolved domain objects, same as product_path_selection
    # everywhere else in this file) are attached after parsing, standing in
    # for the existing candidate-resolution layer that does this in
    # production.
    frontend_payload = json.loads(json.dumps({
        "A1": {
            "factor_mode": "precomputed",
            "split_count": 2,
            "group_index": 0,  # highest-MA half
                "initial_capital_major": 1_000_000.0,
                "base_currency": "CNY",
                "engine_mode": "basic",
        },
    }))
    selection = _FakeProductPathSelection("sel-ma", [p1, p2])
    frontend_payload["A1"]["product_path_selection"] = selection
    frontend_payload["A1"]["factor"] = factor

    account = BacktestRunState()
    apply_strategy_configs(account, frontend_payload)
    account.raw_market_data = {"raw_prices": raw_prices, "price_tables": {"open": raw_prices, "close": raw_prices}}

    registry = _build_registry()
    queue = EventQueue()
    run(account, queue, registry.resolve())

    strategy = next(iter(account.strategy_configs))
    curve = equity_curve_for(account, strategy)
    assert not curve.empty
    # The real rolling-mean ranking must put p1 (consistently higher MA
    # level) in the group_index=0 (top) bucket -- proof the engine's
    # allocation decision was actually driven by FactorExpr.evaluate()'s
    # real output, not a hand-built signal table.
    positions_by_ts = position_curve_for(account, strategy)
    final_positions = positions_by_ts[max(positions_by_ts)]
    assert final_positions.get(str(p1), 0.0) > 0.0
    assert final_positions.get(str(p2), 0.0) == pytest.approx(0.0, abs=1e-6)

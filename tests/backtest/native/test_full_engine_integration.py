"""End-to-end integration test: wires every real module in
_ALL_MODULE_CLASSES through FlowRegistry, builds StrategyConfig via the
real bootstrap (build_strategy_configs), and runs a small synthetic
backtest through the actual scheduler -- the strongest available proof
that the whole framework (not just isolated units) works together.
"""

from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.ledger import AccountState
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowRegistry, run
from tools.testers.backtest.engines.native.strategy_config_builder import apply_strategy_configs
from tools.testers.backtest.modules.equity_curve import equity_curve_for
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
            "group_index": 1,  # highest-signal half
            "initial_capital_major": 1_000_000.0,
            "base_currency": "CNY",
            "accounting_mode": "Basic",
        },
    }

    account = AccountState()
    apply_strategy_configs(account, resolved_settings)
    account.raw_market_data = {"raw_prices": raw_prices}

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
        "accounting_mode": "Basic",
    }
    resolved_settings = {
        "A1": {**base_settings, "group_index": 0},
        "A2": {**base_settings, "group_index": 1},
    }

    account = AccountState()
    apply_strategy_configs(account, resolved_settings)
    account.raw_market_data = {"raw_prices": raw_prices}

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

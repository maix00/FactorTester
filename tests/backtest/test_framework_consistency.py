"""Native engine vs framework-worker replay consistency (ADR-030 §8).

Drives the SAME resolved settings + market data + factor through:
  (a) the native Event/Order/Flow engine (`run()`), and
  (b) the framework bridge with an in-process worker that executes the
      framework-free reference replay (`runners/reference.py` — the exact
      loop the backtrader/zipline workers delegate to).

This is the control-variable equivalence gate: any behavioral drift between
native replay semantics and worker replay semantics fails here without
needing conda framework environments. Framework-specific engines (real
backtrader/qlib/zipline processes) are additionally covered by
test_framework_workers.py where those environments exist.
"""

from __future__ import annotations

import uuid
from typing import Any

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.ledger import BacktestRunState
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowRegistry, run
from tools.testers.backtest.engines.native.strategy_config_builder import apply_strategy_configs
from tools.testers.backtest.engines.workers.bridge import run_framework_backtest_task
from tools.testers.backtest.engines.workers.contracts import WorkerResponse
from tools.testers.backtest.engines.workers.runners.reference import (
    run_group_strategy as reference_run_group_strategy,
)
from tools.testers.backtest.modules.equity_curve import equity_curve_for, position_curve_for
from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES


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


class _InProcessReferenceDispatcher:
    """Executes the reference replay in-process instead of a conda worker."""

    def __init__(self):
        self.request = None

    def dispatch(self, request, *, timeout_seconds=0.0, progress=None, cancel_event=None):
        self.request = request

        def _progress(completed, total, timestamp):
            if progress is not None:
                progress({
                    "completed": completed, "total": total,
                    "event_timestamp": timestamp.isoformat(),
                })

        result = reference_run_group_strategy(request.payload, _progress, engine=request.engine)
        return WorkerResponse(request.request_id, request.engine, True, result)


class _State:
    account = None


def _scenario(
    engine: str, products: tuple[Product, Product] | None = None,
) -> tuple[BacktestRunState, dict[str, dict[str, Any]], list[Product]]:
    if products is None:
        products = (
            Product(name=f"P-{uuid.uuid4().hex[:8]}", point_value=1, currency="CNY"),
            Product(name=f"Q-{uuid.uuid4().hex[:8]}", point_value=1, currency="CNY"),
        )
    p1, p2 = products
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    raw_prices = pd.DataFrame({p1: [10.0, 11.0, 12.0, 13.0], p2: [20.0, 19.0, 18.0, 17.0]}, index=idx)
    factor_table = pd.DataFrame({p1: [1.0, 2.0, 1.0, 2.0], p2: [2.0, 1.0, 2.0, 1.0]}, index=idx)

    settings = {
        "G1": {
            "product_path_selection": _FakeProductPathSelection("sel-1", [p1, p2]),
            "factor": _FakeFactor(factor_table),
            "factor_mode": "precomputed",
            "split_count": 2,
            "group_index": 1,
            "allocation_policy": "equal_notional",
            "initial_capital_major": 1_000_000.0,
            "base_currency": "CNY",
            "engine_mode": "basic",
            "engine": engine,
        },
    }
    run_state = BacktestRunState()
    apply_strategy_configs(run_state, settings)
    run_state.raw_market_data = {
        "raw_prices": raw_prices,
        "price_tables": {"open": raw_prices, "close": raw_prices},
        # whole-contract trading on both sides: native PositionSizingModule
        # floors to this lot; the translator carries the same values into the
        # worker payload's lot_sizes matrix (workers cannot express fractional
        # contracts — their target_quantities always floors to lot).
        "lot_sizes": {p1: 1.0, p2: 1.0},
    }
    return run_state, settings, [p1, p2]


def _native_curves(products=None) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    run_state, _, _ = _scenario("native", products)
    registry = FlowRegistry()
    for cls in _ALL_MODULE_CLASSES:
        for flow in getattr(cls, "flows", ()):
            registry.register_flow(flow)
        for override in getattr(cls, "overrides", ()):
            registry.register_override(override)
    run(run_state, EventQueue(), registry.resolve())
    strategy = next(iter(run_state.strategy_configs))
    equity = {
        pd.Timestamp(ts).isoformat(): float(value)
        for ts, value in equity_curve_for(run_state, strategy).items()
    }
    positions = position_curve_for(run_state, strategy)
    return equity, positions


def _bridge_curves(
    engine: str = "backtrader", products=None,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    run_state, settings, _ = _scenario(engine, products)
    execution = run_framework_backtest_task(
        _State(),
        run_state=run_state,
        engine=engine,
        group_owner=[{"group_id": "G1"}],
        settings_by_strategy=settings,
        run_id="consistency-run",
        dispatcher=_InProcessReferenceDispatcher(),
    )
    portfolio = execution["engine_result"]["portfolios"]["G1"]
    return dict(portfolio["equity_curve"]), dict(portfolio["position_curve"])


def _shared_products() -> tuple[Product, Product]:
    return (
        Product(name=f"P-{uuid.uuid4().hex[:8]}", point_value=1, currency="CNY"),
        Product(name=f"Q-{uuid.uuid4().hex[:8]}", point_value=1, currency="CNY"),
    )


def test_native_and_worker_replay_agree_on_equity_curve():
    products = _shared_products()
    native_equity, _ = _native_curves(products)
    bridge_equity, _ = _bridge_curves(products=products)

    assert native_equity, "native produced no equity curve"
    assert bridge_equity, "bridge produced no equity curve"
    shared = sorted(set(native_equity) & set(bridge_equity))
    assert shared, (
        f"no shared equity timestamps: native={sorted(native_equity)} "
        f"bridge={sorted(bridge_equity)}"
    )
    for ts in shared:
        assert native_equity[ts] == pytest.approx(bridge_equity[ts], rel=1e-9), (
            f"equity diverges at {ts}: native={native_equity[ts]} bridge={bridge_equity[ts]}"
        )


def test_native_and_worker_replay_agree_on_positions():
    products = _shared_products()
    _, native_positions = _native_curves(products)
    _, bridge_positions = _bridge_curves(products=products)

    shared = sorted(set(native_positions) & set(bridge_positions))
    assert shared
    for ts in shared:
        native_row = {str(k): float(v) for k, v in native_positions[ts].items() if abs(float(v)) > 1e-12}
        bridge_row = {str(k): float(v) for k, v in bridge_positions[ts].items() if abs(float(v)) > 1e-12}
        assert native_row == pytest.approx(bridge_row), (
            f"positions diverge at {ts}: native={native_row} bridge={bridge_row}"
        )

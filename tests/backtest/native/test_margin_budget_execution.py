from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.data.types.data_money import DataMoney
from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.ledger import ledger_identity
from tools.testers.backtest.engines.native.order import Order
from tools.testers.backtest.engines.native.position import ProductPosition
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.cash_pool import set_cash_for_ledger_pool
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.margin_budget import MarginBudgetModule
from tools.testers.backtest.modules.margin_budget_impl.observability import (
    CumulativeMarginExecutionObserver,
)
from tools.testers.backtest.modules.margin_budget_impl.execution import _active_positions
from tools.testers.backtest.modules.market_data import MarketDataModule


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def _case(alias: str, products: list[Product], quantities: list[float], cash: float):
    strategy = Strategy(alias=alias)
    state = BacktestRunState(strategy_configs={strategy: StrategyConfig(strategy=strategy)})
    ledger = state.ledger_for_strategy(strategy)
    state.ledger_configs[ledger_identity(f"private:{alias}")] = LedgerConfig(
        fee_mode="zero", margin_mode="fixed", fixed_margin_ratio=0.10,
    )
    set_cash_for_ledger_pool(state, ledger, DataMoney.from_major(
        cash, currency="CNY", use_minor_units=False,
    ))
    drafts = []
    for product, quantity in zip(products, quantities, strict=True):
        order = Order(
            instrument=product, timestamp=pd.Timestamp("2025-01-02"),
            quantity=quantity, intent_quantity=quantity, strategy=strategy,
        )
        order.set("effective_price", 100.0)
        order.set("fee_cost", 0.0)
        drafts.append(EventDraft(EventKind.ORDER, order.timestamp, strategy, order))
    ctx = FlowContext(
        timestamp=pd.Timestamp("2025-01-02"), event_queue=EventQueue(),
        active_strategies=frozenset({strategy}), drafts_by_strategy={strategy: drafts},
    )
    ctx.set(MarketDataModule.current_prices, {product: 100.0 for product in products})
    ctx.set_for(MarketDataModule.current_historical_fields, strategy, {
        product: {"VolumeMultiple": 1.0} for product in products
    })
    return state, ledger, ctx, [draft.payload for draft in drafts]


def test_execution_hard_limit_scales_only_margin_increasing_quantity() -> None:
    product = _product()
    state, ledger, ctx, orders = _case("limit", [product], [100.0], 1_000.0)
    ledger.set(LedgerModule.positions, {product: ProductPosition(quantity=0.0)})

    MarginBudgetModule.constrain_execution_margin_utilization.compute(state, ctx)

    assert orders[0].quantity == pytest.approx(40.0)
    summary = ctx.get(MarginBudgetModule.execution_margin_summary)["private:limit"]
    assert summary["projected_utilization"] == pytest.approx(0.40)
    assert summary["gross_leverage"] == pytest.approx(4.0)


def test_execution_margin_observer_reports_over_limit_and_stage_breakdown() -> None:
    product = _product()
    state, ledger, ctx, orders = _case("observed", [product], [100.0], 1_000.0)
    ledger.set(LedgerModule.positions, {product: ProductPosition(quantity=0.0)})
    observer = CumulativeMarginExecutionObserver(min_total_ms=0.0)
    state.margin_execution_observer = observer

    MarginBudgetModule.constrain_execution_margin_utilization.compute(state, ctx)
    observer.flush(state)

    rows = [
        row for row in state.runtime_info_rows
        if row.get("code") == "backtest_margin_execution_profile"
    ]
    assert len(rows) == 1
    details = rows[0]["details"]
    assert details["orders_seen"] == 1
    assert details["over_limit_orders"] == 1
    assert details["scaled_orders"] == 1
    assert details["over_limit_order_ratio"] == pytest.approx(1.0)
    assert details["scaled_order_ratio"] == pytest.approx(1.0)
    assert details["projection_calls"] >= 50
    assert details["stage_ms"]["find_scale"] >= 0.0
    assert orders[0].quantity == pytest.approx(40.0)


def test_execution_margin_observer_reports_when_no_order_pool_is_applicable() -> None:
    observer = CumulativeMarginExecutionObserver(min_total_ms=0.0)
    state = BacktestRunState()

    observer.flush(state)

    rows = [
        row for row in state.runtime_info_rows
        if row.get("code") == "backtest_margin_execution_profile"
    ]
    assert len(rows) == 1
    assert rows[0]["status"] == "no_applicable_orders"
    assert rows[0]["details"]["observation_status"] == "no_applicable_orders"
    assert rows[0]["details"]["checks"] == 0


def test_execution_hard_limit_preserves_close_before_scaling_flip() -> None:
    product = _product()
    state, ledger, ctx, orders = _case("flip", [product], [-110.0], 900.0)
    ledger.set(LedgerModule.positions, {product: ProductPosition(
        quantity=10.0, average_cost=100.0,
        margin_reserved=DataMoney.from_major(100.0, currency="CNY", use_minor_units=False),
    )})

    MarginBudgetModule.constrain_execution_margin_utilization.compute(state, ctx)

    assert orders[0].quantity == pytest.approx(-50.0)
    assert abs(orders[0].quantity) >= 10.0


def test_execution_gross_leverage_values_each_ledger_once_for_multiple_orders() -> None:
    products = [_product(), _product()]
    state, ledger, ctx, _orders = _case("multi", products, [1.0, 1.0], 1_000.0)
    ledger.set(LedgerModule.positions, {})

    MarginBudgetModule.constrain_execution_margin_utilization.compute(state, ctx)

    summary = ctx.get(MarginBudgetModule.execution_margin_summary)["private:multi"]
    assert summary["gross_leverage"] == pytest.approx(0.2)


def test_execution_precheck_values_existing_positions_from_causal_close() -> None:
    held = _product()
    order_product = _product()
    state, ledger, ctx, orders = _case("causal-close", [order_product], [1.0], 1_000.0)
    ledger.set(LedgerModule.positions, {
        held: ProductPosition(
            quantity=1.0,
            average_cost=90.0,
            margin_reserved=DataMoney.from_major(
                9.0, currency="CNY", use_minor_units=False,
            ),
        ),
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        held: {"VolumeMultiple": 1.0},
        order_product: {"VolumeMultiple": 1.0},
    })
    # ORDER current_prices is the execution-basis map and intentionally has
    # no row for the already-held product.  Existing equity must use causal
    # close; settlement is present only to prove it is not consulted here.
    ctx.set(MarketDataModule.current_market_snapshot, {
        "close": {held: 100.0, order_product: 100.0},
        "settlement": {held: 999.0, order_product: 999.0},
    })

    MarginBudgetModule.constrain_execution_margin_utilization.compute(state, ctx)

    assert orders[0].quantity == pytest.approx(1.0)
    summary = ctx.get(MarginBudgetModule.execution_margin_summary)["private:causal-close"]
    assert summary["equity"] > 1_000.0
    assert summary["projected_utilization"] < 0.50


def test_execution_projection_drops_zero_position_tombstones() -> None:
    stale = _product()
    live = _product()
    stale_entry = ProductPosition(quantity=0.0)
    live_entry = ProductPosition(quantity=1.0)

    active = _active_positions({stale: stale_entry, live: live_entry})

    assert stale not in active
    assert active[live] is live_entry


def test_execution_projection_keeps_zero_quantity_margin_balance() -> None:
    product = _product()
    entry = ProductPosition(
        quantity=0.0,
        margin_reserved=DataMoney.from_major(
            1.0, currency="CNY", use_minor_units=False,
        ),
    )

    assert _active_positions({product: entry}) == {product: entry}

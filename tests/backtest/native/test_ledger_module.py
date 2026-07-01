from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.data.types.data_money import DataMoney
from tools.products.Product import Product
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import FieldRef
from tools.testers.backtest.engines.native.ledger import BacktestRunState, ProductPosition, StrategyConfig
from tools.testers.backtest.engines.native.order import Order, OrderStatus
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.ledger_module import LedgerModule, _basic_cash_update, _basic_equity, _initialize_ledgers
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.margin import MarginModule
from tools.testers.backtest.modules.trading_rule import TradingRuleModule


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def _strategy_config(strategy, **trading_rule_values) -> StrategyConfig:
    field_values: dict[FieldRef, object] = {
        LedgerModule.initial_capital_major: 1_000_000.0,
        LedgerModule.base_currency: "CNY",
    }
    for key, value in trading_rule_values.items():
        ref = (
            getattr(EngineModule, key, None)
            or getattr(TradingRuleModule, key, None)
            or getattr(MarginModule, key)
        )
        field_values[ref] = value
    return StrategyConfig(strategy=strategy, field_values=field_values)


def test_initialize_ledgers_builds_correct_shape_per_method():
    s1 = Strategy(alias="S1")  # Basic -> WeightAverage
    s2 = Strategy(alias="S2")  # Custom + FIFO
    p1, p2 = _product(), _product()

    configs = {
        s1: _strategy_config(s1, engine_mode="basic"),
        s2: _strategy_config(s2, engine_mode="custom", accounting_mode="Custom", cost_basis_method="FIFO"),
    }
    account = BacktestRunState(strategy_configs=configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s1, frozenset({p1}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({p2}))

    _initialize_ledgers(account, ctx)

    entry1 = account.ledgers[s1].get(LedgerModule.positions)[p1]
    assert entry1.average_cost == 0.0
    assert entry1.lots is None
    assert entry1.equity_occupied.to_major() == 0.0

    entry2 = account.ledgers[s2].get(LedgerModule.positions)[p2]
    assert entry2.average_cost is None
    assert entry2.lots is not None and len(entry2.lots) == 0

    assert account.ledgers[s1].get(LedgerModule.cash).to_major() == pytest.approx(1_000_000.0)


def test_initialize_ledgers_use_int_position_keeps_quantity_as_int():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="custom", accounting_mode="Custom", use_int_position=True)
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)
    entry = account.ledgers[s].get(LedgerModule.positions)[p]
    assert isinstance(entry.quantity, int)
    assert entry.quantity == 0


def test_initialize_ledgers_uses_effective_backtest_product_universe():
    s = Strategy(alias="S")
    in_range, out_of_range = _product(), _product()
    config = _strategy_config(s, engine_mode="basic")
    account = BacktestRunState(strategy_configs={s: config})
    account.market_data_store.included_products = frozenset({in_range})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({in_range, out_of_range}))

    _initialize_ledgers(account, ctx)

    positions = account.ledgers[s].get(LedgerModule.positions)
    assert set(positions) == {in_range}


def test_cash_zeros_after_full_rebalance_with_two_products():
    """Σ target_weights = 1 -> cash should be exactly zero after a full
    rebalance trade batch (algebraic result, not approximation)."""
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    config = _strategy_config(s, engine_mode="basic")
    account = BacktestRunState(strategy_configs={s: config})

    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p1, p2}))
    _initialize_ledgers(account, ctx)

    t = pd.Timestamp("2024-01-01")
    prices = {p1: 10.0, p2: 20.0}
    account.market_data_store.current_prices_table = pd.DataFrame({p1: [10.0], p2: [20.0]}, index=[t])

    # equity = cash = 1_000_000; target weights 0.5/0.5 -> buy
    # quantity[p1] = 0.5*1_000_000/10 = 50_000, quantity[p2] = 0.5*1_000_000/20 = 25_000
    order1 = Order(instrument=p1, timestamp=t, quantity=50_000.0, intent_quantity=50_000.0, strategy=s)
    order2 = Order(instrument=p2, timestamp=t, quantity=25_000.0, intent_quantity=25_000.0, strategy=s)

    draft1 = EventDraft(EventKind.ORDER, t, s, order1)
    draft2 = EventDraft(EventKind.ORDER, t, s, order2)
    order_ctx = FlowContext(
        timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}),
        drafts_by_strategy={s: [draft1]},
    )
    order_ctx.set(MarketDataModule.current_prices, prices)
    _basic_cash_update(account, order_ctx)

    # second order processed in its own batch (same strategy, different
    # product) -- payload_for looks up by strategy, so reuse same pattern
    order_ctx2 = FlowContext(
        timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}),
        drafts_by_strategy={s: [draft2]},
    )
    order_ctx2.set(MarketDataModule.current_prices, prices)
    _basic_cash_update(account, order_ctx2)

    cash = account.ledgers[s].get(LedgerModule.cash)
    assert cash.to_major() == pytest.approx(0.0, abs=1e-6)


def test_equity_on_signal_and_on_order_recompute_after_fill():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="basic")
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    t = pd.Timestamp("2024-01-01")
    prices = {p: 10.0}

    signal_ctx = FlowContext(timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}))
    signal_ctx.set(MarketDataModule.current_prices, prices)
    _basic_equity(account, signal_ctx)
    assert signal_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_000.0)

    order = Order(instrument=p, timestamp=t, quantity=1000.0, intent_quantity=1000.0, strategy=s)
    draft = EventDraft(EventKind.ORDER, t, s, order)
    order_ctx = FlowContext(
        timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}),
        drafts_by_strategy={s: [draft]},
    )
    order_ctx.set(MarketDataModule.current_prices, prices)
    _basic_cash_update(account, order_ctx)
    _basic_equity(account, order_ctx)

    # equity unchanged by a fair-price trade (bought 1000 @ 10 = 10_000 cash
    # out, +10_000 market value in)
    assert order_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_000.0)
    cash_after = account.ledgers[s].get(LedgerModule.cash).to_major()
    assert cash_after == pytest.approx(1_000_000.0 - 10_000.0)


def test_cash_update_and_equity_use_contract_multiplier():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="basic")
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    t = pd.Timestamp("2024-01-01")
    prices = {p: 10.0}
    historical_fields = {p: {"VolumeMultiple": 10.0}}
    order = Order(instrument=p, timestamp=t, quantity=1000.0, intent_quantity=1000.0, strategy=s)
    draft = EventDraft(EventKind.ORDER, t, s, order)
    order_ctx = FlowContext(
        timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}),
        drafts_by_strategy={s: [draft]},
    )
    order_ctx.set(MarketDataModule.current_prices, prices)
    order_ctx.set(MarketDataModule.current_historical_fields, historical_fields)

    _basic_cash_update(account, order_ctx)
    _basic_equity(account, order_ctx)

    assert account.ledgers[s].get(LedgerModule.cash).to_major() == pytest.approx(900_000.0)
    assert order_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_000.0)


def test_equity_uses_margin_and_floating_pnl_when_margin_is_tracked():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="basic")
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    ledger = account.ledgers[s]
    ledger.set(LedgerModule.cash, DataMoney.from_major(
        990_000.0, currency="CNY", use_minor_units=False))
    ledger.set(LedgerModule.positions, {
        p: ProductPosition(
            quantity=10.0,
            average_cost=100.0,
            equity_occupied=DataMoney.from_major(
                1_000.0, currency="CNY", use_minor_units=False),
        )
    })

    signal_ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
    )
    signal_ctx.set(MarketDataModule.current_prices, {p: 110.0})
    signal_ctx.set(MarketDataModule.current_historical_fields, {p: {"VolumeMultiple": 2.0}})

    _basic_equity(account, signal_ctx)

    assert signal_ctx.get_for(LedgerModule.equity, s) == pytest.approx(991_200.0)


def test_margin_accounting_cash_update_locks_margin_and_realizes_pnl():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(
        s,
        engine_mode="custom",
        accounting_mode="Custom",
        margin_mode="fixed",
        fixed_margin_ratio=0.1,
    )
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    open_ts = pd.Timestamp("2024-01-01")
    open_order = Order(instrument=p, timestamp=open_ts, quantity=10.0, intent_quantity=10.0, strategy=s)
    open_ctx = FlowContext(
        timestamp=open_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, open_ts, s, open_order)]},
    )
    open_ctx.set(MarketDataModule.current_prices, {p: 100.0})
    open_ctx.set(MarketDataModule.current_historical_fields, {p: {"VolumeMultiple": 2.0}})

    _basic_cash_update(account, open_ctx)
    _basic_equity(account, open_ctx)

    assert account.ledgers[s].get(LedgerModule.cash).to_major() == pytest.approx(999_800.0)
    assert open_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_000.0)

    signal_ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-02"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
    )
    signal_ctx.set(MarketDataModule.current_prices, {p: 110.0})
    signal_ctx.set(MarketDataModule.current_historical_fields, {p: {"VolumeMultiple": 2.0}})
    _basic_equity(account, signal_ctx)
    assert signal_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_200.0)

    close_ts = pd.Timestamp("2024-01-03")
    close_order = Order(instrument=p, timestamp=close_ts, quantity=-10.0, intent_quantity=-10.0, strategy=s)
    close_ctx = FlowContext(
        timestamp=close_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, close_ts, s, close_order)]},
    )
    close_ctx.set(MarketDataModule.current_prices, {p: 110.0})
    close_ctx.set(MarketDataModule.current_historical_fields, {p: {"VolumeMultiple": 2.0}})

    _basic_cash_update(account, close_ctx)
    _basic_equity(account, close_ctx)

    assert account.ledgers[s].get(LedgerModule.cash).to_major() == pytest.approx(1_000_200.0)
    assert close_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_200.0)


def test_two_strategies_independent_ledgers_do_not_cross_contaminate():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")
    p = _product()
    configs = {
        s1: _strategy_config(s1, engine_mode="basic"),
        s2: _strategy_config(s2, engine_mode="basic"),
    }
    account = BacktestRunState(strategy_configs=configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s1, frozenset({p}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({p}))
    _initialize_ledgers(account, ctx)

    t = pd.Timestamp("2024-01-01")
    order1 = Order(instrument=p, timestamp=t, quantity=100.0, intent_quantity=100.0, strategy=s1)
    draft1 = EventDraft(EventKind.ORDER, t, s1, order1)
    order_ctx = FlowContext(
        timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s1}),
        drafts_by_strategy={s1: [draft1]},
    )
    order_ctx.set(MarketDataModule.current_prices, {p: 5.0})
    _basic_cash_update(account, order_ctx)

    assert account.ledgers[s1].get(LedgerModule.positions)[p].quantity == 100.0
    assert account.ledgers[s2].get(LedgerModule.positions)[p].quantity == 0.0
    assert account.ledgers[s2].get(LedgerModule.cash).to_major() == pytest.approx(1_000_000.0)


def test_cancelled_order_has_no_ledger_effect():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="basic")
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    t = pd.Timestamp("2024-01-01")
    order = Order(instrument=p, timestamp=t, quantity=100.0, intent_quantity=100.0,
                  strategy=s, status=OrderStatus.CANCELLED)
    draft = EventDraft(EventKind.ORDER, t, s, order)
    order_ctx = FlowContext(
        timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}),
        drafts_by_strategy={s: [draft]},
    )
    order_ctx.set(MarketDataModule.current_prices, {p: 10.0})
    _basic_cash_update(account, order_ctx)

    assert account.ledgers[s].get(LedgerModule.positions)[p].quantity == 0.0
    assert account.ledgers[s].get(LedgerModule.cash).to_major() == pytest.approx(1_000_000.0)


def test_multiple_simultaneous_orders_for_one_strategy_are_all_applied():
    """Regression: a single dispatch batch can carry several ORDER drafts
    for the SAME strategy (one per product being rebalanced at this
    timestamp). All of them must update the ledger, not just one."""
    s = Strategy(alias="S")
    p1, p2, p3 = _product(), _product(), _product()
    config = _strategy_config(s, engine_mode="basic")
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p1, p2, p3}))
    _initialize_ledgers(account, ctx)

    t = pd.Timestamp("2024-01-01")
    order1 = Order(instrument=p1, timestamp=t, quantity=10.0, intent_quantity=10.0, strategy=s)
    order2 = Order(instrument=p2, timestamp=t, quantity=20.0, intent_quantity=20.0, strategy=s)
    order3 = Order(instrument=p3, timestamp=t, quantity=30.0, intent_quantity=30.0, strategy=s)
    draft1 = EventDraft(EventKind.ORDER, t, s, order1)
    draft2 = EventDraft(EventKind.ORDER, t, s, order2)
    draft3 = EventDraft(EventKind.ORDER, t, s, order3)
    # all three drafts land in ONE dispatch batch for the same strategy --
    # exactly the scenario the old dict[Strategy, EventDraft] shape (one
    # draft per strategy, last-write-wins) would have silently dropped two
    # of these three orders.
    order_ctx = FlowContext(
        timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}),
        drafts_by_strategy={s: [draft1, draft2, draft3]},
    )
    order_ctx.set(MarketDataModule.current_prices, {p1: 1.0, p2: 1.0, p3: 1.0})
    _basic_cash_update(account, order_ctx)

    positions = account.ledgers[s].get(LedgerModule.positions)
    assert positions[p1].quantity == 10.0
    assert positions[p2].quantity == 20.0
    assert positions[p3].quantity == 30.0
    assert account.ledgers[s].get(LedgerModule.cash).to_major() == pytest.approx(1_000_000.0 - 60.0)

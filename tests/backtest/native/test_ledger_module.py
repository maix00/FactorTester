from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.data.types.data_money import DataMoney
from tools.products.Product import Product
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import FieldRef
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.position import ProductPosition
from tools.testers.backtest.engines.native.ledger import ledger_identity
from tools.testers.backtest.engines.native.order import Order, OrderStatus
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules import ledger_module as ledger_module_impl
from tools.testers.backtest.modules.ledger_module import LedgerModule, _apply_order_fill, _basic_equity, _initialize_ledgers
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.margin import MarginModule
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.cash_pool import (
    cash_for_ledger,
    cash_pool_cash_major,
    set_cash_for_ledger_pool,
)
from tools.testers.backtest.modules.strategy_book import (
    StrategyBook,
    StrategyBookModule,
    _apply_ledger_session_policy,
    materialize_strategy_book_store,
    strategy_book_store_for,
)
from tools.testers.backtest.modules.trading_rule import TradingRuleModule


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def _cash(account: BacktestRunState, strategy: Strategy) -> DataMoney:
    cash = cash_for_ledger(account, account.ledger_for_strategy(strategy))
    assert cash is not None
    return cash


def _cash_major(account: BacktestRunState, strategy: Strategy) -> float:
    return _cash(account, strategy).to_major()


def _strategy_config(strategy, **trading_rule_values) -> StrategyConfig:
    field_values: dict[FieldRef, object] = {
        LedgerModule.initial_capital_major: 1_000_000.0,
        LedgerModule.base_currency: "CNY",
    }
    for key, value in trading_rule_values.items():
        ref = (
            getattr(EngineModule, key, None)
            or getattr(StrategyBookModule, key, None)
            or getattr(LedgerModule, key, None)
            or getattr(TradingRuleModule, key, None)
            or getattr(FeeModule, key, None)
            or getattr(MarginModule, key)
        )
        field_values[ref] = value
    return StrategyConfig(strategy=strategy, field_values=field_values)


def _state_with_ledger_configs(configs: dict[Strategy, StrategyConfig]) -> BacktestRunState:
    state = BacktestRunState(strategy_configs=configs)
    for strategy, config in configs.items():
        state.ledger_configs[ledger_identity(f"private:{strategy.alias}")] = LedgerConfig(
            fee_mode=config.get(FeeModule.fee_mode),
            fixed_fee_rate=config.get(FeeModule.fixed_fee_rate),
            margin_mode=config.get(MarginModule.margin_mode),
            fixed_margin_ratio=config.get(MarginModule.fixed_margin_ratio),
            accounting_mode=config.get(TradingRuleModule.accounting_mode),
            daily_mark_to_market_enabled=config.get(TradingRuleModule.daily_mark_to_market_enabled),
            cost_basis_method=config.get(TradingRuleModule.cost_basis_method),
            use_int_position=config.get(TradingRuleModule.use_int_position),
        )
    return state


def test_initialize_ledgers_builds_correct_shape_per_method():
    s1 = Strategy(alias="S1")  # Basic -> WeightAverage
    s2 = Strategy(alias="S2")  # Custom + FIFO
    p1, p2 = _product(), _product()

    configs = {
        s1: _strategy_config(s1, engine_mode="basic"),
        s2: _strategy_config(s2, engine_mode="custom", accounting_mode="Custom", cost_basis_method="FIFO"),
    }
    account = _state_with_ledger_configs(configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s1, frozenset({p1}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({p2}))

    _initialize_ledgers(account, ctx)

    entry1 = account.ledger_for_strategy(s1).get(LedgerModule.positions)[p1]
    assert entry1.average_cost == 0.0
    assert entry1.lots is None
    assert entry1.margin_reserved is None

    entry2 = account.ledger_for_strategy(s2).get(LedgerModule.positions)[p2]
    assert entry2.average_cost is None
    assert entry2.lots is not None and len(entry2.lots) == 0

    assert _cash_major(account, s1) == pytest.approx(1_000_000.0)


def test_initialize_ledgers_use_int_position_keeps_quantity_as_int():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="custom", accounting_mode="Custom", use_int_position=True)
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)
    entry = account.ledger_for_strategy(s).get(LedgerModule.positions)[p]
    assert isinstance(entry.quantity, int)
    assert entry.quantity == 0


def test_initialize_ledgers_uses_effective_backtest_product_universe():
    s = Strategy(alias="S")
    in_range, out_of_range = _product(), _product()
    config = _strategy_config(s, engine_mode="basic")
    account = _state_with_ledger_configs({s: config})
    account.market_data_store.included_products = frozenset({in_range})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({in_range, out_of_range}))

    _initialize_ledgers(account, ctx)

    positions = account.ledger_for_strategy(s).get(LedgerModule.positions)
    assert set(positions) == {in_range}


def test_initialize_ledgers_funds_empty_ledger_created_before_initialization():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="auto")
    account = _state_with_ledger_configs({s: config})
    # Some PRE_REPLAY flows ask for the strategy ledger identity before the
    # ledger initialization flow runs. That creates an empty LedgerState; init
    # must fund it instead of treating it as an already-funded shared ledger.
    empty = account.ledger_for_strategy(s)
    assert empty.get(LedgerModule.cash) is None
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))

    _initialize_ledgers(account, ctx)

    ledger = account.ledger_for_strategy(s)
    assert ledger is empty
    cash = cash_for_ledger(account, ledger)
    assert cash is not None
    assert cash.to_major() == pytest.approx(1_000_000.0)
    assert p in ledger.get(LedgerModule.positions)


def test_cash_zeros_after_full_rebalance_with_two_products():
    """Σ target_weights = 1 -> cash should be exactly zero after a full
    rebalance trade batch (algebraic result, not approximation)."""
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    config = _strategy_config(s, engine_mode="basic")
    account = _state_with_ledger_configs({s: config})

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
    _apply_order_fill(account, order_ctx)

    # second order processed in its own batch (same strategy, different
    # product) -- payload_for looks up by strategy, so reuse same pattern
    order_ctx2 = FlowContext(
        timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}),
        drafts_by_strategy={s: [draft2]},
    )
    order_ctx2.set(MarketDataModule.current_prices, prices)
    _apply_order_fill(account, order_ctx2)

    assert _cash_major(account, s) == pytest.approx(0.0, abs=1e-6)


def test_equity_on_signal_and_on_order_recompute_after_fill():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="basic")
    account = _state_with_ledger_configs({s: config})
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
    _apply_order_fill(account, order_ctx)
    _basic_equity(account, order_ctx)

    # equity unchanged by a fair-price trade (bought 1000 @ 10 = 10_000 cash
    # out, +10_000 market value in)
    assert order_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_000.0)
    cash_after = _cash_major(account, s)
    assert cash_after == pytest.approx(1_000_000.0 - 10_000.0)


def test_equity_on_order_marks_held_positions_from_snapshot_close_not_execution_prices():
    s = Strategy(alias="S")
    held = _product()
    traded = _product()
    config = _strategy_config(s, engine_mode="basic")
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({held, traded}))
    _initialize_ledgers(account, ctx)
    ledger = account.ledger_for_strategy(s)
    ledger.get(LedgerModule.positions)[held] = ProductPosition(quantity=10.0)

    t = pd.Timestamp("2024-01-01 09:30", tz="Asia/Shanghai")
    order_ctx = FlowContext(timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}))
    order_ctx.set(MarketDataModule.current_prices, {traded: 20.0})
    order_ctx.set(MarketDataModule.current_market_snapshot, {"close": {held: 7.0, traded: 21.0}})

    _basic_equity(account, order_ctx)

    assert order_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_000.0 + 70.0)


def test_equity_requires_ffilled_price_for_held_position():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="basic")
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)
    ledger = account.ledger_for_strategy(s)
    ledger.get(LedgerModule.positions)[p] = ProductPosition(quantity=10.0)

    signal_ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01 09:01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
    )
    signal_ctx.set(MarketDataModule.current_prices, {})

    with pytest.raises(KeyError, match="current price missing for held product"):
        _basic_equity(account, signal_ctx)


def test_equity_ignores_zero_position_without_price():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="basic")
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    signal_ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01 09:01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
    )
    signal_ctx.set(MarketDataModule.current_prices, {})

    _basic_equity(account, signal_ctx)

    assert signal_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_000.0)


def test_apply_order_fill_skips_rejected_order_without_ledger_effect():
    s = Strategy(alias="S")
    p = _product()
    base_config = _strategy_config(s, engine_mode="basic")
    config = StrategyConfig(
        strategy=s,
        active_flow_names=frozenset({"strategy_runtime_on_order_status_event"}),
        field_values=base_config.field_values,
    )
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    t = pd.Timestamp("2024-01-01")
    order = Order(instrument=p, timestamp=t, quantity=1000.0, intent_quantity=1000.0, strategy=s)
    order.set("reject_reason", "触及涨停，买入方向不可成交")
    order_ctx = FlowContext(
        timestamp=t,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, t, s, order)]},
    )
    order_ctx.set(MarketDataModule.current_prices, {p: 10.0})

    _apply_order_fill(account, order_ctx)

    ledger = account.ledger_for_strategy(s)
    cash = cash_for_ledger(account, ledger)
    assert cash is not None
    assert cash.to_major() == pytest.approx(1_000_000.0)
    assert ledger.get(LedgerModule.positions)[p].quantity == 0.0
    assert order.status == OrderStatus.REJECTED
    assert order.reject_reason == "触及涨停，买入方向不可成交"
    status_events = order_ctx._event_queue.snapshot_head()
    assert len(status_events) == 1
    assert status_events[0].kind is EventKind.ORDER_STATUS
    assert status_events[0].payload.status is OrderStatus.REJECTED


def test_apply_order_fill_and_equity_use_contract_multiplier():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="basic")
    account = _state_with_ledger_configs({s: config})
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

    _apply_order_fill(account, order_ctx)
    _basic_equity(account, order_ctx)

    assert _cash_major(account, s) == pytest.approx(900_000.0)
    assert order_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_000.0)
    assert order.status == OrderStatus.FILLED


def test_equity_uses_margin_and_floating_pnl_when_margin_is_tracked():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="basic")
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    ledger = account.ledger_for_strategy(s)
    set_cash_for_ledger_pool(account, ledger, DataMoney.from_major(
        990_000.0, currency="CNY", use_minor_units=False))
    ledger.set(LedgerModule.positions, {
        p: ProductPosition(
            quantity=10.0,
            average_cost=100.0,
            margin_reserved=DataMoney.from_major(
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


def test_equity_values_cash_and_margin_positions_in_the_same_ledger():
    s = Strategy(alias="mixed-accounting")
    margin_product, cash_product = _product(), _product()
    config = _strategy_config(s, engine_mode="auto")
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(
        ProductSelectionModule.products, s,
        frozenset({margin_product, cash_product}),
    )
    _initialize_ledgers(account, ctx)

    ledger = account.ledger_for_strategy(s)
    set_cash_for_ledger_pool(account, ledger, DataMoney.from_major(
        990_000.0, currency="CNY", use_minor_units=False))
    ledger.set(LedgerModule.positions, {
        margin_product: ProductPosition(
            quantity=10.0,
            average_cost=100.0,
            margin_reserved=DataMoney.from_major(
                1_000.0, currency="CNY", use_minor_units=False,
            ),
        ),
        cash_product: ProductPosition(
            quantity=10.0,
            average_cost=100.0,
            margin_reserved=None,
        ),
    })

    signal_ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
    )
    signal_ctx.set(MarketDataModule.current_prices, {
        margin_product: 110.0,
        cash_product: 110.0,
    })
    signal_ctx.set(MarketDataModule.current_historical_fields, {
        margin_product: {"VolumeMultiple": 2.0},
        cash_product: {"VolumeMultiple": 1.0},
    })

    _basic_equity(account, signal_ctx)

    # Margin positions contribute reserved collateral plus floating P&L;
    # fully funded positions contribute their current market value.  The
    # former global branch omitted the latter whenever any margin existed.
    assert signal_ctx.get_for(LedgerModule.equity, s) == pytest.approx(
        990_000.0 + 1_000.0 + 10.0 * (110.0 - 100.0) * 2.0 + 10.0 * 110.0,
    )


def test_margin_accounting_apply_order_fill_locks_margin_and_realizes_pnl():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(
        s,
        engine_mode="custom",
        accounting_mode="Custom",
        margin_mode="fixed",
        fixed_margin_ratio=0.1,
    )
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    open_ts = pd.Timestamp("2024-01-01")
    open_order = Order(instrument=p, timestamp=open_ts, quantity=10.0, intent_quantity=10.0, strategy=s)
    open_order.set("effective_price", 101.0)
    open_ctx = FlowContext(
        timestamp=open_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, open_ts, s, open_order)]},
    )
    open_ctx.set(MarketDataModule.current_prices, {p: 100.0})
    open_ctx.set(
        MarketDataModule.current_market_snapshot,
        {"close": {p: 90.0}},
    )
    open_ctx.set(MarketDataModule.current_historical_fields, {p: {"VolumeMultiple": 2.0}})

    _apply_order_fill(account, open_ctx)
    _basic_equity(account, open_ctx)

    assert _cash_major(account, s) == pytest.approx(999_798.0)
    assert open_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_000.0)

    signal_ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-02"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
    )
    signal_ctx.set(MarketDataModule.current_prices, {p: 110.0})
    signal_ctx.set(MarketDataModule.current_historical_fields, {p: {"VolumeMultiple": 2.0}})
    _basic_equity(account, signal_ctx)
    assert signal_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_180.0)

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

    _apply_order_fill(account, close_ctx)
    _basic_equity(account, close_ctx)

    assert _cash_major(account, s) == pytest.approx(1_000_180.0)
    assert close_ctx.get_for(LedgerModule.equity, s) == pytest.approx(1_000_180.0)


def test_margin_recalculation_uses_remaining_position_side_not_order_side():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(
        s,
        engine_mode="custom",
        accounting_mode="Auto",
        margin_mode="auto",
    )
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    fields = {
        p: {
            "VolumeMultiple": 1.0,
            "LongMarginRatioByMoney": 0.10,
            "ShortMarginRatioByMoney": 0.90,
        }
    }
    open_ts = pd.Timestamp("2024-01-01")
    open_order = Order(instrument=p, timestamp=open_ts, quantity=10.0, intent_quantity=10.0, strategy=s)
    open_ctx = FlowContext(
        timestamp=open_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, open_ts, s, open_order)]},
    )
    open_ctx.set(MarketDataModule.current_prices, {p: 100.0})
    open_ctx.set(MarketDataModule.current_historical_fields, fields)
    _apply_order_fill(account, open_ctx)

    close_ts = pd.Timestamp("2024-01-02")
    close_order = Order(instrument=p, timestamp=close_ts, quantity=-4.0, intent_quantity=-4.0, strategy=s)
    close_ctx = FlowContext(
        timestamp=close_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, close_ts, s, close_order)]},
    )
    close_ctx.set(MarketDataModule.current_prices, {p: 110.0})
    close_ctx.set(MarketDataModule.current_historical_fields, fields)

    _apply_order_fill(account, close_ctx)

    entry = account.ledger_for_strategy(s).get(LedgerModule.positions)[p]
    assert entry.quantity == pytest.approx(6.0)
    assert entry.margin_reserved.to_major() == pytest.approx(6.0 * 100.0 * 0.10)
    assert _cash_major(account, s) == pytest.approx(999_980.0)


def test_auto_margin_mode_cash_accounts_products_without_margin_rules():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(
        s,
        engine_mode="custom",
        accounting_mode="Custom",
        margin_mode="auto",
    )
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    ts = pd.Timestamp("2024-01-01")
    order = Order(instrument=p, timestamp=ts, quantity=10.0, intent_quantity=10.0, strategy=s)
    order_ctx = FlowContext(
        timestamp=ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, ts, s, order)]},
    )
    order_ctx.set(MarketDataModule.current_prices, {p: 100.0})
    order_ctx.set(MarketDataModule.current_historical_fields, {p: {}})

    _apply_order_fill(account, order_ctx)

    ledger = account.ledger_for_strategy(s)
    entry = ledger.get(LedgerModule.positions)[p]
    assert entry.quantity == pytest.approx(10.0)
    assert entry.margin_reserved is None
    cash = cash_for_ledger(account, ledger)
    assert cash is not None
    assert cash.to_major() == pytest.approx(999_000.0)


def test_cash_fill_does_not_recompute_unchanged_margin_components():
    """A cash-accounted fill must leave existing margin state untouched."""
    s = Strategy(alias="mixed")
    future, cash_product = _product(), _product()
    config = _strategy_config(
        s, engine_mode="custom", accounting_mode="Auto", margin_mode="auto",
    )
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({future, cash_product}))
    _initialize_ledgers(account, ctx)

    fields = {
        future: {"VolumeMultiple": 1.0, "LongMarginRatioByMoney": 0.10},
        cash_product: {},
    }
    open_ts = pd.Timestamp("2024-01-01")
    open_order = Order(
        instrument=future, timestamp=open_ts, quantity=10.0,
        intent_quantity=10.0, strategy=s,
    )
    open_ctx = FlowContext(
        timestamp=open_ts, event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, open_ts, s, open_order)]},
    )
    open_ctx.set(
        MarketDataModule.current_prices,
        {future: 100.0, cash_product: 100.0},
    )
    open_ctx.set(MarketDataModule.current_historical_fields, fields)
    _apply_order_fill(account, open_ctx)

    ledger = account.ledger_for_strategy(s)
    margin_fields = (
        MarginModule.margin_reserved,
        MarginModule.margin_requirement,
        MarginModule.margin_deficit,
        MarginModule.margin_excess,
    )
    before = {ref: ledger.get(ref) for ref in margin_fields}

    cash_ts = pd.Timestamp("2024-01-02")
    cash_order = Order(
        instrument=cash_product, timestamp=cash_ts, quantity=1.0,
        intent_quantity=1.0, strategy=s,
    )
    cash_ctx = FlowContext(
        timestamp=cash_ts, event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, cash_ts, s, cash_order)]},
    )
    cash_ctx.set(
        MarketDataModule.current_prices,
        {future: 100.0, cash_product: 100.0},
    )
    cash_ctx.set(MarketDataModule.current_historical_fields, fields)
    _apply_order_fill(account, cash_ctx)

    assert {ref: ledger.get(ref) for ref in margin_fields} == before


def test_auto_daily_mark_to_market_fill_marks_new_lot_as_today():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="auto")
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    ts = pd.Timestamp("2024-01-01")
    order = Order(instrument=p, timestamp=ts, quantity=2.0, intent_quantity=2.0, strategy=s)
    order_ctx = FlowContext(
        timestamp=ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, ts, s, order)]},
    )
    order_ctx.set(MarketDataModule.current_prices, {p: 10.0})
    order_ctx.set(MarketDataModule.current_historical_fields, {
        p: {
            "VolumeMultiple": 1.0,
            "SettlementPrice": 10.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_order_fill(account, order_ctx)

    entry = account.ledger_for_strategy(s).get(LedgerModule.positions)[p]
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in entry.lots] == [(2.0, 10.0, True)]


def test_auto_integer_dmtm_rejects_fractional_fill_before_ledger_mutation():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="auto")
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    ts = pd.Timestamp("2024-01-01")
    order = Order(instrument=p, timestamp=ts, quantity=0.4, intent_quantity=0.4, strategy=s)
    order_ctx = FlowContext(
        timestamp=ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, ts, s, order)]},
    )
    order_ctx.set(MarketDataModule.current_prices, {p: 10.0})
    order_ctx.set(MarketDataModule.current_historical_fields, {
        p: {
            "VolumeMultiple": 1.0,
            "SettlementPrice": 10.0,
            "CostBasisMethod": "DailyMarkToMarket",
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_order_fill(account, order_ctx)

    entry = account.ledger_for_strategy(s).get(LedgerModule.positions)[p]
    assert order.status is OrderStatus.REJECTED
    assert "取整为 0" in order.reject_reason
    assert entry.quantity == 0
    assert list(entry.lots or []) == []


def test_daily_mark_to_market_fill_uses_ledger_config_not_strategy_field():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(
        s,
        engine_mode="custom",
        accounting_mode="Custom",
        cost_basis_method="FIFO",
        daily_mark_to_market_enabled=False,
        fee_mode="auto",
        margin_mode="auto",
    )
    account = _state_with_ledger_configs({s: config})
    ledger_key = ledger_identity(f"private:{s.alias}")
    account.ledger_configs[ledger_key] = LedgerConfig(
        accounting_mode="Custom",
        cost_basis_method="FIFO",
        daily_mark_to_market_enabled=True,
        fee_mode="auto",
        margin_mode="auto",
    )
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    ts = pd.Timestamp("2024-01-01")
    order = Order(instrument=p, timestamp=ts, quantity=2.0, intent_quantity=2.0, strategy=s)
    order_ctx = FlowContext(
        timestamp=ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, ts, s, order)]},
    )
    order_ctx.set(MarketDataModule.current_prices, {p: 10.0})
    order_ctx.set(MarketDataModule.current_historical_fields, {
        p: {
            "VolumeMultiple": 1.0,
            "SettlementPrice": 10.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_order_fill(account, order_ctx)

    entry = account.ledger_for_strategy(s).get(LedgerModule.positions)[p]
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in entry.lots] == [(2.0, 10.0, True)]


def test_lot_based_accounting_without_daily_mark_to_market_keeps_today_marker_absent():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(
        s,
        engine_mode="custom",
        accounting_mode="Custom",
        cost_basis_method="FIFO",
    )
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    ts = pd.Timestamp("2024-01-01")
    order = Order(instrument=p, timestamp=ts, quantity=2.0, intent_quantity=2.0, strategy=s)
    order_ctx = FlowContext(
        timestamp=ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, ts, s, order)]},
    )
    order_ctx.set(MarketDataModule.current_prices, {p: 10.0})
    order_ctx.set(MarketDataModule.current_historical_fields, {p: {"VolumeMultiple": 1.0}})

    _apply_order_fill(account, order_ctx)

    entry = account.ledger_for_strategy(s).get(LedgerModule.positions)[p]
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in entry.lots] == [(2.0, 10.0, None)]


def test_strategy_book_private_mode_uses_one_ledger_per_strategy():
    s = Strategy(alias="S")
    p = _product()
    s2 = Strategy(alias="T")
    configs = {
        s: _strategy_config(s, engine_mode="basic"),
        s2: _strategy_config(s2, engine_mode="basic"),
    }
    account = _state_with_ledger_configs(configs)
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({p}))
    _initialize_ledgers(account, ctx)

    assert account.ledger_for_strategy(s) is not account.ledger_for_strategy(s2)
    assert sorted(ledger.name for ledger in account.ledgers) == sorted([
        f"private:{s.alias}",
        f"private:{s2.alias}",
    ])


def test_strategy_book_shared_mode_can_share_one_ledger_across_strategies():
    s1 = Strategy(alias="S1")
    s2 = Strategy(alias="S2")
    p = _product()
    configs = {
        s1: _strategy_config(s1, engine_mode="custom", margin_mode="none"),
        s2: _strategy_config(s2, engine_mode="custom", margin_mode="none"),
    }
    account = _state_with_ledger_configs(configs)
    materialize_strategy_book_store(account, StrategyBook.from_dict({
        "strategies": {
            s1.alias: "shared-book",
            s2.alias: "shared-book",
        },
    }), {s1.alias: s1, s2.alias: s2})
    account.ledger_configs[ledger_identity("shared-book")] = LedgerConfig(margin_mode="none")
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s1, frozenset({p}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({p}))
    _initialize_ledgers(account, ctx)

    ts = pd.Timestamp("2024-01-01")
    order = Order(instrument=p, timestamp=ts, quantity=2.0, intent_quantity=2.0, strategy=s1)
    order_ctx = FlowContext(
        timestamp=ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s1}),
        drafts_by_strategy={s1: [EventDraft(EventKind.ORDER, ts, s1, order)]},
    )
    order_ctx.set(MarketDataModule.current_prices, {p: 10.0})
    _apply_order_fill(account, order_ctx)

    assert [ledger.name for ledger in account.ledgers] == ["shared-book"]
    assert account.ledger_for_strategy(s1) is account.ledger_for_strategy(s2)
    assert account.ledger_for_strategy(s2).get(LedgerModule.positions)[p].quantity == pytest.approx(2.0)


def test_ledger_session_policy_errors_on_mixed_sessions_in_one_ledger():
    s = Strategy(alias="S")
    p_day = _product()
    p_night = _product()
    p_day.trading_session_signature = "day"
    p_night.trading_session_signature = "night"
    configs = {
        s: _strategy_config(s, engine_mode="custom", margin_mode="none"),
    }
    account = _state_with_ledger_configs(configs)
    materialize_strategy_book_store(account, StrategyBook.from_dict({
        "strategies": {s.alias: "shared-book"},
    }), {s.alias: s})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p_day, p_night}))

    with pytest.raises(ValueError, match="multiple trading sessions"):
        _apply_ledger_session_policy(account, ctx)


def test_ledger_session_policy_auto_split_routes_products_to_session_ledgers():
    s = Strategy(alias="S")
    p_day = _product()
    p_night = _product()
    p_day.trading_session_signature = "day"
    p_night.trading_session_signature = "night"
    configs = {
        s: _strategy_config(
            s,
            engine_mode="custom",
            margin_mode="none",
            ledger_session_policy="auto_split",
        ),
    }
    account = _state_with_ledger_configs(configs)
    materialize_strategy_book_store(account, StrategyBook.from_dict({
        "strategies": {s.alias: "shared-book"},
        "cash_pools": {"shared-book": "main-cash"},
    }), {s.alias: s})
    strategy_book_store_for(account).policies.cash_availability = lambda _state, _ledger, cash, _reason: cash
    account.ledger_configs[ledger_identity("shared-book")] = LedgerConfig(margin_mode="none")
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p_day, p_night}))

    _apply_ledger_session_policy(account, ctx)

    store = strategy_book_store_for(account)
    ledgers = store.ledgers_for_strategy(account, s)
    assert sorted(ledger.name for ledger in ledgers) == [
        "shared-book@session:day",
        "shared-book@session:night",
    ]
    assert {
        store.cash_pool_for_ledger(ledger)
        for ledger in ledgers
    } == {"main-cash"}
    day_order = Order(instrument=p_day, timestamp=pd.Timestamp("2024-01-01"), quantity=1.0, intent_quantity=1.0, strategy=s)
    night_order = Order(instrument=p_night, timestamp=pd.Timestamp("2024-01-01"), quantity=1.0, intent_quantity=1.0, strategy=s)
    assert account.ledger_for(day_order).ledger.name == "shared-book@session:day"
    assert account.ledger_for(night_order).ledger.name == "shared-book@session:night"
    assert account.ledger_config_for("shared-book@session:day").margin_mode == "none"
    assert account.runtime_info_rows[-1]["code"] == "ledger_session_auto_split"


def test_ledger_session_policy_auto_split_requires_custom_shared_cash_policy():
    s = Strategy(alias="S")
    p_day = _product()
    p_night = _product()
    p_day.trading_session_signature = "day"
    p_night.trading_session_signature = "night"
    configs = {
        s: _strategy_config(
            s,
            engine_mode="custom",
            margin_mode="none",
            ledger_session_policy="auto_split",
        ),
    }
    account = _state_with_ledger_configs(configs)
    materialize_strategy_book_store(account, StrategyBook.from_dict({
        "strategies": {s.alias: "shared-book"},
        "cash_pools": {"shared-book": "main-cash"},
    }), {s.alias: s})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p_day, p_night}))

    with pytest.raises(ValueError, match="no default inactive-ledger cash allocation policy"):
        _apply_ledger_session_policy(account, ctx)


def test_ledger_session_policy_auto_split_requires_single_source_ledger():
    s = Strategy(alias="S")
    p_day = _product()
    p_night = _product()
    p_day.trading_session_signature = "day"
    p_night.trading_session_signature = "night"
    configs = {
        s: _strategy_config(
            s,
            engine_mode="custom",
            margin_mode="none",
            ledger_session_policy="auto_split",
        ),
    }
    account = _state_with_ledger_configs(configs)
    materialize_strategy_book_store(account, StrategyBook.from_dict({
        "strategies": {
            s.alias: {
                "ledger_ids": ["book-a", "book-b"],
                "default_ledger_id": "book-a",
            },
        },
        "cash_pools": {
            "book-a": "main-cash",
            "book-b": "main-cash",
        },
    }), {s.alias: s})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p_day, p_night}))

    with pytest.raises(ValueError, match="only supports one source ledger"):
        _apply_ledger_session_policy(account, ctx)


def test_equity_on_shared_ledger_is_computed_once_per_event(monkeypatch):
    s1 = Strategy(alias="S1")
    s2 = Strategy(alias="S2")
    p = _product()
    configs = {
        s1: _strategy_config(s1, engine_mode="custom", margin_mode="none"),
        s2: _strategy_config(s2, engine_mode="custom", margin_mode="none"),
    }
    account = _state_with_ledger_configs(configs)
    materialize_strategy_book_store(account, StrategyBook.from_dict({
        "strategies": {
            s1.alias: "shared-book",
            s2.alias: "shared-book",
        },
    }), {s1.alias: s1, s2.alias: s2})
    account.ledger_configs[ledger_identity("shared-book")] = LedgerConfig(margin_mode="none")
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s1, frozenset({p}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({p}))
    _initialize_ledgers(account, ctx)
    account.ledger_for_strategy(s1).set(LedgerModule.positions, {p: ProductPosition(quantity=2.0)})

    calls = 0
    real_ledger_equity = ledger_module_impl._ledger_equity

    def _counting_ledger_equity(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_ledger_equity(*args, **kwargs)

    monkeypatch.setattr(ledger_module_impl, "_ledger_equity", _counting_ledger_equity)
    equity_ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s1, s2}),
    )
    equity_ctx.set(MarketDataModule.current_prices, {p: 10.0})
    equity_ctx.set(MarketDataModule.current_historical_fields, {})

    _basic_equity(account, equity_ctx)

    assert calls == 1
    assert equity_ctx.get_for(LedgerModule.equity, s1) == pytest.approx(1_000_020.0)
    assert equity_ctx.get_for(LedgerModule.equity, s2) == pytest.approx(1_000_020.0)


def test_strategy_book_declares_cash_pool_across_distinct_ledgers():
    s1 = Strategy(alias="S1")
    s2 = Strategy(alias="S2")
    p1 = _product()
    p2 = _product()
    configs = {
        s1: _strategy_config(s1, engine_mode="custom", margin_mode="none"),
        s2: _strategy_config(s2, engine_mode="custom", margin_mode="none"),
    }
    account = _state_with_ledger_configs(configs)
    book = StrategyBook.from_dict({
        "strategies": {
            s1.alias: "book-a",
            s2.alias: "book-b",
        },
        "cash_pools": {
            "book-a": "main-cash",
            "book-b": "main-cash",
        },
    })
    materialize_strategy_book_store(account, book, {s1.alias: s1, s2.alias: s2})
    account.ledger_configs[ledger_identity("book-a")] = LedgerConfig(
        margin_mode="none",
    )
    account.ledger_configs[ledger_identity("book-b")] = LedgerConfig(
        margin_mode="none",
    )
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s1, frozenset({p1}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({p2}))
    _initialize_ledgers(account, ctx)

    assert account.ledger_for_strategy(s1) is not account.ledger_for_strategy(s2)
    assert _cash(account, s1) is not _cash(account, s2)

    ts = pd.Timestamp("2024-01-01")
    order = Order(instrument=p1, timestamp=ts, quantity=2.0, intent_quantity=2.0, strategy=s1)
    order_ctx = FlowContext(
        timestamp=ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s1}),
        drafts_by_strategy={s1: [EventDraft(EventKind.ORDER, ts, s1, order)]},
    )
    order_ctx.set(MarketDataModule.current_prices, {p1: 10.0})
    order_ctx.set(MarketDataModule.current_historical_fields, {p1: {}})

    _apply_order_fill(account, order_ctx)

    assert account.ledger_for_strategy(s1).get(LedgerModule.positions)[p1].quantity == pytest.approx(2.0)
    assert p1 not in account.ledger_for_strategy(s2).get(LedgerModule.positions)
    assert _cash_major(account, s1) == pytest.approx(999_980.0)
    assert _cash_major(account, s2) == pytest.approx(0.0)
    assert cash_pool_cash_major(
        account, account.ledger_for_strategy(s1), timestamp=ts,
    ) == pytest.approx(999_980.0)


def test_strategy_book_cash_pool_keeps_distinct_account_currency_balances():
    s1 = Strategy(alias="S1")
    s2 = Strategy(alias="S2")
    configs = {
        s1: _strategy_config(s1, engine_mode="custom", margin_mode="none", base_currency="CNY"),
        s2: _strategy_config(s2, engine_mode="custom", margin_mode="none", base_currency="CNY"),
    }
    account = BacktestRunState(strategy_configs=configs)
    book = StrategyBook.from_dict({
        "strategies": {
            s1.alias: "book-a",
            s2.alias: "book-b",
        },
        "cash_pools": {
            "book-a": "main-cash",
            "book-b": "main-cash",
        },
        "cash_pool_configs": {
            "main-cash": {
                "initial_capital_major": 1_000_000.0,
                "base_currency": "CNY",
            },
        },
    })
    materialize_strategy_book_store(account, book, {s1.alias: s1, s2.alias: s2})
    account.ledger_configs[ledger_identity("book-a")] = LedgerConfig(
        margin_mode="none", account_currency="CNY",
    )
    account.ledger_configs[ledger_identity("book-b")] = LedgerConfig(
        margin_mode="none", account_currency="USD",
    )

    _initialize_ledgers(account, FlowContext(timestamp=None, event_queue=EventQueue()))

    cny_cash = cash_for_ledger(account, account.ledger_for_strategy(s1))
    usd_cash = cash_for_ledger(account, account.ledger_for_strategy(s2))
    assert cny_cash is not usd_cash
    assert cny_cash.currency == "CNY"
    assert usd_cash.currency == "USD"
    assert cny_cash.to_major() == pytest.approx(1_000_000.0)
    assert usd_cash.to_major() == pytest.approx(0.0)


def test_mixed_currency_account_fill_updates_account_cash_and_pool_base_value():
    cny_strategy, usd_strategy = Strategy(alias="CNY"), Strategy(alias="USD")
    usd_product = Product(name=f"USD-{uuid.uuid4().hex}", point_value=1, currency="USD")
    configs = {
        cny_strategy: _strategy_config(
            cny_strategy, engine_mode="custom", margin_mode="none", base_currency="CNY",
        ),
        usd_strategy: _strategy_config(
            usd_strategy, engine_mode="custom", margin_mode="none", base_currency="CNY",
        ),
    }
    account = BacktestRunState(strategy_configs=configs)
    book = StrategyBook.from_dict({
        "strategies": {cny_strategy.alias: "cny-account", usd_strategy.alias: "usd-account"},
        "cash_pools": {"cny-account": "pool", "usd-account": "pool"},
        "cash_pool_configs": {
            "pool": {"initial_capital_major": 1_000_000.0, "base_currency": "CNY"},
        },
    })
    materialize_strategy_book_store(
        account, book, {cny_strategy.alias: cny_strategy, usd_strategy.alias: usd_strategy},
    )
    account.ledger_configs[ledger_identity("cny-account")] = LedgerConfig(
        margin_mode="none", account_currency="CNY",
    )
    account.ledger_configs[ledger_identity("usd-account")] = LedgerConfig(
        margin_mode="none", account_currency="USD",
    )
    init_ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    init_ctx.set_for(ProductSelectionModule.products, usd_strategy, frozenset({usd_product}))
    _initialize_ledgers(account, init_ctx)
    account.cash_pool_store.fx_rate_provider = (
        lambda source, target, _timestamp: 7.0
        if (source, target) == ("USD", "CNY") else None
    )
    timestamp = pd.Timestamp("2025-01-02 09:30")
    order = Order(
        instrument=usd_product, timestamp=timestamp, quantity=2.0,
        intent_quantity=2.0, strategy=usd_strategy,
    )
    order_ctx = FlowContext(
        timestamp=timestamp, event_queue=EventQueue(),
        active_strategies=frozenset({usd_strategy}),
        drafts_by_strategy={
            usd_strategy: [EventDraft(EventKind.ORDER, timestamp, usd_strategy, order)],
        },
    )
    order_ctx.set(MarketDataModule.current_prices, {usd_product: 10.0})
    order_ctx.set(MarketDataModule.current_historical_fields, {usd_product: {}})

    _apply_order_fill(account, order_ctx)

    usd_ledger = account.ledger_for_strategy(usd_strategy)
    assert cash_for_ledger(account, usd_ledger).to_major() == pytest.approx(-20.0)
    assert cash_pool_cash_major(
        account, usd_ledger, timestamp=timestamp,
    ) == pytest.approx(999_860.0)
    settlement = next(iter(account.order_store.settlements_by_fill.values()))
    assert settlement.account_id == "usd-account"
    assert settlement.cash_pool_id == "pool"
    assert settlement.account_currency == "USD"
    assert settlement.cash_pool_base_currency == "CNY"


def test_shared_ledger_rejects_mismatched_initial_capital_instead_of_last_writer_wins():
    s1, s2 = Strategy(alias="S1"), Strategy(alias="S2")
    config1 = StrategyConfig(strategy=s1, field_values={
        EngineModule.engine_mode: "custom",
        LedgerModule.initial_capital_major: 1_000_000.0, LedgerModule.base_currency: "CNY",
        MarginModule.margin_mode: "none",
    })
    config2 = StrategyConfig(strategy=s2, field_values={
        EngineModule.engine_mode: "custom",
        LedgerModule.initial_capital_major: 2_000_000.0, LedgerModule.base_currency: "CNY",
        MarginModule.margin_mode: "none",
    })
    account = BacktestRunState(strategy_configs={s1: config1, s2: config2})
    account.ledger_configs[ledger_identity("shared-book")] = LedgerConfig(
        margin_mode="none",
    )
    materialize_strategy_book_store(account, StrategyBook.from_dict({
        "strategies": {
            s1.alias: "shared-book",
            s2.alias: "shared-book",
        },
    }), {s1.alias: s1, s2.alias: s2})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    with pytest.raises(ValueError, match="initial_capital_major"):
        _initialize_ledgers(account, ctx)


def test_shared_ledger_rejects_mismatched_base_currency_instead_of_silently_swapping_it():
    s1, s2 = Strategy(alias="S1"), Strategy(alias="S2")
    config1 = StrategyConfig(strategy=s1, field_values={
        EngineModule.engine_mode: "custom",
        LedgerModule.initial_capital_major: 1_000_000.0, LedgerModule.base_currency: "CNY",
        MarginModule.margin_mode: "none",
    })
    config2 = StrategyConfig(strategy=s2, field_values={
        EngineModule.engine_mode: "custom",
        LedgerModule.initial_capital_major: 1_000_000.0, LedgerModule.base_currency: "USD",
        MarginModule.margin_mode: "none",
    })
    account = BacktestRunState(strategy_configs={s1: config1, s2: config2})
    account.ledger_configs[ledger_identity("shared-book")] = LedgerConfig(
        margin_mode="none",
    )
    materialize_strategy_book_store(account, StrategyBook.from_dict({
        "strategies": {
            s1.alias: "shared-book",
            s2.alias: "shared-book",
        },
    }), {s1.alias: s1, s2.alias: s2})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    with pytest.raises(ValueError, match="base_currency"):
        _initialize_ledgers(account, ctx)


@pytest.mark.parametrize("fee_mode", ["zero", "fixed", "close_today", "close_yesterday"])
def test_daily_mark_to_market_does_not_mark_today_when_fee_mode_does_not_need_lot_split(fee_mode: str):
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(
        s,
        engine_mode="custom",
        accounting_mode="Custom",
        cost_basis_method="FIFO",
        daily_mark_to_market_enabled=True,
        fee_mode=fee_mode,
        fixed_fee_rate=0.001,
    )
    account = _state_with_ledger_configs({s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, s, frozenset({p}))
    _initialize_ledgers(account, ctx)

    ts = pd.Timestamp("2024-01-01")
    order = Order(instrument=p, timestamp=ts, quantity=2.0, intent_quantity=2.0, strategy=s)
    order_ctx = FlowContext(
        timestamp=ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [EventDraft(EventKind.ORDER, ts, s, order)]},
    )
    order_ctx.set(MarketDataModule.current_prices, {p: 10.0})
    order_ctx.set(MarketDataModule.current_historical_fields, {p: {
        "VolumeMultiple": 1.0,
        "SettlementPrice": 10.0,
        "LongMarginRatioByMoney": 0.1,
    }})

    _apply_order_fill(account, order_ctx)

    entry = account.ledger_for_strategy(s).get(LedgerModule.positions)[p]
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in entry.lots] == [(2.0, 10.0, None)]


def test_two_strategies_independent_ledgers_do_not_cross_contaminate():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")
    p = _product()
    configs = {
        s1: _strategy_config(s1, engine_mode="basic"),
        s2: _strategy_config(s2, engine_mode="basic"),
    }
    account = _state_with_ledger_configs(configs)
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
    _apply_order_fill(account, order_ctx)

    assert account.ledger_for_strategy(s1).get(LedgerModule.positions)[p].quantity == 100.0
    assert account.ledger_for_strategy(s2).get(LedgerModule.positions)[p].quantity == 0.0
    assert _cash_major(account, s2) == pytest.approx(1_000_000.0)


def test_cancelled_order_has_no_ledger_effect():
    s = Strategy(alias="S")
    p = _product()
    config = _strategy_config(s, engine_mode="basic")
    account = _state_with_ledger_configs({s: config})
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
    _apply_order_fill(account, order_ctx)

    assert account.ledger_for_strategy(s).get(LedgerModule.positions)[p].quantity == 0.0
    assert _cash_major(account, s) == pytest.approx(1_000_000.0)


def test_multiple_simultaneous_orders_for_one_strategy_are_all_applied():
    """Regression: a single dispatch batch can carry several ORDER drafts
    for the SAME strategy (one per product being rebalanced at this
    timestamp). All of them must update the ledger, not just one."""
    s = Strategy(alias="S")
    p1, p2, p3 = _product(), _product(), _product()
    config = _strategy_config(s, engine_mode="basic")
    account = _state_with_ledger_configs({s: config})
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
    _apply_order_fill(account, order_ctx)

    positions = account.ledger_for_strategy(s).get(LedgerModule.positions)
    assert positions[p1].quantity == 10.0
    assert positions[p2].quantity == 20.0
    assert positions[p3].quantity == 30.0
    assert _cash_major(account, s) == pytest.approx(1_000_000.0 - 60.0)

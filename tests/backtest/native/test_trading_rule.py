from __future__ import annotations

import uuid
from collections import deque

import pandas as pd
import pytest

from tools.data.types.data_money import DataMoney
from tools.products.Product import Product
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.ledger import Ledger, Lot, ProductPosition, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.ledger import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.trading_rule import (
    TradingRuleModule, _resolve_daily_mark_to_market_enabled, _resolve_method, _resolve_use_int_position,
    close_position, infer_auto_cost_basis_method, mark_to_market, open_position, _apply_daily_mark_to_market,
    _register_daily_mark_to_market_notices,
)
from tools.testers.backtest.modules.margin import (
    MarginModule, _resolve_margin_mode, _resolve_margin_ratio,
)


def _product(margin_traded: bool = False) -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY", is_margin_traded=margin_traded)


def _config(**values) -> StrategyConfig:
    s = Strategy(alias="S")
    field_values = {}
    for key, value in values.items():
        ref = (
            getattr(EngineModule, key, None)
            or getattr(TradingRuleModule, key, None)
            or getattr(FeeModule, key, None)
            or getattr(MarginModule, key)
        )
        field_values[ref] = value
    return StrategyConfig(strategy=s, field_values=field_values)


def test_resolve_method_basic_is_always_weight_average():
    config = _config(engine_mode="basic")
    assert _resolve_method(config, _product()) == "WeightAverage"


def test_resolve_method_custom_reads_field():
    config = _config(engine_mode="custom", accounting_mode="Custom", cost_basis_method="FIFO")
    assert _resolve_method(config, _product()) == "FIFO"


def test_resolve_method_auto_uses_explicit_historical_cost_basis_method():
    config = _config(engine_mode="auto")
    assert _resolve_method(config, _product(margin_traded=True), {"CostBasisMethod": "FIFO"}) == "FIFO"


def test_resolve_method_auto_uses_fifo_and_daily_mark_to_market_when_close_today_field_exists():
    config = _config(engine_mode="auto")
    fields = {
        "CloseRatioByMoney": 0.0001,
        "CloseTodayRatioByMoney": 0.0001,
    }
    product = _product(margin_traded=False)
    assert _resolve_method(config, product, fields) == "FIFO"
    assert _resolve_daily_mark_to_market_enabled(config, product, fields) is True


def test_resolve_method_auto_uses_fifo_and_daily_mark_to_market_when_settlement_field_exists():
    config = _config(engine_mode="auto")
    product = _product(margin_traded=False)
    fields = {"SettlementPrice": 10.0}
    assert _resolve_method(config, product, fields) == "FIFO"
    assert _resolve_daily_mark_to_market_enabled(config, product, fields) is True


def test_resolve_method_auto_uses_fifo_when_fee_exists_without_close_today_fields():
    config = _config(engine_mode="auto")
    fields = {
        "OpenRatioByMoney": 0.0001,
        "CloseRatioByMoney": 0.0001,
    }
    assert _resolve_method(config, _product(margin_traded=False), fields) == "FIFO"


def test_legacy_daily_mark_to_market_cost_basis_field_means_fifo_plus_daily_settlement():
    config = _config(engine_mode="auto")
    product = _product(margin_traded=False)
    fields = {"CostBasisMethod": "DailyMarkToMarket"}
    assert _resolve_method(config, product, fields) == "FIFO"
    assert _resolve_daily_mark_to_market_enabled(config, product, fields) is True


def test_resolve_method_auto_without_fee_information_falls_back_to_weight_average():
    config = _config(engine_mode="auto")
    assert _resolve_method(config, _product(margin_traded=True), {}) == "WeightAverage"


def test_resolve_method_exact_requires_explicit_historical_cost_basis_method():
    config = _config(engine_mode="exact")
    with pytest.raises(KeyError):
        _resolve_method(config, _product(), {}, require_exact=True)


def test_infer_auto_cost_basis_rejects_unknown_explicit_method():
    with pytest.raises(ValueError):
        infer_auto_cost_basis_method({"CostBasisMethod": "Mystery"})


def test_resolve_use_int_position_basic_false_auto_true_custom_reads_field():
    assert _resolve_use_int_position(_config(engine_mode="basic")) is False
    assert _resolve_use_int_position(_config(engine_mode="auto")) is True
    assert _resolve_use_int_position(_config(engine_mode="custom", accounting_mode="Custom", use_int_position=True)) is True
    assert _resolve_use_int_position(_config(engine_mode="custom", accounting_mode="Custom")) is False


def test_resolve_margin_mode_defaults_auto_and_reads_field():
    assert _resolve_margin_mode(_config(engine_mode="basic")) == "none"
    assert _resolve_margin_mode(_config(engine_mode="auto")) == "auto"
    assert _resolve_margin_mode(_config(engine_mode="custom")) == "auto"
    assert _resolve_margin_mode(_config(engine_mode="custom", margin_mode="fixed")) == "fixed"


def test_resolve_margin_ratio_basic_is_zero():
    config = _config(engine_mode="basic")
    assert _resolve_margin_ratio(config, market_margin_ratio=0.1) == 0.0


def test_resolve_margin_ratio_none_is_zero():
    config = _config(engine_mode="custom", margin_mode="none")
    assert _resolve_margin_ratio(config, market_margin_ratio=0.1) == 0.0


def test_resolve_margin_ratio_fixed_uses_fixed_field():
    config = _config(engine_mode="custom", margin_mode="fixed", fixed_margin_ratio=0.2)
    assert _resolve_margin_ratio(config, market_margin_ratio=0.9) == 0.2


def test_resolve_margin_ratio_auto_uses_caller_supplied_market_ratio():
    config = _config(engine_mode="auto")
    assert _resolve_margin_ratio(config, market_margin_ratio=0.15) == 0.15


def test_equity_occupied_basic_accounting_has_zero_margin():
    product = _product()
    config = _config(engine_mode="basic")
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, average_cost=0.0,
                                                              equity_occupied=None)})
    open_position(ledger, config, product, quantity=10.0, entry_price=5.0, multiplier=1.0)
    entry = ledger.get(_positions_ref())[product]
    assert entry.equity_occupied.to_major() == pytest.approx(0.0)


def test_equity_occupied_fixed_margin_ratio_discounts_notional():
    product = _product()
    config = _config(engine_mode="custom", accounting_mode="Custom", cost_basis_method="WeightAverage",
                     margin_mode="fixed", fixed_margin_ratio=0.1)
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, average_cost=0.0)})
    open_position(ledger, config, product, quantity=10.0, entry_price=5.0, multiplier=1.0)
    entry = ledger.get(_positions_ref())[product]
    assert entry.equity_occupied.to_major() == pytest.approx(5.0)  # 10*5*1*0.1


def test_weight_average_open_then_partial_close_realizes_pnl_at_average_cost():
    product = _product()
    config = _config(engine_mode="basic")
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, average_cost=0.0)})

    open_position(ledger, config, product, quantity=10.0, entry_price=10.0, multiplier=1.0)
    open_position(ledger, config, product, quantity=10.0, entry_price=20.0, multiplier=1.0)
    entry = ledger.get(_positions_ref())[product]
    assert entry.quantity == 20.0
    assert entry.average_cost == pytest.approx(15.0)

    realized = close_position(ledger, config, product, quantity=5.0, fill_price=18.0, multiplier=1.0)
    assert realized.to_major() == pytest.approx(5.0 * (18.0 - 15.0))
    entry = ledger.get(_positions_ref())[product]
    assert entry.quantity == 15.0


def test_fifo_closes_earliest_lot_first():
    product = _product()
    config = _config(engine_mode="custom", accounting_mode="Custom", cost_basis_method="FIFO")
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    from collections import deque
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, lots=deque())})

    open_position(ledger, config, product, quantity=10.0, entry_price=10.0, multiplier=1.0)
    open_position(ledger, config, product, quantity=10.0, entry_price=20.0, multiplier=1.0)

    realized = close_position(ledger, config, product, quantity=10.0, fill_price=25.0, multiplier=1.0)
    # FIFO closes the first lot (entry_price=10) first
    assert realized.to_major() == pytest.approx(10.0 * (25.0 - 10.0))
    entry = ledger.get(_positions_ref())[product]
    assert entry.quantity == 10.0
    assert len(entry.lots) == 1
    assert entry.lots[0].entry_price == 20.0


def test_lifo_closes_latest_lot_first():
    product = _product()
    config = _config(engine_mode="custom", accounting_mode="Custom", cost_basis_method="LIFO")
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    from collections import deque
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, lots=deque())})

    open_position(ledger, config, product, quantity=10.0, entry_price=10.0, multiplier=1.0)
    open_position(ledger, config, product, quantity=10.0, entry_price=20.0, multiplier=1.0)

    realized = close_position(ledger, config, product, quantity=10.0, fill_price=25.0, multiplier=1.0)
    assert realized.to_major() == pytest.approx(10.0 * (25.0 - 20.0))
    entry = ledger.get(_positions_ref())[product]
    assert entry.lots[0].entry_price == 10.0


def test_hifo_closes_highest_cost_lot_first():
    product = _product()
    config = _config(engine_mode="custom", accounting_mode="Custom", cost_basis_method="HIFO")
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    from collections import deque
    ledger.set(_positions_ref(), {product: ProductPosition(quantity=0.0, lots=deque())})

    open_position(ledger, config, product, quantity=10.0, entry_price=10.0, multiplier=1.0)
    open_position(ledger, config, product, quantity=10.0, entry_price=30.0, multiplier=1.0)  # highest cost, middle in time
    open_position(ledger, config, product, quantity=10.0, entry_price=20.0, multiplier=1.0)

    realized = close_position(ledger, config, product, quantity=10.0, fill_price=35.0, multiplier=1.0)
    assert realized.to_major() == pytest.approx(10.0 * (35.0 - 30.0))
    remaining_costs = sorted(lot.entry_price for lot in ledger.get(_positions_ref())[product].lots)
    assert remaining_costs == [10.0, 20.0]


def test_daily_mark_to_market_notice_uses_trading_day_last_bar_not_calendar_day():
    strategy = Strategy(alias="S")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            active_flow_names=frozenset({"register_daily_mark_to_market_notices"}),
            field_values={
                EngineModule.engine_mode: "auto",
                TradingRuleModule.accounting_mode: "Auto",
            },
        )
    })
    trade_times = pd.DatetimeIndex([
        pd.Timestamp("2026-03-09 21:00:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-03-10 09:01:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-03-10 15:00:00", tz="Asia/Shanghai"),
    ])
    trading_days = pd.DatetimeIndex(["2026-03-10", "2026-03-10", "2026-03-10"])
    index = pd.MultiIndex.from_arrays([trading_days, trade_times], names=["trading_day", "_SIGNAL@MIN1"])
    account.market_data_store.current_prices_table = pd.DataFrame({"P1": [1.0, 2.0, 3.0]}, index=index)
    queue = EventQueue()
    captured = []
    queue.set_dispatcher(EventKind.LEDGER_NOTICE, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))

    _register_daily_mark_to_market_notices(account, ctx)
    queue.run_until_drained()

    assert len(captured) == 1
    assert captured[0].timestamp == pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai")
    assert captured[0].payload == {"kind": "daily_mark_to_market", "trading_day": "2026-03-10"}


def test_daily_mark_to_market_updates_cash_margin_and_settlement_basis():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
            MarginModule.margin_mode: "auto",
        },
    )
    ledger = Ledger(strategy=strategy, base_currency="CNY")
    ledger.set(
        _positions_ref(),
        {
            product: ProductPosition(
                quantity=2.0,
                lots=deque([
                    Lot(quantity=2.0, entry_price=10.0, multiplier=10.0, is_today=False),
                ]),
                equity_occupied=DataMoney.from_major(2.0, currency="CNY", use_minor_units=False),
            )
        },
    )
    ledger.set(_cash_ref(), DataMoney.from_major(1000.0, currency="CNY", use_minor_units=False))
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={strategy: ledger})
    queue = EventQueue()
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=queue,
        active_strategies=frozenset({strategy}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 12.0},
        "close": {product: 11.5},
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 10.0,
            "PreSettlementPrice": 10.0,
            "SettlementPrice": 12.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    updated_cash = ledger.get(_cash_ref())
    updated_position = ledger.get(_positions_ref())[product]
    # pnl = 2 * (12 - 10) * 10 = 40
    # margin grows from 2 to 2 * 12 * 10 * 0.1 = 24, so cash delta = 40 - 22
    assert updated_cash.to_major() == pytest.approx(1018.0)
    assert updated_position.equity_occupied.to_major() == pytest.approx(24.0)
    assert updated_position.settlement_price == pytest.approx(12.0)
    assert updated_position.average_cost is None
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in updated_position.lots] == [(2.0, 12.0, False)]


def test_daily_mark_to_market_uses_blended_intraday_basis_after_same_day_add():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
            MarginModule.margin_mode: "auto",
        },
    )
    ledger = Ledger(strategy=strategy, base_currency="CNY")
    ledger.set(
        _positions_ref(),
        {
            product: ProductPosition(
                quantity=2.0,
                lots=deque([
                    Lot(quantity=1.0, entry_price=20.0, multiplier=1.0, is_today=False),
                    Lot(quantity=1.0, entry_price=10.0, multiplier=1.0, is_today=True),
                ]),
                settlement_price=20.0,  # stale previous settlement for the old lot only
                equity_occupied=DataMoney.from_major(4.0, currency="CNY", use_minor_units=False),
            )
        },
    )
    ledger.set(_cash_ref(), DataMoney.from_major(1000.0, currency="CNY", use_minor_units=False))
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={strategy: ledger})
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 18.0},
        "close": {product: 18.0},
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 1.0,
            "SettlementPrice": 18.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    updated_cash = ledger.get(_cash_ref())
    updated_position = ledger.get(_positions_ref())[product]
    # Correct PnL: old lot (18-20) + new lot (18-10) = +6, equivalent to
    # 2 * (18 - blended_basis 15). The stale settlement tag alone would
    # produce 2 * (18 - 20) = -4 and an artificial equity drop.
    # Margin falls from 4.0 to 2 * 18 * 0.1 = 3.6, so cash delta = 6 + 0.4.
    assert updated_cash.to_major() == pytest.approx(1006.4)
    assert updated_position.equity_occupied.to_major() == pytest.approx(3.6)
    assert updated_position.settlement_price == pytest.approx(18.0)
    assert updated_position.average_cost is None
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in updated_position.lots] == [(2.0, 18.0, False)]


def test_daily_mark_to_market_prefers_lot_basis_even_when_equal_to_current_settlement():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
            MarginModule.margin_mode: "auto",
        },
    )
    ledger = Ledger(strategy=strategy, base_currency="CNY")
    ledger.set(_cash_ref(), DataMoney.from_major(1000.0, currency="CNY", use_minor_units=False))
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=1.0,
            lots=deque([Lot(quantity=1.0, entry_price=18.0, multiplier=1.0, is_today=True)]),
            settlement_price=20.0,
            equity_occupied=DataMoney.from_major(2.0, currency="CNY", use_minor_units=False),
        )
    })
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={strategy: ledger})
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: 18.0},
        "close": {product: 18.0},
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 1.0,
            "PreSettlementPrice": 20.0,
            "SettlementPrice": 18.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    # PnL is zero because the open lot's basis is already 18. The historical
    # PreSettlementPrice belongs to old inventory and must not override lots.
    assert ledger.get(_cash_ref()).to_major() == pytest.approx(1000.0 + 0.2)
    entry = ledger.get(_positions_ref())[product]
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in entry.lots] == [(1.0, 18.0, False)]


def test_daily_mark_to_market_settlement_keeps_today_marker_absent_when_fee_mode_does_not_need_split():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"apply_daily_mark_to_market"}),
        field_values={
            EngineModule.engine_mode: "custom",
            TradingRuleModule.accounting_mode: "Custom",
            TradingRuleModule.cost_basis_method: "FIFO",
            TradingRuleModule.daily_mark_to_market_enabled: True,
            FeeModule.fee_mode: "zero",
            MarginModule.margin_mode: "auto",
        },
    )
    ledger = Ledger(strategy=strategy, base_currency="CNY")
    ledger.set(_cash_ref(), DataMoney.from_major(1000.0, currency="CNY", use_minor_units=False))
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            lots=deque([
                Lot(quantity=1.0, entry_price=20.0, multiplier=1.0, is_today=None),
                Lot(quantity=1.0, entry_price=10.0, multiplier=1.0, is_today=None),
            ]),
            settlement_price=20.0,
            equity_occupied=DataMoney.from_major(4.0, currency="CNY", use_minor_units=False),
        )
    })
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={strategy: ledger})
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 15:00:00.000000001", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set(MarketDataModule.current_market_snapshot, {"settlement": {product: 18.0}, "close": {product: 18.0}})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {
            "VolumeMultiple": 1.0,
            "SettlementPrice": 18.0,
            "LongMarginRatioByMoney": 0.1,
        }
    })

    _apply_daily_mark_to_market(account, ctx)

    entry = ledger.get(_positions_ref())[product]
    assert [(lot.quantity, lot.entry_price, lot.is_today) for lot in entry.lots] == [(2.0, 18.0, None)]


def test_daily_mark_to_market_close_uses_fifo_mark_to_market_lots():
    product = _product()
    config = _config(
        engine_mode="custom",
        accounting_mode="Custom",
        cost_basis_method="FIFO",
        daily_mark_to_market_enabled=True,
    )
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    ledger.set(
        _positions_ref(),
        {
            product: ProductPosition(
                quantity=2.0,
                lots=deque([
                    Lot(quantity=1.0, entry_price=20.0, multiplier=1.0, is_today=False),
                    Lot(quantity=1.0, entry_price=10.0, multiplier=1.0, is_today=True),
                ]),
                settlement_price=20.0,
                equity_occupied=DataMoney.from_major(4.0, currency="CNY", use_minor_units=False),
            )
        },
    )

    realized = close_position(
        ledger,
        config,
        product,
        quantity=1.0,
        fill_price=18.0,
        multiplier=1.0,
    )

    # Daily mark-to-market is not a blended average-cost close. It consumes
    # yesterday's lot first here, so closing at 18 against yesterday's 20 basis
    # realizes -2; today's @10 lot remains open.
    assert realized.to_major() == pytest.approx(18.0 - 20.0)
    entry = ledger.get(_positions_ref())[product]
    assert [lot.entry_price for lot in entry.lots] == [10.0]


def test_daily_mark_to_market_intraday_equity_uses_last_settlement_basis():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = Ledger(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=3.0,
            lots=deque([
                Lot(quantity=3.0, entry_price=12.0, multiplier=10.0, is_today=False),
            ]),
            settlement_price=12.0,
            equity_occupied=DataMoney.from_major(36.0, currency="CNY", use_minor_units=False),
        )
    })

    pnl = mark_to_market(
        ledger,
        config,
        {product: 13.5},
        {product: {"VolumeMultiple": 10.0, "SettlementPrice": 12.0}},
    )

    assert pnl.to_major() == pytest.approx(3.0 * (13.5 - 12.0) * 10.0)


def test_daily_mark_to_market_defaults_to_aggregate_money_formula():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = Ledger(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            settlement_price=10.0,
            equity_occupied=DataMoney.from_major(0.0, currency="CNY", use_minor_units=True),
        )
    })

    pnl = mark_to_market(
        ledger,
        config,
        {product: 10.005},
        {product: {"VolumeMultiple": 1.0, "SettlementPrice": 10.005}},
    )

    assert pnl.to_major() == pytest.approx(0.01)


def test_daily_mark_to_market_can_use_per_contract_price_point_policy():
    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = Ledger(strategy=strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=2.0,
            settlement_price=10.0,
            equity_occupied=DataMoney.from_major(0.0, currency="CNY", use_minor_units=True),
        )
    })

    pnl = mark_to_market(
        ledger,
        config,
        {product: 10.005},
        {product: {
            "VolumeMultiple": 1.0,
            "SettlementPrice": 10.005,
            "MoneyCalculationPolicy": "per_contract_price_point",
        }},
    )

    assert pnl.to_major() == pytest.approx(0.02)


def test_daily_mark_to_market_equity_flow_includes_intraday_floating_pnl():
    from tools.testers.backtest.modules.ledger_module import LedgerModule, _basic_equity

    product = _product()
    strategy = Strategy(alias="S")
    config = StrategyConfig(
        strategy=strategy,
        field_values={
            EngineModule.engine_mode: "auto",
            TradingRuleModule.accounting_mode: "Auto",
        },
    )
    ledger = Ledger(strategy=strategy, base_currency="CNY")
    ledger.set(_cash_ref(), DataMoney.from_major(1000.0, currency="CNY", use_minor_units=False))
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=3.0,
            lots=deque([
                Lot(quantity=3.0, entry_price=12.0, multiplier=10.0, is_today=False),
            ]),
            settlement_price=12.0,
            equity_occupied=DataMoney.from_major(36.0, currency="CNY", use_minor_units=False),
        )
    })
    account = BacktestRunState(strategy_configs={strategy: config}, ledgers={strategy: ledger})
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-03-10 10:00:00", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set(MarketDataModule.current_prices, {product: 13.5})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {"VolumeMultiple": 10.0, "SettlementPrice": 12.0}
    })

    _basic_equity(account, ctx)

    assert ctx.get_for(LedgerModule.equity, strategy) == pytest.approx(1000.0 + 36.0 + 45.0)


def test_daily_mark_to_market_close_realizes_from_last_settlement_not_original_entry():
    product = _product()
    config = _config(
        engine_mode="custom",
        accounting_mode="Custom",
        cost_basis_method="FIFO",
        daily_mark_to_market_enabled=True,
    )
    ledger = Ledger(strategy=config.strategy, base_currency="CNY")
    ledger.set(_positions_ref(), {
        product: ProductPosition(
            quantity=3.0,
            lots=deque([
                Lot(quantity=3.0, entry_price=12.0, multiplier=10.0, is_today=False),
            ]),
            settlement_price=12.0,
        )
    })

    realized = close_position(ledger, config, product, quantity=1.0, fill_price=13.5, multiplier=10.0)

    assert realized.to_major() == pytest.approx((13.5 - 12.0) * 10.0)


def _positions_ref():
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    return LedgerModule.positions


def _cash_ref():
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    return LedgerModule.cash

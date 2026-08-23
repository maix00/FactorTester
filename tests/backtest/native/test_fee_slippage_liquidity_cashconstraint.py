from __future__ import annotations

import uuid
from collections import deque

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.position import Lot, ProductPosition
from tools.testers.backtest.engines.native.ledger import LedgerState, ledger_identity
from tools.testers.backtest.engines.native.order import Order, OrderOffset
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.strategy_book import apply_order_sizing_policy, strategy_book_store_for
from tools.testers.backtest.modules.cash_pool import cash_for_ledger, set_cash_for_ledger_pool
from tools.testers.backtest.modules import cash_rescale as cash_rescale_impl
from tools.testers.backtest.modules.cash_rescale import _constrain_to_ledger_cash, constrain_order_batch_to_execution_cash
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.fee import FeeModule, _resolve_fee_cost, _resolve_fee_mode
from tools.testers.backtest.modules.custom_product import CustomProductModule
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.ledger_module import _apply_order_fill
from tools.testers.backtest.modules.market_data import MarketDataModule, _historical_fields_for_strategy
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.order_flow import record_order_terminal_state
from tools.testers.backtest.modules.slippage import SlippageModule, _apply_slippage
from tools.testers.backtest.modules.trading_rule import TradingRuleModule
from tools.testers.backtest.modules.volume_capacity import VolumeCapacityMode
from tools.data.types.data_money import DataMoney


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def _account_with_ledger(strategy: Strategy, config: StrategyConfig) -> BacktestRunState:
    account = BacktestRunState(strategy_configs={strategy: config})
    account.ledger_configs[ledger_identity(f"private:{strategy.alias}")] = LedgerConfig(
        fee_mode=config.get(FeeModule.fee_mode),
        fixed_fee_rate=config.get(FeeModule.fixed_fee_rate),
        accounting_mode=config.get(TradingRuleModule.accounting_mode),
        daily_mark_to_market_enabled=config.get(TradingRuleModule.daily_mark_to_market_enabled),
        cost_basis_method=config.get(TradingRuleModule.cost_basis_method),
    )
    ledger = account.ledger_for_strategy(strategy)
    set_cash_for_ledger_pool(account, ledger, DataMoney.from_major(1_000_000.0, currency="CNY", use_minor_units=False))
    ledger.set(LedgerModule.positions, {})
    return account


def _set_cash(account: BacktestRunState, ledger: LedgerState, amount: float) -> None:
    set_cash_for_ledger_pool(account, ledger, DataMoney.from_major(
        amount, currency="CNY", use_minor_units=False))


def _zero_fee_config(strategy: Strategy) -> StrategyConfig:
    return StrategyConfig(
        strategy=strategy,
        field_values={EngineModule.engine_mode: "basic"},
    )


def _cash_major(account: BacktestRunState, ledger: LedgerState) -> float:
    cash = cash_for_ledger(account, ledger)
    assert cash is not None
    return cash.to_major()


def test_fee_mode_zero_means_no_fee():
    s = Strategy(alias="S")
    p = _product()
    order = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s)
    config = StrategyConfig(strategy=s, field_values={
        EngineModule.engine_mode: "custom",
        FeeModule.fee_mode: "zero",
    })
    account = _account_with_ledger(s, config)
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}), drafts_by_strategy={s: [draft]})
    ctx.set(MarketDataModule.current_prices, {p: 10.0})

    _resolve_fee_cost(account, ctx)
    assert order.get("fee_cost") == 0.0


def test_fee_uses_effective_price_without_reading_sparse_execution_prices():
    s = Strategy(alias="effective-price")
    p = _product()
    order = Order(
        instrument=p,
        timestamp=pd.Timestamp("2024-01-01"),
        quantity=10.0,
        intent_quantity=10.0,
        strategy=s,
    )
    order.set("effective_price", 12.0)
    config = StrategyConfig(strategy=s, field_values={
        EngineModule.engine_mode: "custom",
        FeeModule.fee_mode: "fixed",
        FeeModule.fixed_fee_rate: 0.01,
    })
    account = _account_with_ledger(s, config)
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
        active_strategies=frozenset({s}), drafts_by_strategy={s: [draft]},
    )
    ctx.set(MarketDataModule.current_prices, {})
    ctx.set(MarketDataModule.current_historical_fields, {p: {"VolumeMultiple": 1.0}})

    _resolve_fee_cost(account, ctx)

    assert order.get("fee_cost") == pytest.approx(10.0 * 12.0 * 0.01)


def test_fee_mode_custom_uses_unified_product_field_overrides():
    s = Strategy(alias="S")
    p = _product()
    order = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s)
    config = StrategyConfig(strategy=s, field_values={
        EngineModule.engine_mode: "custom",
        FeeModule.fee_mode: "custom",
        CustomProductModule.custom_product_fields: [
            {"product": str(p), "field": "OpenRatioByMoney", "value": 0.01},
            {"product": str(p), "field": "OpenRatioByVolume", "value": 0.0},
            {"product": str(p), "field": "CloseRatioByMoney", "value": 0.0},
            {"product": str(p), "field": "CloseRatioByVolume", "value": 0.0},
            {"product": str(p), "field": "CloseTodayRatioByMoney", "value": 0.0},
            {"product": str(p), "field": "CloseTodayRatioByVolume", "value": 0.0},
            {"product": str(p), "field": "VolumeMultiple", "value": 1.0},
        ],
    })
    account = _account_with_ledger(s, config)
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}), drafts_by_strategy={s: [draft]})
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set_for(
        MarketDataModule.current_historical_fields,
            s,
                _historical_fields_for_strategy(
                    {p: {}},
                    config,
                    pd.Timestamp("2024-01-01"),
                    ledger_config=account.ledger_config_for(f"private:{s.alias}"),
                ),
    )

    _resolve_fee_cost(account, ctx)
    assert order.get("fee_cost") == pytest.approx(10.0 * 10.0 * 0.01)


def test_engine_mode_exact_uses_exact_fee_and_requires_historical_fields():
    s = Strategy(alias="S")
    p = _product()
    order = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s)
    config = StrategyConfig(strategy=s, field_values={EngineModule.engine_mode: "exact"})
    account = _account_with_ledger(s, config)
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}), drafts_by_strategy={s: [draft]})
    ctx.set(MarketDataModule.current_prices, {p: 10.0})

    assert config.get(FeeModule.fee_mode) is None
    assert _resolve_fee_mode(config) == "exact"
    with pytest.raises(KeyError):
        _resolve_fee_cost(account, ctx)


def test_fee_mode_auto_uses_historical_fields():
    s = Strategy(alias="S")
    p = _product()
    order = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s)
    config = StrategyConfig(strategy=s, field_values={EngineModule.engine_mode: "auto"})
    account = _account_with_ledger(s, config)
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}), drafts_by_strategy={s: [draft]})
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set(MarketDataModule.current_historical_fields, {
        p: {
            "OpenRatioByMoney": 0.002,
            "OpenRatioByVolume": 0.0,
            "CloseRatioByMoney": 0.0,
            "CloseRatioByVolume": 0.0,
            "CloseTodayRatioByMoney": 0.0,
            "CloseTodayRatioByVolume": 0.0,
            "VolumeMultiple": 1.0,
        },
    })

    _resolve_fee_cost(account, ctx)
    assert order.get("fee_cost") == pytest.approx(10.0 * 10.0 * 0.002)


def test_fee_mode_auto_splits_close_today_and_yesterday_from_position_lots():
    s = Strategy(alias="S")
    p = _product()
    order = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=-2.0, intent_quantity=-2.0, strategy=s)
    config = StrategyConfig(strategy=s, field_values={EngineModule.engine_mode: "auto"})
    account = _account_with_ledger(s, config)
    account.ledger_for_strategy(s).set(LedgerModule.positions, {
        p: ProductPosition(
            quantity=3.0,
            lots=deque([
                Lot(quantity=1.0, entry_price=8.0, multiplier=1.0, is_today=False),
                Lot(quantity=2.0, entry_price=9.0, multiplier=1.0, is_today=True),
            ]),
        )
    })
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}), drafts_by_strategy={s: [draft]})
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set(MarketDataModule.current_historical_fields, {
        p: {
            "OpenRatioByMoney": 0.0,
            "OpenRatioByVolume": 0.0,
            "CloseRatioByMoney": 0.01,
            "CloseRatioByVolume": 0.0,
            "CloseTodayRatioByMoney": 0.02,
            "CloseTodayRatioByVolume": 0.0,
            "VolumeMultiple": 1.0,
        },
    })

    _resolve_fee_cost(account, ctx)

    assert order.get("fee_close_yesterday_quantity") == pytest.approx(1.0)
    assert order.get("fee_close_today_quantity") == pytest.approx(1.0)
    assert order.get("fee_cost") == pytest.approx(10.0 * 1.0 * 0.01 + 10.0 * 1.0 * 0.02)


def test_explicit_close_today_offset_does_not_reclassify_from_position_snapshot():
    s = Strategy(alias="S")
    p = _product()
    order = Order(
        instrument=p, timestamp=pd.Timestamp("2024-01-01"),
        quantity=-1.0, intent_quantity=-1.0, strategy=s,
        offset=OrderOffset.CLOSE_TODAY,
    )
    config = StrategyConfig(strategy=s, field_values={EngineModule.engine_mode: "auto"})
    account = _account_with_ledger(s, config)
    account.ledger_for_strategy(s).set(LedgerModule.positions, {
        p: ProductPosition(
            quantity=1.0,
            lots=deque([
                Lot(quantity=1.0, entry_price=9.0, multiplier=1.0, is_today=False),
            ]),
        ),
    })
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={
            s: [EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)],
        },
    )
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set(MarketDataModule.current_historical_fields, {
        p: {
            "OpenRatioByMoney": 0.0,
            "OpenRatioByVolume": 0.0,
            "CloseRatioByMoney": 0.01,
            "CloseRatioByVolume": 0.0,
            "CloseTodayRatioByMoney": 0.02,
            "CloseTodayRatioByVolume": 0.0,
            "VolumeMultiple": 1.0,
        },
    })

    _resolve_fee_cost(account, ctx)

    assert order.get("fee_close_today_quantity") == 1.0
    assert order.get("fee_close_yesterday_quantity") == 0.0
    assert order.get("fee_cost") == pytest.approx(0.2)


@pytest.mark.parametrize("fee_mode", ["custom", "exact"])
def test_fee_mode_lot_aware_modes_split_close_today_and_yesterday_from_position_lots(fee_mode: str):
    s = Strategy(alias="S")
    p = _product()
    order = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=-2.0, intent_quantity=-2.0, strategy=s)
    config = StrategyConfig(strategy=s, field_values={
        EngineModule.engine_mode: "custom",
        FeeModule.fee_mode: fee_mode,
        TradingRuleModule.accounting_mode: "Custom",
        TradingRuleModule.cost_basis_method: "FIFO",
        TradingRuleModule.daily_mark_to_market_enabled: True,
    })
    account = _account_with_ledger(s, config)
    account.ledger_for_strategy(s).set(LedgerModule.positions, {
        p: ProductPosition(
            quantity=3.0,
            lots=deque([
                Lot(quantity=1.0, entry_price=8.0, multiplier=1.0, is_today=False),
                Lot(quantity=2.0, entry_price=9.0, multiplier=1.0, is_today=True),
            ]),
        )
    })
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}), drafts_by_strategy={s: [draft]})
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set(MarketDataModule.current_historical_fields, {
        p: {
            "OpenRatioByMoney": 0.0,
            "OpenRatioByVolume": 0.0,
            "CloseRatioByMoney": 0.01,
            "CloseRatioByVolume": 0.0,
            "CloseTodayRatioByMoney": 0.02,
            "CloseTodayRatioByVolume": 0.0,
            "VolumeMultiple": 1.0,
            "CostBasisMethod": "FIFO",
            "DailyMarkToMarketEnabled": True,
        },
    })

    _resolve_fee_cost(account, ctx)

    assert order.get("fee_close_yesterday_quantity") == pytest.approx(1.0)
    assert order.get("fee_close_today_quantity") == pytest.approx(1.0)
    assert order.get("fee_cost") == pytest.approx(10.0 * 1.0 * 0.01 + 10.0 * 1.0 * 0.02)


def test_fee_mode_close_yesterday_overrides_today_lot_markers():
    s = Strategy(alias="S")
    p = _product()
    order = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=-1.0, intent_quantity=-1.0, strategy=s)
    config = StrategyConfig(strategy=s, field_values={
        EngineModule.engine_mode: "custom",
        FeeModule.fee_mode: "close_yesterday",
    })
    account = _account_with_ledger(s, config)
    account.ledger_for_strategy(s).set(LedgerModule.positions, {
        p: ProductPosition(
            quantity=1.0,
            lots=deque([Lot(quantity=1.0, entry_price=9.0, multiplier=1.0, is_today=True)]),
        )
    })
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}), drafts_by_strategy={s: [draft]})
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set(MarketDataModule.current_historical_fields, {
        p: {
            "OpenRatioByMoney": 0.0,
            "OpenRatioByVolume": 0.0,
            "CloseRatioByMoney": 0.01,
            "CloseRatioByVolume": 0.0,
            "CloseTodayRatioByMoney": 0.02,
            "CloseTodayRatioByVolume": 0.0,
            "VolumeMultiple": 1.0,
        },
    })

    _resolve_fee_cost(account, ctx)

    assert order.get("fee_close_yesterday_quantity") == pytest.approx(1.0)
    assert order.get("fee_close_today_quantity") == pytest.approx(0.0)
    assert order.get("fee_cost") == pytest.approx(10.0 * 0.01)


def test_fee_mode_auto_uses_configured_lot_close_order_for_today_split():
    s = Strategy(alias="S")
    p = _product()
    order = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=-1.0, intent_quantity=-1.0, strategy=s)
    config = StrategyConfig(strategy=s, field_values={
        EngineModule.engine_mode: "custom",
        TradingRuleModule.accounting_mode: "Custom",
        TradingRuleModule.cost_basis_method: "LIFO",
        TradingRuleModule.daily_mark_to_market_enabled: True,
        FeeModule.fee_mode: "auto",
    })
    account = _account_with_ledger(s, config)
    account.ledger_for_strategy(s).set(LedgerModule.positions, {
        p: ProductPosition(
            quantity=2.0,
            lots=deque([
                Lot(quantity=1.0, entry_price=8.0, multiplier=1.0, is_today=False),
                Lot(quantity=1.0, entry_price=9.0, multiplier=1.0, is_today=True),
            ]),
        )
    })
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}), drafts_by_strategy={s: [draft]})
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set(MarketDataModule.current_historical_fields, {
        p: {
            "OpenRatioByMoney": 0.0,
            "OpenRatioByVolume": 0.0,
            "CloseRatioByMoney": 0.01,
            "CloseRatioByVolume": 0.0,
            "CloseTodayRatioByMoney": 0.02,
            "CloseTodayRatioByVolume": 0.0,
            "VolumeMultiple": 1.0,
        },
    })

    _resolve_fee_cost(account, ctx)

    assert order.get("fee_close_yesterday_quantity") == pytest.approx(0.0)
    assert order.get("fee_close_today_quantity") == pytest.approx(1.0)
    assert order.get("fee_cost") == pytest.approx(10.0 * 0.02)


def test_fee_mode_auto_without_fee_fields_falls_back_to_zero_with_high_risk_runtime_info():
    s = Strategy(alias="S")
    p = _product()
    order = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s)
    config = StrategyConfig(strategy=s, field_values={EngineModule.engine_mode: "auto"})
    account = _account_with_ledger(s, config)
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}), drafts_by_strategy={s: [draft]})
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set(MarketDataModule.current_historical_fields, {p: {"VolumeMultiple": 10.0}})

    _resolve_fee_cost(account, ctx)

    assert order.get("fee_cost") == 0.0
    assert len(account.runtime_info_rows) == 1
    warning = account.runtime_info_rows[0]
    assert warning["code"] == "fee_auto_missing_history"
    assert warning["level"] == "error"
    assert warning["status"] == "高风险回退"
    assert warning["details"]["strategy"] == "S"
    assert "OpenRatioByMoney" in warning["details"]["missing_fields"]


def test_fee_mode_zero_records_explicit_zero_fee_assumption():
    s = Strategy(alias="S")
    p = _product()
    order = Order(
        instrument=p, timestamp=pd.Timestamp("2024-01-01"),
        quantity=1.0, intent_quantity=1.0, strategy=s,
    )
    config = StrategyConfig(strategy=s, field_values={
        EngineModule.engine_mode: "custom", FeeModule.fee_mode: "zero",
    })
    account = _account_with_ledger(s, config)
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
        active_strategies=frozenset({s}), drafts_by_strategy={
            s: [EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)],
        },
    )
    ctx.set(MarketDataModule.current_prices, {p: 10.0})

    _resolve_fee_cost(account, ctx)

    assert account.runtime_info_rows[0]["code"] == "fee_zero_mode"
    assert account.runtime_info_rows[0]["level"] == "warning"
    assert account.runtime_info_rows[0]["status"] == "研究假设"


def test_slippage_zero_means_unadjusted_price():
    s = Strategy(alias="S")
    p = _product()
    order = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s)
    config = StrategyConfig(strategy=s, field_values={SlippageModule.slippage_mode: "none"})
    account = BacktestRunState(strategy_configs={s: config})
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                       active_strategies=frozenset({s}), drafts_by_strategy={s: [draft]})
    ctx.set(MarketDataModule.current_prices, {p: 10.0})

    _apply_slippage(account, ctx)
    assert order.get("effective_price") == pytest.approx(10.0)


def test_slippage_uses_effective_price_without_requiring_current_market_price():
    s = Strategy(alias="S")
    p = _product()
    order = Order(
        instrument=p,
        timestamp=pd.Timestamp("2024-01-01"),
        quantity=10.0,
        intent_quantity=10.0,
        strategy=s,
    )
    order.set("effective_price", 12.0)
    config = StrategyConfig(
        strategy=s,
        field_values={SlippageModule.slippage_mode: "none"},
    )
    account = BacktestRunState(strategy_configs={s: config})
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [draft]},
    )
    ctx.set(MarketDataModule.current_prices, {})

    _apply_slippage(account, ctx)

    assert order.get("effective_price") == pytest.approx(12.0)


def test_slippage_requires_current_market_price_when_effective_price_is_missing():
    s = Strategy(alias="S")
    p = _product()
    order = Order(
        instrument=p,
        timestamp=pd.Timestamp("2024-01-01"),
        quantity=10.0,
        intent_quantity=10.0,
        strategy=s,
    )
    config = StrategyConfig(
        strategy=s,
        field_values={SlippageModule.slippage_mode: "none"},
    )
    account = BacktestRunState(strategy_configs={s: config})
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [draft]},
    )
    ctx.set(MarketDataModule.current_prices, {})

    with pytest.raises(KeyError) as exc_info:
        _apply_slippage(account, ctx)

    assert exc_info.value.args == (p,)


def test_slippage_worsens_buy_and_sell_price_in_opposite_directions():
    s = Strategy(alias="S")
    p = _product()
    buy = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s)
    sell = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=-10.0, intent_quantity=-10.0, strategy=s)
    config = StrategyConfig(strategy=s, field_values={
        SlippageModule.slippage_mode: "fixed_bps", SlippageModule.slippage_bps: 100.0,  # 1%
    })
    account = BacktestRunState(strategy_configs={s: config})

    for order in (buy, sell):
        draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s, order)
        ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
                           active_strategies=frozenset({s}), drafts_by_strategy={s: [draft]})
        ctx.set(MarketDataModule.current_prices, {p: 10.0})
        _apply_slippage(account, ctx)

    assert buy.get("effective_price") == pytest.approx(10.1)   # worse (higher) for buys
    assert sell.get("effective_price") == pytest.approx(9.9)   # worse (lower) for sells


def test_volume_capacity_uncapped_when_mode_infinite():
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={VolumeCapacityMode.liquidity_mode: "infinite"})
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.volume, {p: 100.0})

    capped = apply_order_sizing_policy(account, ctx, s, {p: 99999.0})
    assert capped[p] == 99999.0


def test_order_sizing_does_not_consume_execution_volume_capacity():
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={
        VolumeCapacityMode.liquidity_mode: "volume_participation", VolumeCapacityMode.participation_rate: 0.1,
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.volume, {p: 100.0})

    sized = apply_order_sizing_policy(account, ctx, s, {p: 50.0})
    assert sized[p] == pytest.approx(50.0)


def test_order_sizing_does_not_read_signal_bar_volume_table():
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={
        VolumeCapacityMode.liquidity_mode: "volume_participation", VolumeCapacityMode.participation_rate: 0.1,
    })
    account = BacktestRunState(strategy_configs={s: config})
    timestamp = pd.Timestamp("2024-01-02 09:01")
    volume_table = pd.DataFrame(
        {p: [100.0, 300.0]},
        index=[pd.Timestamp("2024-01-02 09:00"), timestamp],
    )
    account.market_data_store.volume_table = volume_table
    ctx = FlowContext(timestamp=timestamp, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.volume, volume_table)

    sized = apply_order_sizing_policy(account, ctx, s, {p: 50.0})
    assert sized[p] == pytest.approx(50.0)


def test_order_sizing_defers_missing_volume_validation_to_execution():
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={
        VolumeCapacityMode.liquidity_mode: "volume_participation", VolumeCapacityMode.participation_rate: 0.1,
    })
    account = BacktestRunState(strategy_configs={s: config})
    account.market_data_store.volume_table = pd.DataFrame({p: [100.0]}, index=[pd.Timestamp("2023-12-29 15:00")])
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.volume, {})

    sized = apply_order_sizing_policy(account, ctx, s, {p: 50.0})
    assert sized[p] == 50.0
    assert not account.runtime_info_rows


def test_order_sizing_volume_capacity_does_not_require_volume_for_zero_delta():
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={
        VolumeCapacityMode.liquidity_mode: "volume_participation", VolumeCapacityMode.participation_rate: 0.1,
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.volume, {})

    capped = apply_order_sizing_policy(account, ctx, s, {p: 0.0})

    assert capped[p] == 0.0


def test_order_sizing_preserves_excess_for_execution_lifecycle():
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={
        VolumeCapacityMode.liquidity_mode: "volume_participation", VolumeCapacityMode.participation_rate: 0.1,
    })
    account = BacktestRunState(strategy_configs={s: config})
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.volume, {p: 100.0})

    sized = apply_order_sizing_policy(account, ctx, s, {p: -50.0})
    assert sized[p] == pytest.approx(-50.0)


def test_cash_constraint_haircuts_buy_orders_proportionally():
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    ledger = LedgerState(strategy=s, base_currency="CNY")
    account = BacktestRunState(ledgers={f"private:{s.alias}": ledger}, strategy_configs={s: _zero_fee_config(s)})
    _set_cash(account, ledger, 100.0)

    buy1 = Order(instrument=p1, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s)
    buy2 = Order(instrument=p2, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {p1: 10.0, p2: 10.0})  # total cost 200 > 100 cash
    ctx.set_for(OrderConstructModule.orders, s, [buy1, buy2])

    _constrain_to_ledger_cash(account, ctx)
    assert buy1.quantity == pytest.approx(5.0)  # scaled by 100/200 = 0.5
    assert buy2.quantity == pytest.approx(5.0)


def test_cash_constraint_does_not_touch_sell_orders():
    s = Strategy(alias="S")
    p = _product()
    ledger = LedgerState(strategy=s, base_currency="CNY")
    account = BacktestRunState(ledgers={f"private:{s.alias}": ledger}, strategy_configs={s: _zero_fee_config(s)})
    _set_cash(account, ledger, 0.0)

    sell = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=-10.0, intent_quantity=-10.0, strategy=s)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set_for(OrderConstructModule.orders, s, [sell])

    _constrain_to_ledger_cash(account, ctx)
    assert sell.quantity == -10.0


def test_cash_constraint_counts_same_batch_sell_proceeds_before_scaling_buys():
    s = Strategy(alias="S")
    p_sell, p_buy = _product(), _product()
    ledger = LedgerState(strategy=s, base_currency="CNY")
    account = BacktestRunState(ledgers={f"private:{s.alias}": ledger}, strategy_configs={s: _zero_fee_config(s)})
    _set_cash(account, ledger, 0.0)

    sell = Order(instrument=p_sell, timestamp=pd.Timestamp("2024-01-01"), quantity=-10.0, intent_quantity=-10.0, strategy=s)
    buy = Order(instrument=p_buy, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {p_sell: 10.0, p_buy: 10.0})
    ctx.set_for(OrderConstructModule.orders, s, [sell, buy])

    _constrain_to_ledger_cash(account, ctx)

    assert sell.quantity == pytest.approx(-10.0)
    assert buy.quantity == pytest.approx(10.0)


def test_cash_constraint_isolates_strategies():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")
    p = _product()
    l1 = LedgerState(strategy=s1, base_currency="CNY", ledger_id="private:A")
    l2 = LedgerState(strategy=s2, base_currency="CNY", ledger_id="private:B")
    account = BacktestRunState(
        ledgers={"private:A": l1, "private:B": l2},
        strategy_configs={s1: _zero_fee_config(s1), s2: _zero_fee_config(s2)},
    )
    _set_cash(account, l1, 10.0)
    _set_cash(account, l2, 1000.0)

    buy1 = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s1)
    buy2 = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s2)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(), active_strategies=frozenset({s1, s2}))
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set_for(OrderConstructModule.orders, s1, [buy1])
    ctx.set_for(OrderConstructModule.orders, s2, [buy2])

    _constrain_to_ledger_cash(account, ctx)
    assert buy1.quantity == pytest.approx(1.0)   # 10 cash / 100 cost
    assert buy2.quantity == pytest.approx(10.0)  # untouched, plenty of cash


def test_cash_constraint_combines_buys_across_strategies_sharing_one_ledger():
    """Two strategies routed to the same shared ledger_id draw on the
    same pool of cash -- each independently assuming it can spend the whole
    balance (the pre-fix behavior) would let their combined spend exceed the
    ledger's actual cash."""
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")
    p = _product()
    ledger = LedgerState(strategy=s1, base_currency="CNY", ledger_id="shared-book")
    account = BacktestRunState(
        ledgers={"shared-book": ledger},
        strategy_configs={s1: _zero_fee_config(s1), s2: _zero_fee_config(s2)},
    )
    _set_cash(account, ledger, 100.0)
    strategy_book_store = strategy_book_store_for(account)
    strategy_book_store.register_strategy_ledgers(s1, ("shared-book",), default_ledger_id="shared-book")
    strategy_book_store.register_strategy_ledgers(s2, ("shared-book",), default_ledger_id="shared-book")

    buy1 = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s1)
    buy2 = Order(instrument=p, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s2)
    ctx = FlowContext(timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(), active_strategies=frozenset({s1, s2}))
    ctx.set(MarketDataModule.current_prices, {p: 10.0})  # each order costs 100, combined cost 200 > 100 cash
    ctx.set_for(OrderConstructModule.orders, s1, [buy1])
    ctx.set_for(OrderConstructModule.orders, s2, [buy2])

    _constrain_to_ledger_cash(account, ctx)

    # Combined post-haircut spend must not exceed the shared ledger's cash.
    assert buy1.quantity == pytest.approx(5.0)
    assert buy2.quantity == pytest.approx(5.0)
    assert (buy1.quantity + buy2.quantity) * 10.0 == pytest.approx(100.0)


def test_signal_cash_constraint_combines_distinct_ledgers_in_one_cash_pool() -> None:
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")
    p1, p2 = _product(), _product()
    l1 = LedgerState(strategy=s1, base_currency="CNY", ledger_id="book-a")
    l2 = LedgerState(strategy=s2, base_currency="CNY", ledger_id="book-b")
    account = BacktestRunState(
        ledgers={"book-a": l1, "book-b": l2},
        strategy_configs={s1: _zero_fee_config(s1), s2: _zero_fee_config(s2)},
    )
    store = strategy_book_store_for(account)
    store.register_strategy_ledgers(
        s1, ("book-a",), default_ledger_id="book-a",
        cash_pool_ids_by_ledger={"book-a": "shared-pool"},
    )
    store.register_strategy_ledgers(
        s2, ("book-b",), default_ledger_id="book-b",
        cash_pool_ids_by_ledger={"book-b": "shared-pool"},
    )
    _set_cash(account, l1, 100.0)
    buy1 = Order(instrument=p1, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s1)
    buy2 = Order(instrument=p2, timestamp=pd.Timestamp("2024-01-01"), quantity=10.0, intent_quantity=10.0, strategy=s2)
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
        active_strategies=frozenset({s1, s2}),
    )
    ctx.set(MarketDataModule.current_prices, {p1: 10.0, p2: 10.0})
    ctx.set_for(OrderConstructModule.orders, s1, [buy1])
    ctx.set_for(OrderConstructModule.orders, s2, [buy2])

    _constrain_to_ledger_cash(account, ctx)

    assert buy1.quantity + buy2.quantity == pytest.approx(10.0)


def test_signal_cash_constraint_uses_incremental_futures_margin_not_full_notional():
    s = Strategy(alias="margin")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={EngineModule.engine_mode: "custom"})
    account = BacktestRunState(strategy_configs={s: config})
    ledger = account.ledger_for_strategy(s)
    account.ledger_configs[ledger_identity("private:margin")] = LedgerConfig(
        fee_mode="zero", margin_mode="fixed", fixed_margin_ratio=0.10,
    )
    _set_cash(account, ledger, 100.0)
    ledger.set(LedgerModule.positions, {p: ProductPosition(quantity=0.0)})
    order = Order(
        instrument=p, timestamp=pd.Timestamp("2024-01-01"),
        quantity=10.0, intent_quantity=10.0, strategy=s,
    )
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
        active_strategies=frozenset({s}),
    )
    ctx.set(MarketDataModule.current_prices, {p: 100.0})
    ctx.set_for(OrderConstructModule.orders, s, [order])

    _constrain_to_ledger_cash(account, ctx)

    assert order.quantity == pytest.approx(10.0)


def test_signal_cash_constraint_limits_short_open_by_margin() -> None:
    s = Strategy(alias="short-margin")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={EngineModule.engine_mode: "custom"})
    account = BacktestRunState(strategy_configs={s: config})
    ledger = account.ledger_for_strategy(s)
    account.ledger_configs[ledger_identity("private:short-margin")] = LedgerConfig(
        fee_mode="zero", margin_mode="fixed", fixed_margin_ratio=0.10,
    )
    _set_cash(account, ledger, 80.0)
    ledger.set(LedgerModule.positions, {p: ProductPosition(quantity=0.0)})
    order = Order(
        instrument=p, timestamp=pd.Timestamp("2024-01-01"),
        quantity=-10.0, intent_quantity=-10.0, strategy=s,
    )
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
        active_strategies=frozenset({s}),
    )
    ctx.set(MarketDataModule.current_prices, {p: 100.0})
    ctx.set_for(OrderConstructModule.orders, s, [order])

    _constrain_to_ledger_cash(account, ctx)

    assert order.quantity == pytest.approx(-8.0)


def test_signal_cash_constraint_never_scales_margin_reduction() -> None:
    s = Strategy(alias="reduce-margin")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={EngineModule.engine_mode: "custom"})
    account = BacktestRunState(strategy_configs={s: config})
    ledger = account.ledger_for_strategy(s)
    account.ledger_configs[ledger_identity("private:reduce-margin")] = LedgerConfig(
        fee_mode="zero", margin_mode="fixed", fixed_margin_ratio=0.10,
    )
    _set_cash(account, ledger, 0.0)
    ledger.set(LedgerModule.positions, {p: ProductPosition(
        quantity=10.0, average_cost=100.0,
        margin_reserved=DataMoney.from_major(100.0, currency="CNY", use_minor_units=False),
    )})
    order = Order(
        instrument=p, timestamp=pd.Timestamp("2024-01-01"),
        quantity=-10.0, intent_quantity=-10.0, strategy=s,
    )
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
        active_strategies=frozenset({s}),
    )
    ctx.set(MarketDataModule.current_prices, {p: 100.0})
    ctx.set_for(OrderConstructModule.orders, s, [order])

    _constrain_to_ledger_cash(account, ctx)

    assert order.quantity == pytest.approx(-10.0)


def test_execution_cash_constraint_uses_actual_execution_price_before_ledger_update():
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={EngineModule.engine_mode: "basic"})
    account = BacktestRunState(strategy_configs={s: config})
    ledger = account.ledger_for_strategy(s)
    _set_cash(account, ledger, 100.0)
    ledger.set(LedgerModule.positions, {p: ProductPosition(quantity=0.0)})
    order = Order(
        instrument=p,
        timestamp=pd.Timestamp("2024-01-02"),
        quantity=1.0,
        intent_quantity=1.0,
        strategy=s,
    )
    order.set("effective_price", 200.0)
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-02"), s, order)
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-02"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [draft]},
    )
    ctx.set(MarketDataModule.current_prices, {p: 200.0})

    constrain_order_batch_to_execution_cash(account, ctx)
    _apply_order_fill(account, ctx)

    assert order.quantity == pytest.approx(0.5)
    assert _cash_major(account, ledger) == pytest.approx(0.0)
    assert ledger.get(LedgerModule.positions)[p].quantity == pytest.approx(0.5)


def test_execution_cash_constraint_fast_path_skips_margin_simulation_when_bound_fits(monkeypatch):
    s = Strategy(alias="S")
    p = _product()
    config = StrategyConfig(strategy=s, field_values={
        EngineModule.engine_mode: "custom",
    })
    account = _account_with_ledger(s, config)
    ledger = account.ledger_for_strategy(s)
    account.ledger_configs[ledger_identity(f"private:{s.alias}")] = LedgerConfig(
        margin_mode="fixed",
        fixed_margin_ratio=0.1,
    )
    _set_cash(account, ledger, 1_000.0)
    ledger.set(LedgerModule.positions, {p: ProductPosition(quantity=0.0)})
    order = Order(
        instrument=p,
        timestamp=pd.Timestamp("2024-01-02"),
        quantity=1.0,
        intent_quantity=1.0,
        strategy=s,
    )
    order.set("effective_price", 100.0)
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-02"), s, order)
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-02"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [draft]},
    )
    ctx.set(MarketDataModule.current_prices, {p: 100.0})

    def fail_clone(_positions):
        raise AssertionError("exact simulation should be skipped when conservative cash bound fits")

    monkeypatch.setattr(cash_rescale_impl, "_clone_positions_for_cash_check", fail_clone)

    constrain_order_batch_to_execution_cash(account, ctx)

    assert order.quantity == pytest.approx(1.0)
    assert order.get("reject_reason") is None


def test_order_flow_records_fee_slippage_ledger_and_final_status():
    s = Strategy(alias="S")
    p = _product()
    order = Order(
        instrument=p,
        timestamp=pd.Timestamp("2024-01-01 09:01"),
        quantity=10.0,
        intent_quantity=10.0,
        strategy=s,
        order_id="order-1",
    )
    config = StrategyConfig(strategy=s, field_values={
        SlippageModule.slippage_mode: "fixed_bps",
        SlippageModule.slippage_bps: 100.0,
        EngineModule.engine_mode: "custom",
        FeeModule.fee_mode: "fixed",
        FeeModule.fixed_fee_rate: 0.01,
    })
    account = _account_with_ledger(s, config)
    _set_cash(account, account.ledger_for_strategy(s), 10_000.0)
    draft = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01 09:01"), s, order)
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01 09:01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({s}),
        drafts_by_strategy={s: [draft]},
    )
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set(MarketDataModule.current_historical_fields, {p: {"VolumeMultiple": 1.0}})

    _apply_slippage(account, ctx)
    _resolve_fee_cost(account, ctx)
    _apply_order_fill(account, ctx)
    record_order_terminal_state(account, ctx)

    records = account.order_flow_store.records_for_order("order-1")
    assert [row["step"] for row in records] == [
        "slippage",
        "fee",
        "ledger_update",
        "order_terminal",
    ]
    assert records[-1]["status"] == "filled"

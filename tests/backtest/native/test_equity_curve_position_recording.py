from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.data.types.data_money import DataMoney
from tools.products.Product import Product
from tools.testers.backtest.engines.native.ledger import BacktestRunState, Ledger, ProductPosition, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.equity_curve import (
    _record_equity, margin_curve_for, notional_curve_for, position_curve_for,
)
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def test_records_positions_and_notional_alongside_equity():
    s = Strategy(alias="S")
    p1, p2 = _product(), _product()
    ledger = Ledger(strategy=s, base_currency="CNY")
    ledger.set(LedgerModule.positions, {
        p1: ProductPosition(quantity=10.0),
        p2: ProductPosition(quantity=0.0),  # zero position -- should be omitted
    })
    account = BacktestRunState(ledgers={f"private:{s.alias}": ledger}, strategy_configs={s: StrategyConfig(strategy=s)})
    t = pd.Timestamp("2024-01-01")
    ctx = FlowContext(timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {p1: 20.0, p2: 5.0})
    ctx.set_for(LedgerModule.equity, s, 1000.0)

    _record_equity(account, ctx)

    positions = position_curve_for(account, s)
    notional = notional_curve_for(account, s)
    assert positions[t.isoformat()] == {str(p1): 10.0}  # p2 omitted, zero quantity
    assert notional[t.isoformat()] == {str(p1): pytest.approx(200.0)}


def test_margin_curve_is_none_when_never_tracked():
    s = Strategy(alias="S")
    p = _product()
    ledger = Ledger(strategy=s, base_currency="CNY")
    ledger.set(LedgerModule.positions, {p: ProductPosition(quantity=5.0)})  # equity_occupied=None
    account = BacktestRunState(ledgers={f"private:{s.alias}": ledger}, strategy_configs={s: StrategyConfig(strategy=s)})
    t = pd.Timestamp("2024-01-01")
    ctx = FlowContext(timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set_for(LedgerModule.equity, s, 1000.0)

    _record_equity(account, ctx)

    assert margin_curve_for(account, s) is None


def test_margin_curve_present_when_equity_occupied_is_tracked():
    s = Strategy(alias="S")
    p = _product()
    ledger = Ledger(strategy=s, base_currency="CNY")
    ledger.set(LedgerModule.positions, {
        p: ProductPosition(quantity=5.0, equity_occupied=DataMoney.from_major(
            50.0, currency="CNY", use_minor_units=False)),
    })
    account = BacktestRunState(ledgers={f"private:{s.alias}": ledger}, strategy_configs={s: StrategyConfig(strategy=s)})
    t = pd.Timestamp("2024-01-01")
    ctx = FlowContext(timestamp=t, event_queue=EventQueue(), active_strategies=frozenset({s}))
    ctx.set(MarketDataModule.current_prices, {p: 10.0})
    ctx.set_for(LedgerModule.equity, s, 1000.0)

    _record_equity(account, ctx)

    margin = margin_curve_for(account, s)
    assert margin is not None
    assert margin[t.isoformat()] == {str(p): pytest.approx(50.0)}

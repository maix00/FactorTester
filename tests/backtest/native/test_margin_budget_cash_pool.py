from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.data.types.data_money import DataMoney
from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import CashPoolConfig, LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.ledger import LedgerState, ledger_identity
from tools.testers.backtest.engines.native.position import ProductPosition
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.cash_pool import (
    cash_pool_cash_major,
    cash_pool_store_for,
    set_cash_for_ledger_pool,
)
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.ledger_impl.valuation import cash_pool_equity
from tools.testers.backtest.modules.margin_budget import MarginBudgetModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.strategy_book import strategy_book_store_for
from tools.testers.backtest.modules.target import TargetStrategyModule, TargetWeightIntent


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def test_shared_cash_pool_gets_one_combined_eighty_percent_budget() -> None:
    a, b = Strategy(alias="A"), Strategy(alias="B")
    pa, pb = _product(), _product()
    ledger_a = LedgerState(strategy=a, base_currency="CNY", ledger_id="book-a")
    ledger_b = LedgerState(strategy=b, base_currency="CNY", ledger_id="book-b")
    legacy_budget_settings = {
        MarginBudgetModule.target_margin_utilization: 0.80,
        MarginBudgetModule.max_margin_utilization: 0.85,
    }
    state = BacktestRunState(
        ledgers={"book-a": ledger_a, "book-b": ledger_b},
        strategy_configs={
            a: StrategyConfig(strategy=a, field_values=dict(legacy_budget_settings)),
            b: StrategyConfig(strategy=b, field_values=dict(legacy_budget_settings)),
        },
    )
    store = strategy_book_store_for(state)
    store.register_strategy_ledgers(
        a, ("book-a",), default_ledger_id="book-a",
        cash_pool_ids_by_ledger={"book-a": "pool"},
    )
    store.register_strategy_ledgers(
        b, ("book-b",), default_ledger_id="book-b",
        cash_pool_ids_by_ledger={"book-b": "pool"},
    )
    for ledger_id in ("book-a", "book-b"):
        state.ledger_configs[ledger_identity(ledger_id)] = LedgerConfig(
            margin_mode="fixed", fixed_margin_ratio=0.10,
        )
    set_cash_for_ledger_pool(state, ledger_a, DataMoney.from_major(
        100_000_000.0, currency="CNY", use_minor_units=True,
    ))
    ctx = FlowContext(
        timestamp=pd.Timestamp("2025-01-02"), event_queue=EventQueue(),
        active_strategies=frozenset({a, b}),
    )
    ctx.set(MarketDataModule.current_prices, {pa: 100.0, pb: 100.0})
    for strategy, product in ((a, pa), (b, pb)):
        ctx.set_for(LedgerModule.equity, strategy, 100_000_000.0)
        ctx.set_for(MarketDataModule.current_historical_fields, strategy, {
            product: {"VolumeMultiple": 10.0},
        })
        ctx.set_for(TargetStrategyModule.trade_intent, strategy, TargetWeightIntent({product: 1.0}))
        ctx.set_for(TargetStrategyModule.target_weights, strategy, {product: 1.0})

    MarginBudgetModule.apply_target_margin_budget.compute(state, ctx)

    combined_gross = sum(
        abs(next(iter(ctx.get_for(TargetStrategyModule.target_weights, strategy).values())))
        for strategy in (a, b)
    )
    assert combined_gross == pytest.approx(8.0)
    assert ctx.get(MarginBudgetModule.projected_margin)["pool"] == pytest.approx(80_000_000.0)


def test_cash_pool_values_mixed_account_currencies_with_cached_timestamped_fx() -> None:
    a, b = Strategy(alias="A"), Strategy(alias="B")
    ledger_a = LedgerState(strategy=a, base_currency="CNY", ledger_id="book-a")
    ledger_b = LedgerState(strategy=b, base_currency="USD", ledger_id="book-b")
    state = BacktestRunState(ledgers={"book-a": ledger_a, "book-b": ledger_b})
    store = strategy_book_store_for(state)
    for strategy, ledger_id in ((a, "book-a"), (b, "book-b")):
        store.register_strategy_ledgers(
            strategy, (ledger_id,), default_ledger_id=ledger_id,
            cash_pool_ids_by_ledger={ledger_id: "pool"},
        )
    cash_pool_store_for(state).config_by_pool["pool"] = CashPoolConfig(
        base_currency="CNY", currency_conversion_fee_rate=0.01,
    )
    set_cash_for_ledger_pool(
        state, ledger_a, DataMoney.from_major(100.0, currency="CNY", use_minor_units=False),
    )
    set_cash_for_ledger_pool(
        state, ledger_b, DataMoney.from_major(10.0, currency="USD", use_minor_units=False),
    )
    calls: list[tuple[str, str, object]] = []

    def rates(source: str, target: str, timestamp: object) -> float:
        calls.append((source, target, timestamp))
        return 7.0

    timestamp = pd.Timestamp("2025-01-02 09:30", tz="Asia/Shanghai")
    assert cash_pool_cash_major(
        state, ledger_a, timestamp=timestamp, rate_provider=rates,
    ) == pytest.approx(170.0)
    assert cash_pool_cash_major(
        state, ledger_a, timestamp=timestamp, rate_provider=rates,
    ) == pytest.approx(170.0)
    assert cash_pool_cash_major(
        state, ledger_a, timestamp=timestamp, rate_provider=rates,
        include_conversion_cost=True,
    ) == pytest.approx(169.3)
    assert calls == [("USD", "CNY", timestamp)]


def test_cash_pool_mixed_currency_valuation_fails_when_timestamped_fx_is_missing() -> None:
    strategy = Strategy(alias="USD")
    ledger = LedgerState(strategy=strategy, base_currency="USD", ledger_id="usd-account")
    state = BacktestRunState(ledgers={"usd-account": ledger})
    strategy_book_store_for(state).register_strategy_ledgers(
        strategy, ("usd-account",), default_ledger_id="usd-account",
        cash_pool_ids_by_ledger={"usd-account": "pool"},
    )
    cash_pool_store_for(state).config_by_pool["pool"] = CashPoolConfig(base_currency="CNY")
    set_cash_for_ledger_pool(
        state, ledger, DataMoney.from_major(10.0, currency="USD", use_minor_units=False),
    )
    timestamp = pd.Timestamp("2025-01-02 09:30")

    with pytest.raises(ValueError, match=r"Missing FX rate USD->CNY at 2025-01-02 09:30"):
        cash_pool_cash_major(
            state, ledger, timestamp=timestamp,
            rate_provider=lambda _source, _target, _timestamp: None,
        )


def test_cash_pool_equity_converts_each_accounts_positions_to_pool_base_currency() -> None:
    cny_strategy, usd_strategy = Strategy(alias="CNY"), Strategy(alias="USD")
    cny_product = Product(name=f"CNY-{uuid.uuid4().hex}", point_value=1, currency="CNY")
    usd_product = Product(name=f"USD-{uuid.uuid4().hex}", point_value=1, currency="USD")
    cny_ledger = LedgerState(strategy=cny_strategy, base_currency="CNY", ledger_id="cny")
    usd_ledger = LedgerState(strategy=usd_strategy, base_currency="USD", ledger_id="usd")
    cny_ledger.set(LedgerModule.positions, {
        cny_product: ProductPosition(quantity=2.0, average_cost=5.0),
    })
    usd_ledger.set(LedgerModule.positions, {
        usd_product: ProductPosition(quantity=2.0, average_cost=5.0),
    })
    state = BacktestRunState(
        ledgers={ledger_identity("cny"): cny_ledger, ledger_identity("usd"): usd_ledger},
        strategy_configs={
            cny_strategy: StrategyConfig(strategy=cny_strategy),
            usd_strategy: StrategyConfig(strategy=usd_strategy),
        },
    )
    book = strategy_book_store_for(state)
    for strategy, ledger_id in ((cny_strategy, "cny"), (usd_strategy, "usd")):
        book.register_strategy_ledgers(
            strategy, (ledger_id,), default_ledger_id=ledger_id,
            cash_pool_ids_by_ledger={ledger_id: "pool"},
        )
    pool_store = cash_pool_store_for(state)
    pool_store.config_by_pool["pool"] = CashPoolConfig(base_currency="CNY")
    pool_store.fx_rate_provider = lambda source, target, _timestamp: (
        7.0 if (source, target) == ("USD", "CNY") else None
    )
    set_cash_for_ledger_pool(
        state, cny_ledger, DataMoney.from_major(100.0, currency="CNY", use_minor_units=False),
    )
    set_cash_for_ledger_pool(
        state, usd_ledger, DataMoney.from_major(10.0, currency="USD", use_minor_units=False),
    )
    timestamp = pd.Timestamp("2025-01-02 09:30")
    ctx = FlowContext(
        timestamp=timestamp, event_queue=EventQueue(),
        active_strategies=frozenset({cny_strategy, usd_strategy}),
    )
    ctx.set(MarketDataModule.current_prices, {cny_product: 5.0, usd_product: 5.0})
    ctx.set(MarketDataModule.current_historical_fields, {})

    assert cash_pool_equity(state, ctx, cny_ledger) == pytest.approx(250.0)

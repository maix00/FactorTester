from __future__ import annotations

from collections import deque

import pandas as pd
import pytest

from tools.data.types.data_money import DataMoney
from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import CashPoolConfig, LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.ledger import LedgerState
from tools.testers.backtest.engines.native.position import Lot, ProductPosition
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.cash_pool import cash_pool_store_for, set_cash_for_ledger_pool
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.margin import _apply_margin_requirement_change
from tools.testers.backtest.modules.margin_risk.utilization import margin_limit_states
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.strategy_book import strategy_book_store_for


def test_margin_limit_states_values_shared_pool_once(monkeypatch) -> None:
    first_strategy = Strategy(alias="first")
    second_strategy = Strategy(alias="second")
    first_product = Product(name="FIRST", point_value=1, currency="CNY")
    second_product = Product(name="SECOND", point_value=1, currency="CNY")
    first = _ledger(first_strategy, "L1", first_product)
    second = _ledger(second_strategy, "L2", second_product)
    state = BacktestRunState(
        ledgers={first.ledger: first, second.ledger: second},
        strategy_configs={
            first_strategy: StrategyConfig(
                strategy=first_strategy,
                field_values={EngineModule.engine_mode: "auto"},
            ),
            second_strategy: StrategyConfig(
                strategy=second_strategy,
                field_values={EngineModule.engine_mode: "auto"},
            ),
        },
    )
    state.ledger_configs.update({
        first.ledger: LedgerConfig(margin_mode="auto", margin_call_mode="warn"),
        second.ledger: LedgerConfig(margin_mode="auto", margin_call_mode="warn"),
    })
    book = strategy_book_store_for(state)
    book.register_strategy_ledgers(
        first_strategy, ("L1",), default_ledger_id="L1",
        cash_pool_ids_by_ledger={"L1": "shared"},
    )
    book.register_strategy_ledgers(
        second_strategy, ("L2",), default_ledger_id="L2",
        cash_pool_ids_by_ledger={"L2": "shared"},
    )
    set_cash_for_ledger_pool(
        state, first,
        DataMoney.from_major(1_000.0, currency="CNY", use_minor_units=False),
    )
    timestamp = pd.Timestamp("2026-03-10 14:39:00", tz="Asia/Shanghai")
    ctx = FlowContext(timestamp=timestamp, event_queue=EventQueue())
    ctx.set(MarketDataModule.current_market_snapshot, {
        "close": {first_product: 11.0, second_product: 9.0},
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        first_product: {"VolumeMultiple": 10.0, "LongMarginRatioByMoney": 0.1},
        second_product: {"VolumeMultiple": 10.0, "LongMarginRatioByMoney": 0.1},
    })

    import tools.testers.backtest.modules.ledger_module as ledger_module

    original = ledger_module._ledger_equity
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(ledger_module, "_ledger_equity", counted)
    states = margin_limit_states(
        state, ctx, {first.ledger: 20.0, second.ledger: 20.0},
    )

    assert calls == 2
    assert states[first.ledger] == (40.0 / 1_020.0, 0.0)
    assert states[second.ledger] == (40.0 / 1_020.0, 0.0)


def test_margin_limit_states_converts_each_accounts_margin_and_equity() -> None:
    cny_strategy, usd_strategy = Strategy(alias="CNY"), Strategy(alias="USD")
    cny_product = Product(name="CNY-P", point_value=1, currency="CNY")
    usd_product = Product(name="USD-P", point_value=1, currency="USD")
    cny = _ledger(cny_strategy, "CNY-L", cny_product)
    usd = LedgerState(strategy=usd_strategy, base_currency="USD", ledger_id="USD-L")
    usd.set(LedgerModule.positions, {
        usd_product: ProductPosition(
            quantity=1.0,
            lots=deque([Lot(quantity=1.0, entry_price=10.0, multiplier=10.0, is_today=False)]),
            margin_reserved=DataMoney.from_major(10.0, currency="USD", use_minor_units=False),
        ),
    })
    state = BacktestRunState(
        ledgers={cny.ledger: cny, usd.ledger: usd},
        strategy_configs={
            cny_strategy: StrategyConfig(
                strategy=cny_strategy, field_values={EngineModule.engine_mode: "auto"},
            ),
            usd_strategy: StrategyConfig(
                strategy=usd_strategy, field_values={EngineModule.engine_mode: "auto"},
            ),
        },
    )
    state.ledger_configs.update({
        cny.ledger: LedgerConfig(margin_mode="auto", margin_call_mode="warn"),
        usd.ledger: LedgerConfig(
            margin_mode="auto", margin_call_mode="warn", account_currency="USD",
        ),
    })
    book = strategy_book_store_for(state)
    for strategy, ledger_id in ((cny_strategy, "CNY-L"), (usd_strategy, "USD-L")):
        book.register_strategy_ledgers(
            strategy, (ledger_id,), default_ledger_id=ledger_id,
            cash_pool_ids_by_ledger={ledger_id: "shared"},
        )
    store = cash_pool_store_for(state)
    store.config_by_pool["shared"] = CashPoolConfig(base_currency="CNY")
    store.fx_rate_provider = lambda source, target, _timestamp: (
        7.0 if (source, target) == ("USD", "CNY") else None
    )
    set_cash_for_ledger_pool(
        state, cny, DataMoney.from_major(1_000.0, currency="CNY", use_minor_units=False),
    )
    set_cash_for_ledger_pool(
        state, usd, DataMoney.from_major(0.0, currency="USD", use_minor_units=False),
    )
    timestamp = pd.Timestamp("2026-03-10 14:39:00", tz="Asia/Shanghai")
    ctx = FlowContext(timestamp=timestamp, event_queue=EventQueue())
    ctx.set(MarketDataModule.current_market_snapshot, {
        "close": {cny_product: 10.0, usd_product: 10.0},
    })
    ctx.set(MarketDataModule.current_historical_fields, {
        cny_product: {"VolumeMultiple": 10.0, "LongMarginRatioByMoney": 0.1},
        usd_product: {"VolumeMultiple": 10.0, "LongMarginRatioByMoney": 0.1},
    })

    states = margin_limit_states(
        state, ctx, {cny.ledger: 20.0, usd.ledger: 10.0},
    )

    expected = 90.0 / 1_080.0
    assert states[cny.ledger][0] == pytest.approx(expected)
    assert states[usd.ledger][0] == pytest.approx(expected)


def test_unchanged_requirement_preserves_cash_and_position_money_objects() -> None:
    strategy = Strategy(alias="only")
    product = Product(name="ONLY", point_value=1, currency="CNY")
    ledger = _ledger(strategy, "L1", product)
    state = BacktestRunState(
        ledgers={ledger.ledger: ledger},
        strategy_configs={
            strategy: StrategyConfig(
                strategy=strategy,
                field_values={EngineModule.engine_mode: "auto"},
            ),
        },
    )
    state.ledger_configs[ledger.ledger] = LedgerConfig(
        margin_mode="auto", margin_call_mode="warn",
    )
    book = strategy_book_store_for(state)
    book.register_strategy_ledgers(
        strategy, ("L1",), default_ledger_id="L1",
        cash_pool_ids_by_ledger={"L1": "shared"},
    )
    cash = DataMoney.from_major(1_000.0, currency="CNY", use_minor_units=False)
    set_cash_for_ledger_pool(state, ledger, cash)
    timestamp = pd.Timestamp("2026-03-10 14:39:00", tz="Asia/Shanghai")
    ctx = FlowContext(
        timestamp=timestamp,
        event_queue=EventQueue(),
        active_ledgers=frozenset({ledger.ledger}),
        drafts_by_ledger={
            ledger.ledger: [EventDraft(
                EventKind.LEDGER,
                timestamp,
                payload={"kind": "margin_check", "ledger_id": ledger.ledger_id},
                ledger=ledger.ledger,
            )],
        },
    )
    ctx.set(MarketDataModule.current_market_snapshot, {"close": {product: 11.0}})
    ctx.set(MarketDataModule.current_historical_fields, {
        product: {"VolumeMultiple": 10.0, "LongMarginRatioByMoney": 0.1},
    })
    entry = ledger.get(LedgerModule.positions)[product]
    reserved = entry.margin_reserved

    _apply_margin_requirement_change(state, ctx)

    assert entry.margin_reserved is reserved
    from tools.testers.backtest.modules.cash_pool import cash_for_ledger

    assert cash_for_ledger(state, ledger) is cash


def _ledger(strategy: Strategy, ledger_id: str, product: Product) -> LedgerState:
    ledger = LedgerState(strategy=strategy, base_currency="CNY", ledger_id=ledger_id)
    ledger.set(LedgerModule.positions, {
        product: ProductPosition(
            quantity=1.0,
            lots=deque([
                Lot(quantity=1.0, entry_price=10.0, multiplier=10.0, is_today=False),
            ]),
            margin_reserved=DataMoney.from_major(
                10.0, currency="CNY", use_minor_units=False,
            ),
        ),
    })
    return ledger

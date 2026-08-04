from __future__ import annotations

from collections import deque

import pandas as pd

from tools.data.types.data_money import DataMoney
from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.ledger import LedgerState
from tools.testers.backtest.engines.native.position import Lot, ProductPosition
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.cash_pool import set_cash_for_ledger_pool
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.ledger_module import LedgerModule
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

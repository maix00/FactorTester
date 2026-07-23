from __future__ import annotations

import pandas as pd
import pytest

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.order import OrderOffset
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.trading_rule import _apply_daily_mark_to_market

from .short_accounting_support import (
    FEE_PER_FILL,
    INITIAL_CASH,
    MULTIPLIER,
    OPEN_PRICE,
    QUANTITY,
    cash_major,
    fill_order,
    historical_fields,
    short_account,
)


def test_short_dmtm_segments_pnl_without_double_counting_on_buy_close() -> None:
    """DMTM settles the first price leg and close realizes only the remainder."""
    state, strategy, product = short_account(margin=True, daily_mtm=True)
    ledger = state.ledger_for_strategy(strategy)
    fill_order(
        state, strategy, product,
        timestamp="2025-01-02 09:01", quantity=-QUANTITY,
        price=OPEN_PRICE, fee=FEE_PER_FILL, offset=OrderOffset.OPEN,
    )
    assert cash_major(state, strategy) == pytest.approx(99_698.0)

    settlement = 90.0
    ts = pd.Timestamp("2025-01-02 15:00")
    ctx = FlowContext(
        timestamp=ts,
        event_queue=EventQueue(),
        event_kind=EventKind.LEDGER,
        active_ledgers=frozenset({ledger.ledger}),
        drafts_by_ledger={
            ledger.ledger: [
                EventDraft(
                    EventKind.LEDGER,
                    ts,
                    payload={
                        "kind": "daily_mark_to_market",
                        "ledger_id": ledger.ledger_id,
                        "trading_day": "2025-01-02",
                    },
                    ledger=ledger.ledger,
                )
            ],
        },
    )
    ctx.set(MarketDataModule.current_market_snapshot, {
        "settlement": {product: settlement},
        "close": {product: settlement},
    })
    ctx.set(
        MarketDataModule.current_historical_fields,
        historical_fields(product, settlement=settlement),
    )
    _apply_daily_mark_to_market(state, ctx)

    first_leg = QUANTITY * (OPEN_PRICE - settlement) * MULTIPLIER
    assert first_leg == 300.0
    assert cash_major(state, strategy) == pytest.approx(99_998.0)
    position = ledger.get(LedgerModule.positions)[product]
    assert [(lot.quantity, lot.entry_price) for lot in position.lots] == [
        (-QUANTITY, settlement)
    ]

    close_price = 80.0
    fill_order(
        state, strategy, product,
        timestamp="2025-01-03 09:01", quantity=QUANTITY,
        price=close_price, fee=FEE_PER_FILL, offset=OrderOffset.CLOSE,
    )
    second_leg = QUANTITY * (settlement - close_price) * MULTIPLIER
    settlements = list(state.order_store.settlements_by_fill.values())
    assert second_leg == 300.0
    assert settlements[-1].realized_pnl == pytest.approx(second_leg)
    assert position.quantity == 0
    assert cash_major(state, strategy) == pytest.approx(
        INITIAL_CASH + first_leg + second_leg - 2 * FEE_PER_FILL
    )

from __future__ import annotations

import pandas as pd

from tools.testers.backtest.engines.event_driven.contracts import FeeBreakdown, FeeComponent, Fill, OrderSide
from tools.testers.backtest.engines.event_driven.runtime import EventDraft, EventRuntime, EventTopic, ReplayEventSource
from tools.testers.backtest.engines.execution.trading import (
    FuturesAccounting,
    FuturesContractSpec,
    Ledger,
    SettlementPrices,
)


def make_fill(
    fill_id: str,
    side: OrderSide,
    quantity: float,
    price: float,
    timestamp: pd.Timestamp,
    fee_minor: int = 0,
) -> Fill:
    return Fill(
        fill_id=fill_id,
        order_id=f"order-{fill_id}",
        strategy_id="strategy-futures",
        portfolio_id="futures",
        timestamp=timestamp,
        instrument="A",
        side=side,
        quantity=quantity,
        price=price,
        fees=(
            FeeBreakdown((FeeComponent("commission", fee_minor),))
            if fee_minor
            else FeeBreakdown()
        ),
    )


def test_futures_fill_freezes_margin_instead_of_full_notional() -> None:
    timestamp = pd.Timestamp("2026-01-01 09:01")
    accounting = FuturesAccounting({
        "A": FuturesContractSpec(point_value=10.0, margin_ratio=0.10),
    })
    ledger = Ledger("futures", ("A",), 100_000, accounting)
    runtime = EventRuntime("margin-run")
    runtime.add_source(ReplayEventSource(
        [timestamp],
        [make_fill("1", OrderSide.BUY, 1.0, 100.0, timestamp)],
        topic=EventTopic.FILL,
    ))
    runtime.subscribe(EventTopic.FILL, ledger.on_fill)
    runtime.run()

    assert ledger.positions["A"] == 1.0
    assert ledger.margin_minor == 10_000
    assert ledger.cash_minor == 90_000
    assert ledger.equity_minor == 100_000


def test_daily_settlement_marks_fifo_lots_and_adjusts_margin() -> None:
    opened_at = pd.Timestamp("2026-01-01 09:01")
    settled_at = pd.Timestamp("2026-01-01 15:00")
    accounting = FuturesAccounting({
        "A": FuturesContractSpec(point_value=10.0, margin_ratio=0.10),
    })
    ledger = Ledger("futures", ("A",), 100_000, accounting)
    runtime = EventRuntime("settlement-run")
    runtime.add_source(ReplayEventSource(
        [opened_at, settled_at],
        [
            make_fill("1", OrderSide.BUY, 1.0, 100.0, opened_at),
            SettlementPrices({"A": 110.0}),
        ],
        topic=EventTopic.FILL,
    ))

    def route(event, runtime):
        if isinstance(event.payload, SettlementPrices):
            return EventDraft(EventTopic.SETTLEMENT, event.timestamp, event.payload)
        ledger.on_fill(event, runtime)
        return None

    runtime.subscribe(EventTopic.FILL, route)
    runtime.subscribe(EventTopic.SETTLEMENT, ledger.on_settlement)
    runtime.run()

    assert ledger.margin_minor == 11_000
    assert ledger.cash_minor == 99_000
    assert ledger.equity_minor == 110_000
    assert ledger.realized_pnl_minor == 10_000


def test_fifo_close_releases_original_margin_and_realizes_pnl() -> None:
    t0 = pd.Timestamp("2026-01-01 09:01")
    t1 = pd.Timestamp("2026-01-01 09:02")
    accounting = FuturesAccounting({
        "A": FuturesContractSpec(point_value=10.0, margin_ratio=0.10),
    })
    ledger = Ledger("futures", ("A",), 200_000, accounting)
    runtime = EventRuntime("fifo-run")
    runtime.add_source(ReplayEventSource(
        [t0, t1],
        [
            make_fill("1", OrderSide.BUY, 2.0, 100.0, t0),
            make_fill("2", OrderSide.SELL, 1.0, 110.0, t1, fee_minor=100),
        ],
        topic=EventTopic.FILL,
    ))
    runtime.subscribe(EventTopic.FILL, ledger.on_fill)
    runtime.run()

    assert ledger.positions["A"] == 1.0
    assert ledger.margin_minor == 10_000
    assert ledger.cash_minor == 199_900
    assert ledger.equity_minor == 209_900
    assert ledger.realized_pnl_minor == 10_000

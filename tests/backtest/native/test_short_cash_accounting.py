from __future__ import annotations

import pytest

from tools.testers.backtest.engines.native.order import OrderOffset, OrderSide
from tools.testers.backtest.modules.ledger_module import LedgerModule

from .short_accounting_support import (
    FEE_PER_FILL,
    INITIAL_CASH,
    MULTIPLIER,
    OPEN_PRICE,
    QUANTITY,
    cash_major,
    fill_order,
    short_account,
)


@pytest.mark.parametrize(
    ("close_price", "gross_pnl"),
    [(80.0, 600.0), (120.0, -600.0)],
)
def test_short_sell_open_then_buy_close_has_industry_pnl_sign(
    close_price: float,
    gross_pnl: float,
) -> None:
    """A short gains when the repurchase price falls and loses when it rises."""
    state, strategy, product = short_account(margin=False, daily_mtm=False)
    opening = fill_order(
        state, strategy, product,
        timestamp="2025-01-02 09:01", quantity=-QUANTITY,
        price=OPEN_PRICE, fee=FEE_PER_FILL, offset=OrderOffset.OPEN,
    )
    closing = fill_order(
        state, strategy, product,
        timestamp="2025-01-03 09:01", quantity=QUANTITY,
        price=close_price, fee=FEE_PER_FILL, offset=OrderOffset.CLOSE,
    )

    position = state.ledger_for_strategy(strategy).get(
        LedgerModule.positions,
    )[product]
    settlements = list(state.order_store.settlements_by_fill.values())
    assert opening.side is OrderSide.SELL
    assert closing.side is OrderSide.BUY
    assert position.quantity == 0
    assert settlements[-1].realized_pnl == pytest.approx(gross_pnl)
    assert cash_major(state, strategy) == pytest.approx(
        INITIAL_CASH + gross_pnl - 2 * FEE_PER_FILL
    )


@pytest.mark.parametrize(
    ("buy_quantity", "expected_quantity", "expected_lot"),
    [
        (2.0, -3.0, (-3.0, OPEN_PRICE)),
        (7.0, 2.0, (2.0, 80.0)),
    ],
)
def test_short_partial_close_and_buy_through_zero_preserve_lot_direction(
    buy_quantity: float,
    expected_quantity: float,
    expected_lot: tuple[float, float],
) -> None:
    """A buy either reduces the original short or opens a new long after zero."""
    state, strategy, product = short_account(margin=False, daily_mtm=False)
    open_quantity = 5.0
    fill_order(
        state, strategy, product,
        timestamp="2025-01-02 09:01", quantity=-open_quantity,
        price=OPEN_PRICE, fee=0.0, offset=OrderOffset.OPEN,
    )
    fill_order(
        state, strategy, product,
        timestamp="2025-01-03 09:01", quantity=buy_quantity,
        price=80.0, fee=0.0, offset=OrderOffset.AUTO,
    )

    position = state.ledger_for_strategy(strategy).get(
        LedgerModule.positions,
    )[product]
    settlements = list(state.order_store.settlements_by_fill.values())
    closed_quantity = min(open_quantity, buy_quantity)
    expected_realized = (
        closed_quantity * (OPEN_PRICE - 80.0) * MULTIPLIER
    )
    assert position.quantity == pytest.approx(expected_quantity)
    assert [(lot.quantity, lot.entry_price) for lot in position.lots] == [
        expected_lot
    ]
    assert settlements[-1].realized_pnl == pytest.approx(expected_realized)

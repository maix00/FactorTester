"""LedgerCashConstraintModule — haircuts a strategy's buy-side orders
(built in the same SIGNAL batch) proportionally if their total estimated
cost exceeds that strategy's available Ledger.cash. A real Flow (not a
FlowOverride) since this is a genuine constraint step in its own right, not
a parameter of OrderBookModule.construct_orders."""

from __future__ import annotations

from typing import ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_book import OrderBookModule


class LedgerCashConstraintModule(ExecutableModule):
    key: ClassVar[str] = "cash_rescale"
    label: ClassVar[str] = "现金调整"

    constrain_to_ledger_cash: ClassVar[Flow] = Flow(
        "constrain_to_ledger_cash",
        inputs=(OrderBookModule.orders, MarketDataModule.current_prices),
        outputs=(OrderBookModule.orders,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=35,  # between construct_orders (30) and
                    # GroupMembershipModule.schedule_order_execution (40) --
                    # must haircut buy-side quantities BEFORE they're
                    # scheduled for execution, not after
        after=(OrderBookModule.construct_orders,),
        compute=lambda account, ctx: _constrain_to_ledger_cash(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (constrain_to_ledger_cash,)


def _constrain_to_ledger_cash(account, ctx) -> None:
    prices = ctx.get(MarketDataModule.current_prices)
    for strategy in ctx.active_strategies:
        orders = ctx.get_for(OrderBookModule.orders, strategy, [])
        if not orders:
            continue
        ledger = account.ledgers[strategy]
        buy_cost = sum(o.quantity * prices[o.instrument] for o in orders if o.quantity > 0)
        if buy_cost <= 0:
            continue
        available = ledger.get(LedgerModule.cash).to_major()
        if buy_cost <= available:
            continue
        scale = available / buy_cost
        for o in orders:
            if o.quantity > 0:
                o.quantity *= scale

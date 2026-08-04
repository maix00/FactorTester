"""EventKind/EventDraft — causal replay events for the native scheduler."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Callable

import pandas as pd

if TYPE_CHECKING:
    from .ledger import Ledger
    from tools.testers.backtest.engines.native.strategy import Strategy





class EventKind(IntEnum):
    """Values are priority order, not arbitrary labels — at the same
    timestamp, the lower value pops first from the EventQueue (see
    scheduler.EventQueue). BAR before ORDER before POSITION before TIMER before
    SIGNAL before lifecycle notices before TRADE_INTENT before LEDGER:
    completed market data updates first, carried orders consume that bar before
    a clock callback observes positions, then lifecycle notices can cheaply
    decide whether an order is needed before generic trade intents materialize
    market data. Dynamically emitted same-time events remain causal
    because they enter the queue only after their producer runs. Values are spaced so a future
    EventKind can be inserted without renumbering everything after it."""
    FIELD_CHANGE = -5  # historical market-rule field change event; processed before any
                       # BAR so the field snapshot is already current for the
                       # entire timestamp
    MARKET_FEED = -1  # one raw quote/trade/book observation; payload kind carries
                      # L1/L2/L3 semantics and feed sequence preserves same-time order
    BAR = 0       # an aggregate market bar has arrived; live factors may update state
    ORDER_STATUS = 4  # an order lifecycle transition; never enters matching Flows
    ORDER = 5     # an existing Order has reached one matching opportunity
    POSITION = 6  # a fill has changed a strategy-owned position; ledger is already updated
    TIMER = 8     # a clock-owned strategy timer or one-shot time alert fired
    SIGNAL = 10   # a strategy signal/rebalance decision point has arrived
    LIFECYCLE_NOTICE = 14  # contract rollover / force-close notice; handlers
                           # inspect positions and emit ORDER only when needed
    TRADE_INTENT = 15  # a non-signal trade intent (e.g. contract rollover,
                       # auto-close or risk liquidation). Domain modules
                       # interpret the payload and may emit ORDER events.
    LEDGER = 30  # account/clearing lifecycle event (e.g. daily futures
                 # settlement / mark-to-market). It mutates the ledger and does
                 # not express strategy intent to trade.


@dataclass(frozen=True)
class EventDraft:
    kind: EventKind
    timestamp: pd.Timestamp
    strategy: "Strategy | None" = None
        # Strategy-scoped events: BAR/TIMER/SIGNAL/ORDER_STATUS/ORDER/POSITION/LIFECYCLE_NOTICE/TRADE_INTENT. LEDGER
        # can set this to None and route by ledger instead.
    payload: Any = None
    index_key: Any = None
    index_names: tuple[Any, ...] = ()
    ledger: "Ledger | None" = None
    sequence: int = 0
    dispatch_guard: Callable[[Any, "EventDraft"], bool] | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("EventDraft.sequence must be non-negative")

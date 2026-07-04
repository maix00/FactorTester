"""EventKind/EventDraft — causal replay events for the native scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from .ledger import Ledger
    from tools.testers.backtest.engines.native.strategy import Strategy


class EventKind(IntEnum):
    """Values are priority order, not arbitrary labels — at the same
    timestamp, the lower value pops first from the EventQueue (see
    scheduler.EventQueue). BAR before SIGNAL before TRADE_INTENT before ORDER
    before LEDGER: live factors first observe market data, strategies read
    signal values, non-signal trade intents create orders, orders execute, and
    ledger lifecycle events settle account state. Values are spaced so a future
    EventKind can be inserted without renumbering everything after it."""
    BAR = 0       # a market bar has arrived; live factors may update state
    SIGNAL = 10   # a strategy signal/rebalance decision point has arrived
    TRADE_INTENT = 15  # a non-signal trade intent (e.g. contract rollover,
                       # auto-close/force-close or risk liquidation). Domain
                       # modules interpret the payload and may emit ORDER events.
    ORDER = 20    # an Order has reached its action moment (schedule/cancel/fill
                  # are OrderStatus values inspected from the payload, not
                  # separate EventKinds)
    LEDGER = 30  # account/clearing lifecycle event (e.g. daily futures
                 # settlement / mark-to-market). It mutates the ledger and does
                 # not express strategy intent to trade.


@dataclass(frozen=True)
class EventDraft:
    kind: EventKind
    timestamp: pd.Timestamp
    strategy: "Strategy | None" = None
        # Strategy-scoped events: BAR/SIGNAL/TRADE_INTENT/ORDER.  LEDGER
        # can set this to None and route by ledger instead.
    payload: Any = None
    index_key: Any = None
    index_names: tuple[Any, ...] = ()
    ledger: "Ledger | None" = None

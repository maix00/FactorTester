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
    scheduler.EventQueue). BAR before SIGNAL before ORDER: live factors first
    observe market data, then strategies read signal values, then orders whose
    action time has arrived are processed. Values are spaced so a future
    EventKind can be inserted without renumbering everything after it."""
    BAR = 0       # a market bar has arrived; live factors may update state
    SIGNAL = 10   # a strategy signal/rebalance decision point has arrived
    ORDER_NOTICE = 15  # an order/position lifecycle notification (e.g.
                       # contract rollover, auto-close/force-close warning).
                       # Domain modules interpret the payload and may emit
                       # ORDER events.
    ORDER = 20    # an Order has reached its action moment (schedule/cancel/fill
                  # are OrderStatus values inspected from the payload, not
                  # separate EventKinds)
    LEDGER_NOTICE = 30  # account/clearing lifecycle notification (e.g. daily
                        # futures settlement / mark-to-market). It mutates the
                        # ledger directly and does not express strategy intent
                        # to trade.


@dataclass(frozen=True)
class EventDraft:
    kind: EventKind
    timestamp: pd.Timestamp
    strategy: "Strategy | None" = None
        # Strategy-scoped events: BAR/SIGNAL/ORDER/ORDER_NOTICE.  LEDGER_NOTICE
        # can set this to None and route by ledger instead.
    payload: Any = None
    index_key: Any = None
    index_names: tuple[Any, ...] = ()
    ledger: "Ledger | None" = None

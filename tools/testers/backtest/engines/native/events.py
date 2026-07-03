"""EventKind/EventDraft — causal replay events for the native scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
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
    LEDGER_NOTICE = 30  # accounting-only lifecycle notifications (e.g.
                        # daily mark-to-market settlement) that must happen
                        # after same-timestamp order effects.


@dataclass(frozen=True)
class EventDraft:
    kind: EventKind
    timestamp: pd.Timestamp
    strategy: "Strategy"   # which strategy this event belongs to — different
                            # strategies' SIGNAL events can legitimately land on the
                            # same timestamp; the scheduler batches/dispatches by this
                            # field, not by payload (a SIGNAL event has no Order yet)
    payload: Any = None
    index_key: Any = None
    index_names: tuple[Any, ...] = ()

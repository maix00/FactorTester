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
    scheduler.EventQueue). BAR before ORDER before SIGNAL: the next-bar order
    decided on the previous bar is filled before the current bar's signal
    decides a new target from fresh ledger state. Values are spaced so a
    future EventKind can be inserted without renumbering everything after it."""
    BAR = 0       # a market bar has arrived; live factors may update state
    ORDER = 5     # an Order has reached its action moment (schedule/cancel/fill
                  # are OrderStatus values inspected from the payload, not
                  # separate EventKinds)
    SIGNAL = 10   # a strategy signal/rebalance decision point has arrived
    ORDER_NOTICE = 15  # an order/position lifecycle notification (e.g.
                       # contract rollover, auto-close/force-close warning).
                       # Domain modules interpret the payload and may emit
                       # ORDER events.


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

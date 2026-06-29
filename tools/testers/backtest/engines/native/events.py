"""EventKind/EventDraft — the two domain events of the engine. Bar advance
is NOT an event (timestamps are fully known upfront; the scheduler just
walks the precomputed causal price series), so EventKind has exactly two
values."""

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
    scheduler.EventQueue). SIGNAL before ORDER: process newly-produced
    decisions before executing orders derived from them. Values are spaced
    (0/10, not 0/1) so a future EventKind can be inserted between them
    without renumbering everything after it."""
    SIGNAL = 0    # a factor/signal value has been produced
    ORDER = 10    # an Order has reached its action moment (schedule/cancel/fill
                  # are OrderStatus values inspected from the payload, not
                  # separate EventKinds)


@dataclass(frozen=True)
class EventDraft:
    kind: EventKind
    timestamp: pd.Timestamp
    strategy: "Strategy"   # which strategy this event belongs to — different
                            # strategies' SIGNAL events can legitimately land on the
                            # same timestamp; the scheduler batches/dispatches by this
                            # field, not by payload (a SIGNAL event has no Order yet)
    payload: Any = None

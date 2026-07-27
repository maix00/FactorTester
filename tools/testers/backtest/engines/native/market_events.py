"""Typed raw market-data events consumed by custom native strategies."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any

import pandas as pd


class MarketFeedEventKind(str, Enum):
    """Payload kind carried by ``EventKind.MARKET_FEED``."""

    QUOTE = "quote"
    TRADE = "trade"
    BOOK_DELTA = "book_delta"
    BOOK_SNAPSHOT = "book_snapshot"


class BookLevel(str, Enum):
    L2_MBP = "L2_MBP"
    L3_MBO = "L3_MBO"


@dataclass(frozen=True)
class Quote:
    bid_price: float
    ask_price: float
    bid_size: float | None = None
    ask_size: float | None = None


@dataclass(frozen=True)
class Trade:
    price: float
    quantity: float
    aggressor_side: str | None = None


@dataclass(frozen=True)
class BookDelta:
    action: str
    side: str
    price: float
    quantity: float
    level: BookLevel
    order_id: str | None = None


@dataclass(frozen=True)
class MarketFeedEvent:
    """One atomic feed observation; sequence is its order at a timestamp."""

    timestamp: pd.Timestamp
    instrument: Any
    kind: MarketFeedEventKind
    payload: Quote | Trade | BookDelta | Any
    sequence: int = 0
    source: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", pd.Timestamp(self.timestamp))
        object.__setattr__(self, "kind", MarketFeedEventKind(self.kind))
        if self.sequence < 0:
            raise ValueError("MarketFeedEvent.sequence must be non-negative")
        self._validate_payload()

    def _validate_payload(self) -> None:
        expected = {
            MarketFeedEventKind.QUOTE: Quote,
            MarketFeedEventKind.TRADE: Trade,
            MarketFeedEventKind.BOOK_DELTA: BookDelta,
        }.get(self.kind)
        if expected is not None and not isinstance(self.payload, expected):
            raise TypeError(
                f"{self.kind.value} event requires {expected.__name__} payload, "
                f"got {type(self.payload).__name__}"
            )

    def to_draft(self, strategy: Any) -> Any:
        """Create the scheduler event used by a feed adapter."""

        from tools.testers.backtest.engines.native.events import EventDraft, EventKind

        return EventDraft(
            EventKind.MARKET_FEED,
            self.timestamp,
            strategy,
            payload=self,
            sequence=self.sequence,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self.payload) if is_dataclass(self.payload) else self.payload
        return {
            "kind": self.kind.value,
            "timestamp": self.timestamp.isoformat(),
            "instrument": str(self.instrument),
            "sequence": self.sequence,
            "source": self.source,
            "payload": payload,
        }

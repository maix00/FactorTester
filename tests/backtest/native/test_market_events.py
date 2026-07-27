import pandas as pd
import pytest

from tools.testers.backtest.engines.native.market_events import (
    BookDelta,
    BookLevel,
    MarketFeedEvent,
    MarketFeedEventKind,
    Quote,
    Trade,
)


def test_market_feed_event_normalizes_timestamp_and_kind():
    event = MarketFeedEvent(
        "2025-01-01 09:00:00",
        "P1",
        "quote",
        Quote(10.0, 10.1, 3.0, 4.0),
        sequence=2,
    )

    assert event.timestamp == pd.Timestamp("2025-01-01 09:00:00")
    assert event.kind is MarketFeedEventKind.QUOTE
    assert event.payload.ask_size == 4.0


def test_l2_and_l3_book_deltas_are_typed_payloads():
    l2 = MarketFeedEvent(
        pd.Timestamp("2025-01-01 09:00:00"),
        "P1",
        MarketFeedEventKind.BOOK_DELTA,
        BookDelta("update", "bid", 10.0, 5.0, BookLevel.L2_MBP),
    )
    l3 = MarketFeedEvent(
        pd.Timestamp("2025-01-01 09:00:00"),
        "P1",
        MarketFeedEventKind.BOOK_DELTA,
        BookDelta("add", "ask", 10.1, 2.0, BookLevel.L3_MBO, order_id="O1"),
    )

    assert l2.payload.level is BookLevel.L2_MBP
    assert l3.payload.level is BookLevel.L3_MBO
    assert l3.payload.order_id == "O1"


def test_market_feed_event_rejects_mismatched_payload():
    with pytest.raises(TypeError, match="quote event requires Quote"):
        MarketFeedEvent(
            pd.Timestamp("2025-01-01 09:00:00"),
            "P1",
            MarketFeedEventKind.QUOTE,
            Trade(10.0, 1.0),
        )


def test_market_feed_event_rejects_negative_sequence():
    with pytest.raises(ValueError, match="non-negative"):
        MarketFeedEvent(
            pd.Timestamp("2025-01-01 09:00:00"),
            "P1",
            MarketFeedEventKind.TRADE,
            Trade(10.0, 1.0),
            sequence=-1,
        )


def test_market_feed_event_builds_raw_feed_event_draft():
    strategy = object()
    event = MarketFeedEvent(
        pd.Timestamp("2025-01-01 09:00:00"),
        "P1",
        MarketFeedEventKind.TRADE,
        Trade(10.0, 1.0),
    )

    draft = event.to_draft(strategy)

    assert draft.kind.name == "MARKET_FEED"
    assert draft.strategy is strategy
    assert draft.payload is event
    assert event.to_dict()["kind"] == "trade"


def test_raw_feed_sequence_orders_equal_timestamp_events():
    strategy = object()
    later = MarketFeedEvent(
        pd.Timestamp("2025-01-01 09:00:00"), "P1", "trade", Trade(10.0, 1.0), sequence=2,
    ).to_draft(strategy)
    earlier = MarketFeedEvent(
        pd.Timestamp("2025-01-01 09:00:00"), "P1", "trade", Trade(9.9, 1.0), sequence=1,
    ).to_draft(strategy)

    from tools.testers.backtest.engines.native.scheduler import EventQueue

    queue = EventQueue()
    queue.push_events([later, earlier])

    assert [draft.payload.payload.price for draft in queue.snapshot_head()] == [9.9, 10.0]

"""Limits must be checked before Bar queries; native replay batches are bounded."""
from types import SimpleNamespace

import pytest

from server.services.nautilus_bridge.backtest_runner import (
    MINUTE_NS, iter_catalog_bar_batches, replay_catalog_batches,
)


class Catalog:
    def __init__(self, count=8, delay=100):
        self.bars = [SimpleNamespace(ts_init=index * MINUTE_NS + delay) for index in range(count)]
        self.queries = []
        self.sessions = []

    def query_bar_batches(self, *, identifiers, start, end, chunk_size, max_timestamp_group_rows, memory_limit_bytes):
        self.queries.append((start, end))
        bars = [bar for bar in self.bars if start <= bar.ts_init <= end]

        class Session:
            def __init__(self):
                self.position = 0
                self.closed = False

            def next_batch(self):
                if self.position == len(bars):
                    return None
                first = self.position
                end = min(len(bars), first + chunk_size)
                while end < len(bars) and bars[end].ts_init == bars[end - 1].ts_init:
                    end += 1
                self.position = end
                return bars[first:end]

            def close(self):
                self.closed = True

        session = Session()
        self.sessions.append(session)
        return session


def opened(catalog):
    return (None, catalog, {"bar_type": "A-1-MINUTE-LAST-EXTERNAL", "selected_count": len(catalog.bars),
                            "first_available_ns": catalog.bars[0].ts_init,
                            "last_available_ns": catalog.bars[-1].ts_init}, None)


def test_oversized_receipt_fails_before_querying_any_bars():
    catalog = Catalog()
    with pytest.raises(ValueError, match="bar cap"):
        list(iter_catalog_bar_batches([opened(catalog)], max_input_bars=7))
    assert catalog.queries == []


def test_query_bounds_follow_availability_and_streaming_releases_batches():
    catalog = Catalog(delay=MINUTE_NS * 2)

    class Engine:
        def __init__(self):
            self.loaded = []
            self.processed = self.peak = self.clears = 0

        def add_data(self, bars):
            assert not self.loaded
            self.loaded = list(bars)
            self.peak = max(self.peak, len(self.loaded))

        def run(self, *, start, end, streaming):
            assert streaming is True
            assert start <= self.loaded[0].ts_init <= self.loaded[-1].ts_init == end
            self.processed += len(self.loaded)

        def clear_data(self):
            self.loaded.clear()
            self.clears += 1

    engine = Engine()
    result = replay_catalog_batches(engine, [opened(catalog)], max_input_bars=8, batch_minutes=3)
    assert result == {"bars": 8, "batch_count": 3, "max_batch_bars": 3}
    assert engine.processed == 8
    assert engine.peak == 3
    assert engine.clears == 3 and engine.loaded == []
    assert catalog.queries[0][0] == catalog.bars[0].ts_init
    assert catalog.queries[-1][1] == catalog.bars[-1].ts_init


def test_native_failure_still_releases_loaded_batch():
    catalog = Catalog()
    engine = SimpleNamespace(add_data=lambda _: None, clear_data=lambda: None)
    cleared = []
    engine.run = lambda **_: (_ for _ in ()).throw(RuntimeError("failed"))
    engine.clear_data = lambda: cleared.append(True)
    with pytest.raises(RuntimeError, match="failed"):
        replay_catalog_batches(engine, [opened(catalog)], max_input_bars=8)
    assert cleared == [True]
    assert catalog.sessions[0].closed


def test_per_batch_bar_budget_bounds_native_query_chunks():
    catalog = Catalog(count=16)
    batches = list(iter_catalog_bar_batches(
        [opened(catalog)], max_input_bars=16, max_batch_bars=2,
    ))
    assert sum(len(batch) for batch in batches) == 16
    assert max(len(batch) for batch in batches) <= 2
    assert len(batches) >= 8


def test_multi_catalog_equal_timestamps_stay_in_one_batch_and_sources_close():
    first, second = Catalog(count=5), Catalog(count=5)
    batches = list(iter_catalog_bar_batches([opened(first), opened(second)],
                                            max_input_bars=10, max_batch_bars=3))
    timestamps = [int(bar.ts_init) for batch in batches for bar in batch]
    assert timestamps == sorted([bar.ts_init for bar in first.bars + second.bars])
    assert len(timestamps) == 10
    assert all(batches[i][-1].ts_init < batches[i+1][0].ts_init for i in range(len(batches)-1))
    assert all(session.closed for catalog in (first, second) for session in catalog.sessions)


def test_oversized_global_timestamp_group_refuses_and_closes_all_sources():
    first, second = Catalog(count=4), Catalog(count=4)
    for bar in first.bars + second.bars:
        bar.ts_init = 100
    with pytest.raises(ValueError, match="timestamp group"):
        list(iter_catalog_bar_batches([opened(first), opened(second)], max_input_bars=8,
                                      max_batch_bars=10, max_timestamp_group_bars=5))
    assert all(session.closed for catalog in (first, second) for session in catalog.sessions)


def test_early_consumer_close_releases_all_native_sessions():
    catalog = Catalog()
    stream = iter_catalog_bar_batches([opened(catalog)], max_input_bars=8, max_batch_bars=2)
    next(stream)
    stream.close()
    assert catalog.sessions[0].closed

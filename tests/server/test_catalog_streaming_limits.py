"""Limits must be checked before Bar queries; native replay batches are bounded."""
from types import SimpleNamespace

import pytest

from server.services.nautilus_bridge.backtest_runner import (
    MINUTE_NS, replay_catalog_batches,
)


class Catalog:
    def __init__(self, count=8, delay=100):
        self.bars = [SimpleNamespace(ts_init=index * MINUTE_NS + delay) for index in range(count)]
        self.queries = []
        self.sessions = []

    def query_bar_batches(self, **kwargs):
        raise AssertionError("native replay must not materialize Python batches")


def opened(catalog):
    return (None, catalog, {"bar_type": "A-1-MINUTE-LAST-EXTERNAL", "selected_count": len(catalog.bars),
                            "first_available_ns": catalog.bars[0].ts_init,
                            "last_available_ns": catalog.bars[-1].ts_init}, None)


def test_oversized_receipt_fails_before_querying_any_bars():
    catalog = Catalog()
    with pytest.raises(ValueError, match="bar cap"):
        replay_catalog_batches(SimpleNamespace(), [opened(catalog)], max_input_bars=7)
    assert catalog.queries == []


def test_native_replay_receives_frozen_bounds_without_python_queries():
    catalog = Catalog(delay=MINUTE_NS * 2)
    calls = []
    def run_catalogs(**kwargs):
        calls.append(kwargs)
        return (8, 3, 3, [8])
    engine = SimpleNamespace(run_catalogs=run_catalogs,
                             get_result=lambda: SimpleNamespace(iterations=8))
    result = replay_catalog_batches(engine, [opened(catalog)], max_input_bars=8, batch_minutes=3)
    assert result == {"bars": 8, "batch_count": 3, "max_batch_bars": 3}
    assert len(calls) == 1
    assert calls[0]["start"] == catalog.bars[0].ts_init
    assert calls[0]["end"] == catalog.bars[-1].ts_init
    assert calls[0]["chunk_size"] == 3
    assert calls[0]["max_chunk_events"] == 250_000
    assert all(config.optimize_file_loading for config in calls[0]["data"])
    assert catalog.queries == []


def test_native_failure_is_not_retried_through_python_merge():
    catalog = Catalog()
    def fail(**kwargs):
        raise RuntimeError("native failed")
    engine = SimpleNamespace(run_catalogs=fail)
    with pytest.raises(RuntimeError, match="native failed"):
        replay_catalog_batches(engine, [opened(catalog)], max_input_bars=8)
    assert catalog.queries == []


def test_partial_native_shutdown_does_not_publish_a_complete_receipt():
    catalog = Catalog()
    engine = SimpleNamespace(run_catalogs=lambda **_: (4, 1, 4, [8]),
                             get_result=lambda: SimpleNamespace(iterations=4))
    with pytest.raises(ValueError, match="count differs"):
        replay_catalog_batches(engine, [opened(catalog)], max_input_bars=8)


@pytest.mark.parametrize("cap", [1, 4])
def test_native_two_product_timestamp_group_and_hard_cap(tmp_path, cap):
    from tests.nautilus_runtime import require_nautilus
    from tests.server.test_nautilus_bridge_backtest_runner import _real_catalog
    from server.services.nautilus_bridge.backtest_runner import _load_input
    require_nautilus()
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import AccountType, Currency, Money, OmsType, Venue
    from decimal import Decimal
    rows = []
    for code, month in (("T", "2403"), ("TL", "2406")):
        folder = tmp_path / code
        folder.mkdir()
        rows.append(_load_input(_real_catalog(folder, code=code, month=month, count=8)))
    engine = BacktestEngine(config=BacktestEngineConfig(bypass_logging=True, run_analysis=False))
    try:
        engine.add_venue(venue=Venue("CFFEX"), oms_type=OmsType.NETTING,
                         account_type=AccountType.MARGIN, base_currency=Currency.from_str("CNY"),
                         starting_balances=[Money.from_str("1000000 CNY")],
                         fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)))
        for row in rows:
            engine.add_instrument(row[3])
        if cap == 1:
            with pytest.raises(RuntimeError, match="hard event cap"):
                replay_catalog_batches(engine, rows, max_input_bars=16,
                                       batch_minutes=1, max_batch_bars=cap)
            assert engine.get_result().iterations == 0
        else:
            result = replay_catalog_batches(engine, rows, max_input_bars=16,
                                             batch_minutes=1, max_batch_bars=cap)
            assert result == {"bars": 16, "batch_count": 8, "max_batch_bars": 2}
            assert engine.get_result().iterations == 16
    finally:
        engine.dispose()


def test_per_source_mismatch_cannot_cancel_out_in_total_count():
    first, second = Catalog(count=8), Catalog(count=8)
    engine = SimpleNamespace(run_catalogs=lambda **_: (16, 4, 4, [7, 9]),
                             get_result=lambda: SimpleNamespace(iterations=16))
    with pytest.raises(ValueError, match="per-source"):
        replay_catalog_batches(engine, [opened(first), opened(second)], max_input_bars=16)

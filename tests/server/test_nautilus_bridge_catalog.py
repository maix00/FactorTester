"""Native catalog conversion against tiny real T/TL windows."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from itertools import islice
from pathlib import Path

import pytest

from server.services.nautilus_bridge.catalog import stage_contract_minute_catalog
from server.services.nautilus_bridge.market_data import (
    FuturesContractSpec,
    iter_minute_bars,
)
from tests.nautilus_runtime import require_nautilus
from tests.nautilus_source_fixture import resolved_contract_minute_source

ROOT = Path("/Users/maxdeux/Documents/GTHT/data/sources/LocalCNFutures")


@pytest.mark.parametrize(
    ("code", "month", "tick", "precision"),
    [("T", "2403", "0.005", 3), ("TL", "2406", "0.01", 2)],
)
def test_real_three_bar_native_catalog_readback_and_receipt(
    tmp_path, code, month, tick, precision
):
    require_nautilus()
    pytest.importorskip("pyarrow")
    from nautilus_trader.persistence import ParquetDataCatalog

    source = ROOT / f"data_mink_product/CFFEX_F_{code}_{month}.parquet"
    if not source.is_file():
        pytest.skip("read-only local T/TL source unavailable")
    bars = list(islice(iter_minute_bars(source, batch_size=2), 3))
    assert len(bars) == 3
    uid = f"CFFEX|F|{code}|{month}"
    spec = FuturesContractSpec(
        instrument_code=f"{code}{month}", venue="CFFEX", underlying=code,
        price_increment=Decimal(tick), price_precision=precision,
        multiplier=Decimal("10000"), currency="CNY",
        activation_ns=1, expiration_ns=2_000_000_000_000_000_000,
        margin_init=Decimal("0.02"), margin_maint=Decimal("0.02"),
        provenance="test-only fixture; actual exchange specs not established",
        resolved_source=resolved_contract_minute_source(),
    )
    target = tmp_path / "catalog"
    receipt = stage_contract_minute_catalog(
        source, target, contract_uid=uid, instrument_spec=spec,
        start_ns=bars[0].clock.interval_end_ns,
        end_ns=bars[-1].clock.interval_end_ns,
        batch_bars=2, max_bars=3,
    )
    assert receipt.selected_count == 3
    assert receipt.first_event_ns == bars[0].clock.interval_end_ns
    assert receipt.last_event_ns == bars[-1].clock.interval_end_ns
    assert receipt.process_peak_rss_bytes > 0
    assert len(receipt.source_sha256) == len(receipt.selected_bars_sha256) == 64
    assert receipt.max_batch_bars == 2
    assert json.loads((target / "factor_tester_catalog_receipt.json").read_text())[
        "source_sha256"
    ] == receipt.source_sha256
    for item in receipt.catalog_files:
        path = target / item["path"]
        assert path.stat().st_size == item["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    catalog = ParquetDataCatalog(str(target))
    readback = catalog.query_bars(identifiers=[receipt.bar_type])
    assert len(readback) == 3
    assert [Decimal(str(bar.high)) for bar in readback] == [bar.high for bar in bars]
    assert [bar.ts_event for bar in readback] == [bar.clock.interval_end_ns for bar in bars]
    with pytest.raises(FileExistsError):
        stage_contract_minute_catalog(
            source, target, contract_uid=uid, instrument_spec=spec,
            start_ns=bars[0].clock.interval_end_ns,
            end_ns=bars[-1].clock.interval_end_ns,
        )


def test_budget_failure_does_not_publish_partial_catalog(tmp_path):
    require_nautilus()
    pytest.importorskip("pyarrow")
    source = ROOT / "data_mink_product/CFFEX_F_T_2403.parquet"
    if not source.is_file():
        pytest.skip("read-only local T source unavailable")
    bars = list(islice(iter_minute_bars(source, batch_size=2), 3))
    spec = FuturesContractSpec(
        "T2403", "CFFEX", "T", Decimal("0.005"), 3, Decimal("10000"),
        "CNY", 1, 2_000_000_000_000_000_000, Decimal("0.02"),
        Decimal("0.02"), "test-only fixture", resolved_contract_minute_source(),
    )
    target = tmp_path / "catalog"
    with pytest.raises(ValueError, match="max_bars"):
        stage_contract_minute_catalog(
            source, target, contract_uid="CFFEX|F|T|2403",
            instrument_spec=spec, start_ns=bars[0].clock.interval_end_ns,
            end_ns=bars[-1].clock.interval_end_ns,
            batch_bars=1, max_bars=2,
        )
    assert not target.exists()
    assert not list(tmp_path.iterdir())

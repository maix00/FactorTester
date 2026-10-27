from datetime import date, datetime, time
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from server.services.nautilus_bridge.backtest_runner import (
    ReplayInput, run_small_catalog_replay,
)
from server.services.nautilus_bridge.catalog import stage_contract_daily_catalog
from server.services.nautilus_bridge.market_data import FuturesContractSpec
from tests.nautilus_source_fixture import resolved_contract_minute_source
from tests.nautilus_runtime import require_nautilus


def test_daily_settlement_events_are_consumed_by_native_replay(tmp_path):
    require_nautilus()
    source = tmp_path / "daily.parquet"
    pq.write_table(pa.Table.from_pylist([
        {"TRADING_DAY": date(2024, 1, 2), "PRODUCT": "T",
         "CONTRACT": "T2403.CFE", "CONTRACT_UID": "CFFEX|F|T|2403",
         "OPEN": 102.9, "HIGH": 103.0, "LOW": 102.8, "CLOSE": 102.95,
         "VOLUME": 1000.0, "OPEN_INTEREST": 180000.0,
         "SETTLEMENT_PRICE": 102.94},
        {"TRADING_DAY": date(2024, 1, 3), "PRODUCT": "T",
         "CONTRACT": "T2403.CFE", "CONTRACT_UID": "CFFEX|F|T|2403",
         "OPEN": 102.95, "HIGH": 103.1, "LOW": 102.9, "CLOSE": 103.05,
         "VOLUME": 1100.0, "OPEN_INTEREST": 181000.0,
         "SETTLEMENT_PRICE": 103.04},
    ]), source)
    spec = FuturesContractSpec(
        "T2403", "CFFEX", "T", Decimal("0.005"), 3, Decimal("10000"),
        "CNY", 1, 2_000_000_000_000_000_000, Decimal("0.02"),
        Decimal("0.02"), "test-only fixture", resolved_contract_minute_source(),
    )
    target = tmp_path / "catalog"
    stage_contract_daily_catalog(
        source, target, contract_uid="CFFEX|F|T|2403",
        instrument_spec=spec, start_ns=0, end_ns=2_000_000_000_000_000_000,
        product_codes={"T"},
        session_for_day=lambda day: (
            datetime.combine(day, time(9, 30)),
            datetime.combine(day, time(15, 0)),
        ),
        batch_bars=1,
    )
    receipt = run_small_catalog_replay(
        (ReplayInput(target, "CFFEX|F|T|2403"),),
        tmp_path / "out", max_input_bars=2,
    )
    assert receipt.input_bars == 2
    assert receipt.native_settlements == 2
    assert receipt.native_iterations == 4

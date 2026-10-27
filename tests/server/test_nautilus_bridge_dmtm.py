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


def test_daily_settlement_posts_pnl_and_revalues_margin_on_open_position(tmp_path):
    import json
    from datetime import timedelta
    import pandas as pd

    require_nautilus()
    source = tmp_path / "daily.parquet"
    rows = []
    for index, day in enumerate([date(2024, 1, 2) + timedelta(days=offset) for offset in range(6)]):
        rows.append({
            "TRADING_DAY": day, "PRODUCT": "T", "CONTRACT": "T2403.CFE",
            "CONTRACT_UID": "CFFEX|F|T|2403",
            "OPEN": round(102.9 + index * 0.1, 3),
            "HIGH": round(103.0 + index * 0.1, 3),
            "LOW": round(102.8 + index * 0.1, 3),
            "CLOSE": round(102.95 + index * 0.1, 3),
            "VOLUME": 1000.0 + index, "OPEN_INTEREST": 180000.0 + index,
            "SETTLEMENT_PRICE": round(102.94 + index * 0.1, 3),
        })
    pq.write_table(pa.Table.from_pylist(rows), source)
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
    output = tmp_path / "out"
    receipt = run_small_catalog_replay(
        (ReplayInput(target, "CFFEX|F|T|2403"),), output,
        max_input_bars=6, max_replay_days=6, synthetic_order_probe=True,
    )
    assert receipt.native_settlements == 6
    positions = pd.read_csv(output / "positions.csv")
    events = positions.loc[0, "adjustments"]
    try:
        parsed = json.loads(events)
    except json.JSONDecodeError:
        import ast
        parsed = ast.literal_eval(events)
    adjustments = [item for item in parsed if item["type"] == "PositionAdjusted"]
    assert [item["adjustment_type"] for item in adjustments] == ["DAILY_SETTLEMENT"] * 3
    assert [item["pnl_change"] for item in adjustments] == [
        "400.00 CNY", "1000.00 CNY", "1000.00 CNY",
    ]
    timestamps = [int(item["ts_event"]) for item in adjustments]
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == 3
    assert positions.loc[0, "realized_pnl"] == "3000.00 CNY"
    account = pd.read_csv(output / "account.csv")
    assert account.iloc[-1]["total"] == 1003000.0
    margins = [
        item["maintenance"]
        for value in account["margins"]
        if isinstance(value, str) and "T2403.CFFEX" in value
        for item in __import__("ast").literal_eval(value)
    ]
    assert "2062.00" in margins and "2066.80" in margins

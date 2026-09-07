from __future__ import annotations

import pandas as pd
import sqlite3
import pytest

from server.modules.shared import price_services
from sources.LocalCNFutures import FeeData
from sources.OpenCTP import client as openctp_client
from sources.OpenCTP import fields as openctp_fields
from sources.OpenCTP.client import _clean_instrument_rows
from tools.products.Futures import Futures, FuturesContract


def _instrument_row(**overrides):
    row = {
        "ExchangeID": "CFFEX",
        "InstrumentID": "IF2606",
        "InstrumentName": "IF2606",
        "ProductClass": "1",
        "ProductID": "IF",
        "VolumeMultiple": 300,
        "PriceTick": 0.2,
        "MinLimitOrderVolume": 1,
        "MaxLimitOrderVolume": 20,
        "LongMarginRatioByMoney": 0.12,
        "ShortMarginRatioByMoney": 0.13,
        "LongMarginRatioByVolume": 0,
        "ShortMarginRatioByVolume": 0,
        "OpenRatioByMoney": 0.000023,
        "OpenRatioByVolume": 0,
        "CloseRatioByMoney": 0.000023,
        "CloseRatioByVolume": 0,
        "CloseTodayRatioByMoney": 0.00023,
        "CloseTodayRatioByVolume": 0,
    }
    row.update(overrides)
    return row


def test_clean_instrument_rows_maps_openctp_fields():
    specs = _clean_instrument_rows([_instrument_row()])

    row = specs.iloc[0]
    assert row["ExchangeID"] == "CFFEX"
    assert row["InstrumentID"] == "IF2606"
    assert row["ProductID"] == "IF"
    assert row["VolumeMultiple"] == 300
    assert row["PriceTick"] == 0.2
    assert row["MinLimitOrderVolume"] == 1
    assert row["LongMarginRatioByMoney"] == 0.12
    assert row["ShortMarginRatioByMoney"] == 0.13
    assert row["LongMarginRatioByVolume"] == 0
    assert row["ShortMarginRatioByVolume"] == 0
    assert row["NormalizedInstrumentID"] == "IF2606"


@pytest.mark.parametrize("field", ["multiplier", "point_value", "volume_multiple", "VolumeMultiple"])
def test_product_trading_spec_field_prefers_local_product_value(monkeypatch, field):
    openctp_fields._online_contract_specs.cache_clear()
    openctp_fields._online_product_specs.cache_clear()
    def unexpected_lookup(*_args, **_kwargs):
        raise AssertionError("an explicit local value must not query snapshots or network")

    monkeypatch.setattr(openctp_fields, "local_snapshot_field", unexpected_lookup)
    monkeypatch.setattr(openctp_fields, "fetch_instruments", unexpected_lookup)

    # Use an isolated identity: IF.CFE may already be a catalog singleton,
    # whose constructor correctly does not replace its original point value.
    future = Futures("LOCAL_SPEC.CFE", point_value=300, _local_only=True)

    assert future.get_trading_spec_field(field) == 300


def test_product_trading_spec_field_falls_back_to_openctp_contract(monkeypatch):
    openctp_fields._online_contract_specs.cache_clear()
    openctp_fields._online_product_specs.cache_clear()
    calls = []

    def fake_fetch_instruments(**kwargs):
        calls.append(kwargs)
        return [_instrument_row()]

    monkeypatch.setattr(openctp_fields, "fetch_instruments", fake_fetch_instruments)
    monkeypatch.setattr(FeeData, "get_contract_fee_row", lambda *args, **kwargs: None)
    monkeypatch.setattr(FeeData, "load_latest", lambda: pd.DataFrame())
    contract = FuturesContract("CFE|F|IF|2606", _local_only=True)

    assert contract.get_trading_spec_field("min_tick") == 0.2
    assert calls[0]["instruments"] == "IF2606"


def test_public_fields_fill_missing_local_snapshot_from_product_resolver(monkeypatch):
    openctp_fields._online_contract_specs.cache_clear()
    openctp_fields._online_product_specs.cache_clear()
    local = pd.DataFrame([{
        "date": "20260602",
        "variety_code": "IF",
        "multiplier": 300,
        "open_ratio": 0.0001,
    }])
    monkeypatch.setattr(FeeData, "load_latest", lambda: local)
    monkeypatch.setattr(openctp_fields, "fetch_instruments", lambda **kwargs: [_instrument_row()])

    future = Futures("IF.CFE", _local_only=True)
    fields = price_services.product_public_fields(future)

    assert fields["point_value"]["value"] == 300
    assert fields["min_tick"]["value"] == 0.2
    assert fields["min_trade_quantity"]["value"] == 1
    assert fields["trading_spec_source"]["value"] == "current_variety_snapshot+openctp_fallback"


def test_openctp_request_uses_data_dir_cache_before_network(monkeypatch, tmp_path):
    monkeypatch.setattr(openctp_client, "CACHE_DIR", tmp_path / "openctp")
    monkeypatch.setattr(openctp_client, "CACHE_DB_PATH", tmp_path / "localdata" / "unifieddata.sqlite")
    calls = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"rsp_code": 0, "data": [{"InstrumentID": "IF2606"}]}'

    def fake_urlopen(url, timeout):
        calls.append((url, timeout))
        return _Response()

    monkeypatch.setattr(openctp_client, "urlopen", fake_urlopen)

    first = openctp_client.fetch_instruments(instruments="IF2606")
    second = openctp_client.fetch_instruments(instruments="IF2606")

    assert first == second == [{"InstrumentID": "IF2606"}]
    assert len(calls) == 1
    with sqlite3.connect(tmp_path / "localdata" / "unifieddata.sqlite") as conn:
        count = conn.execute("SELECT count(*) FROM openctp_responses").fetchone()[0]
        spec = conn.execute(
            "SELECT InstrumentID, ProductID, OpenRatioByMoney, OpenRatioByVolume, "
            "LongMarginRatioByMoney, ShortMarginRatioByMoney "
            "FROM openctp_cnfutures_contract_specs"
        ).fetchone()
    assert count == 1
    assert spec == ("IF2606", None, None, None, None, None)

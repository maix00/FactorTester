from __future__ import annotations

import pandas as pd

from sources.FieldHistory.scripts import build_transaction_fee_exchange_baseline as builder


def test_build_exchange_baseline_forces_complementary_fee_unit_to_zero(monkeypatch) -> None:
    mapping = {
        "source_accessed_at": "2026-07-07T00:00:00+08:00",
        "baseline_effective_trading_day": "1900-01-02",
        "official_source_urls": {"DCE": "https://www.dce.com.cn/"},
        "products": [
            {"instrument": "A", "exchange": "DCE", "label": "豆一", "unit": "volume", "value": "2"},
        ],
    }
    monkeypatch.setattr(builder, "load_openctp_latest_market_rule_frame", lambda **_: pd.DataFrame([
        {
            "instrument": "A",
            "field_name": "OpenRatioByMoney",
            "value": 0.0000008,
            "contract_codes": [],
        },
        {
            "instrument": "A",
            "field_name": "OpenRatioByVolume",
            "value": 2.01,
            "contract_codes": [],
        },
    ]))

    events, audit = builder.build_events(mapping)
    by_field = {event["field_name"]: event["value"] for event in events}

    assert by_field["OpenRatioByMoney"] == 0.0
    assert by_field["OpenRatioByVolume"] == 2.0
    assert audit[0]["inactive_openctp_nonzero"] is True


def test_build_exchange_baseline_keeps_exchange_table_when_openctp_differs(monkeypatch) -> None:
    mapping = {
        "source_accessed_at": "2026-07-07T00:00:00+08:00",
        "baseline_effective_trading_day": "1900-01-02",
        "official_source_urls": {"CFFEX": "https://www.cffex.com.cn/"},
        "products": [
            {"instrument": "IF", "exchange": "CFFEX", "label": "沪深300股指期货", "unit": "money", "value": "0.0023%"},
        ],
    }
    monkeypatch.setattr(builder, "load_openctp_latest_market_rule_frame", lambda **_: pd.DataFrame([
        {
            "instrument": "IF",
            "field_name": "CloseTodayRatioByMoney",
            "value": 0.0002308,
            "contract_codes": [],
        },
        {
            "instrument": "IF",
            "field_name": "CloseTodayRatioByVolume",
            "value": 0.01,
            "contract_codes": [],
        },
    ]))

    events, audit = builder.build_events(mapping)
    by_field = {event["field_name"]: event["value"] for event in events}

    assert by_field["OpenRatioByMoney"] == 0.000023
    assert by_field["CloseRatioByMoney"] == 0.000023
    assert by_field["CloseTodayRatioByMoney"] == 0.000023
    assert by_field["CloseTodayRatioByVolume"] == 0.0
    assert [row for row in audit if row["leg"] == "平今"][0]["active_source"] == "table-openctp-mismatch"


def test_baseline_map_classifies_czce_propylene_as_money_fee() -> None:
    mapping = builder._load_mapping(builder.DEFAULT_MAP)
    propylene = next(row for row in mapping["products"] if row["instrument"] == "PL")

    assert propylene["exchange"] == "CZCE"
    assert propylene["unit"] == "money"
    assert propylene["value"] == "0.01%"


def test_baseline_map_uses_official_shfe_fee_standard_values() -> None:
    mapping = builder._load_mapping(builder.DEFAULT_MAP)
    by_instrument = {row["instrument"]: row for row in mapping["products"]}

    assert by_instrument["AU"]["unit"] == "volume"
    assert by_instrument["AU"]["value"] == "20"
    assert by_instrument["FU"]["unit"] == "money"
    assert by_instrument["FU"]["value"] == "0.005%"

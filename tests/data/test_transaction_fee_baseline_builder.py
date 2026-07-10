from __future__ import annotations

import pandas as pd
import pytest

from sources.FieldHistory.scripts import build_transaction_fee_exchange_baseline as builder


def test_build_exchange_fee_table_builder_emits_audit_not_history_events(monkeypatch) -> None:
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

    assert events == []
    assert audit[0]["baseline_volume"] == 2.0
    assert audit[0]["baseline_money"] is None
    assert audit[0]["inactive_openctp_nonzero"] is True


def test_build_exchange_fee_table_audit_does_not_infer_close_today_from_generic_fee(monkeypatch) -> None:
    mapping = {
        "source_accessed_at": "2026-07-07T00:00:00+08:00",
        "baseline_effective_trading_day": "1900-01-02",
        "official_source_urls": {"CZCE": "https://www.czce.com.cn/"},
        "products": [
            {"instrument": "CY", "exchange": "CZCE", "label": "棉纱", "unit": "volume", "value": "4"},
        ],
    }
    monkeypatch.setattr(builder, "load_openctp_latest_market_rule_frame", lambda **_: pd.DataFrame())

    events, audit = builder.build_events(mapping)

    assert events == []
    assert {row["leg"] for row in audit} == {"开仓", "平昨"}


def test_build_exchange_fee_table_audit_marks_openctp_mismatch(monkeypatch) -> None:
    mapping = {
        "source_accessed_at": "2026-07-07T00:00:00+08:00",
        "baseline_effective_trading_day": "1900-01-02",
        "official_source_urls": {"CFFEX": "https://www.cffex.com.cn/"},
        "products": [
            {
                "instrument": "IF",
                "exchange": "CFFEX",
                "label": "沪深300股指期货",
                "unit": "money",
                "value": "0.0023%",
                "leg_values": {"close_today": "0.0023%"},
            },
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

    assert events == []
    assert [row for row in audit if row["leg"] == "平今"][0]["active_source"] == "table-openctp-mismatch"


def test_baseline_map_uses_cffex_close_today_index_future_fee() -> None:
    mapping = builder._load_mapping(builder.DEFAULT_MAP)
    by_instrument = {row["instrument"]: row for row in mapping["products"]}

    for instrument in ("IC", "IF", "IH", "IM"):
        row = by_instrument[instrument]
        assert row["value"] == "0.0023%"
        assert row["leg_values"]["close_today"] == "0.023%"


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


def test_baseline_map_uses_official_czce_fee_standard_values() -> None:
    mapping = builder._load_mapping(builder.DEFAULT_MAP)
    by_instrument = {row["instrument"]: row for row in mapping["products"]}

    assert by_instrument["SF"]["value"] == "3"
    assert by_instrument["SM"]["value"] == "3"
    assert by_instrument["PF"]["value"] == "2"
    assert by_instrument["PL"]["label"] == "丙烯"
    assert by_instrument["PL"]["value"] == "0.01%"
    assert by_instrument["PR"]["label"] == "瓶片"
    assert by_instrument["PR"]["value"] == "0.005%"


def test_build_exchange_fee_table_audit_supports_leg_specific_money_fees(monkeypatch) -> None:
    mapping = {
        "source_accessed_at": "2026-07-07T00:00:00+08:00",
        "baseline_effective_trading_day": "1900-01-02",
        "official_source_urls": {"DCE": "https://www.dce.com.cn/"},
        "products": [
            {
                "instrument": "J",
                "exchange": "DCE",
                "label": "焦炭",
                "unit": "money",
                "value": "0.01%",
                "leg_values": {"open": "0.014%", "close": "0.01%", "close_today": "0.014%"},
            },
        ],
    }
    monkeypatch.setattr(builder, "load_openctp_latest_market_rule_frame", lambda **_: pd.DataFrame())

    events, _audit = builder.build_events(mapping)

    assert events == []
    by_leg = {row["leg"]: row for row in _audit}
    assert by_leg["开仓"]["baseline_money"] == pytest.approx(0.00014)
    assert by_leg["平昨"]["baseline_money"] == 0.0001
    assert by_leg["平今"]["baseline_money"] == pytest.approx(0.00014)
    assert by_leg["开仓"]["baseline_volume"] is None

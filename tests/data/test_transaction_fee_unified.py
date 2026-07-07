from __future__ import annotations

import pandas as pd

from sources.FieldHistory.views.TransactionFee import (
    build_fee_unit_classification_frame,
    build_fee_verification_frame,
    build_unified_frame,
)
from tools.data.field_history import FIELD_HISTORY_COLUMNS


def _fee_source_frame() -> pd.DataFrame:
    base = {
        "instrument": "A",
        "instrument_label": "豆一",
        "instrument_type": "future",
        "field_name": "OpenRatioByVolume",
        "effective_trading_day": "1900-01-01",
        "effective_timestamp": "",
        "value_type": "",
        "contract_codes": "[]",
        "source_url": "",
        "source_date": "",
        "source_notice_id": "",
        "raw_note": "",
    }
    return pd.DataFrame([
        {
            **base,
            "provider": "DCE",
            "source_key": "exchange/a/open",
            "value": 2.0,
            "source_notice_id": "exchange notice",
        },
        {
            **base,
            "provider": "OpenCTP:latest",
            "source_key": "openctp/a/open",
            "value": 2.01,
            "source_notice_id": "OpenCTP latest snapshot",
        },
    ], columns=FIELD_HISTORY_COLUMNS)


def test_transaction_fee_unified_can_build_exchange_and_broker_views() -> None:
    source = _fee_source_frame()

    exchange = build_unified_frame(source, transaction_fee_source="exchange")
    broker = build_unified_frame(source, transaction_fee_source="openctp")

    assert exchange["value"].tolist() == [2.0]
    assert broker["value"].tolist() == [2.01]
    assert "DCE" in exchange["providers"].iloc[0]
    assert "OpenCTP:latest" in broker["providers"].iloc[0]


def test_transaction_fee_classification_tracks_unit_changes_by_effective_day() -> None:
    rows = []
    for day, money, volume in [
        ("1900-01-01", 0.0, 2.0),
        ("2026-01-01", 0.0001, 0.0),
    ]:
        for field_name, value in [
            ("OpenRatioByMoney", money),
            ("OpenRatioByVolume", volume),
        ]:
            rows.append({
                **_base_row(field_name=field_name, value=value, effective_trading_day=day),
                "provider": "Agent:DCE",
                "source_key": f"exchange/a/{day}/{field_name}",
                "source_notice_id": f"notice-{day}",
            })

    classification = build_fee_unit_classification_frame(build_unified_frame(pd.DataFrame(rows, columns=FIELD_HISTORY_COLUMNS), transaction_fee_source="exchange"))

    assert classification[["effective_trading_day", "open_unit"]].values.tolist() == [
        ["1900-01-01", "volume"],
        ["2026-01-01", "money"],
    ]


def test_transaction_fee_classification_forwards_unchanged_fee_legs() -> None:
    rows = []
    for field_name, value in [
        ("OpenRatioByVolume", 5.0),
        ("CloseRatioByVolume", 5.0),
        ("CloseTodayRatioByVolume", 20.0),
    ]:
        rows.append({
            **_base_row(field_name=field_name, value=value, effective_trading_day="1900-01-01"),
            "provider": "Agent:CZCE",
            "source_key": f"exchange/ap/baseline/{field_name}",
            "instrument": "AP",
            "instrument_label": "苹果",
            "source_notice_id": "郑商函〔2018〕209号",
        })
    rows.append({
        **_base_row(field_name="CloseTodayRatioByVolume", value=10.0, effective_trading_day="2026-06-08"),
        "provider": "Agent:CZCE",
        "source_key": "exchange/ap/20260608/close_today",
        "instrument": "AP",
        "instrument_label": "苹果",
        "source_notice_id": "郑商函〔2026〕477号",
    })

    classification = build_fee_unit_classification_frame(
        build_unified_frame(pd.DataFrame(rows, columns=FIELD_HISTORY_COLUMNS), transaction_fee_source="exchange")
    )
    latest = classification.sort_values("effective_trading_day").iloc[-1]

    assert latest["effective_trading_day"] == "2026-06-08"
    assert latest["open_volume"] == 5.0
    assert latest["close_volume"] == 5.0
    assert latest["close_today_volume"] == 10.0


def test_transaction_fee_classification_ignores_label_drift_for_same_instrument() -> None:
    rows = []
    for field_name, value in [
        ("OpenRatioByMoney", 0.00005),
        ("CloseRatioByMoney", 0.00005),
        ("CloseTodayRatioByMoney", 0.00005),
    ]:
        rows.append({
            **_base_row(field_name=field_name, value=value, effective_trading_day="1900-01-01"),
            "provider": "Agent:SHFE",
            "source_key": f"exchange/bu/baseline/{field_name}",
            "instrument": "BU",
            "instrument_label": "沥青",
            "source_notice_id": "exchange-baseline-user-table-2026-07-07",
        })
    rows.append({
        **_base_row(field_name="CloseTodayRatioByMoney", value=0.0, effective_trading_day="2024-04-26"),
        "provider": "Agent:SHFE",
        "source_key": "exchange/bu/20240426/close_today_money",
        "instrument": "BU",
        "instrument_label": "石油沥青",
        "source_notice_id": "上期发〔2024〕126号",
    })
    rows.append({
        **_base_row(field_name="CloseTodayRatioByVolume", value=0.0, effective_trading_day="2024-04-26"),
        "provider": "Agent:SHFE",
        "source_key": "exchange/bu/20240426/close_today_volume",
        "instrument": "BU",
        "instrument_label": "石油沥青",
        "source_notice_id": "上期发〔2024〕126号",
    })

    classification = build_fee_unit_classification_frame(
        build_unified_frame(pd.DataFrame(rows, columns=FIELD_HISTORY_COLUMNS), transaction_fee_source="exchange")
    )
    latest = classification.sort_values("effective_trading_day").iloc[-1]

    assert latest["instrument_label"] == "石油沥青"
    assert latest["open_money"] == 0.00005
    assert latest["close_money"] == 0.00005
    assert latest["close_today_unit"] == "zero"


def test_transaction_fee_verification_accepts_openctp_broker_addon() -> None:
    exchange_rows = [
        {
            **_base_row(field_name="OpenRatioByVolume", value=2.0),
            "provider": "Agent:DCE",
            "source_key": "exchange/a/open_volume",
            "source_notice_id": "exchange-baseline-user-table-2026-07-07",
        },
        {
            **_base_row(field_name="OpenRatioByMoney", value=0.0),
            "provider": "Agent:DCE",
            "source_key": "exchange/a/open_money",
            "source_notice_id": "exchange-baseline-user-table-2026-07-07",
        },
    ]
    openctp_rows = [
        {
            **_base_row(field_name="OpenRatioByVolume", value=2.01),
            "provider": "OpenCTP:latest",
            "source_key": "openctp/a/open_volume",
            "source_notice_id": "OpenCTP latest snapshot",
        },
        {
            **_base_row(field_name="OpenRatioByMoney", value=0.0000008),
            "provider": "OpenCTP:latest",
            "source_key": "openctp/a/open_money",
            "source_notice_id": "OpenCTP latest snapshot",
        },
    ]
    exchange = build_unified_frame(pd.DataFrame(exchange_rows, columns=FIELD_HISTORY_COLUMNS), transaction_fee_source="exchange")
    openctp = build_unified_frame(pd.DataFrame(openctp_rows, columns=FIELD_HISTORY_COLUMNS), transaction_fee_source="openctp")

    verification = build_fee_verification_frame(exchange, openctp)
    row = verification[verification["leg"] == "open"].iloc[0]

    assert row["unit"] == "volume"
    assert row["openctp_delta"] == 0.009999999999999787
    assert row["verification_status"] == "cross_checked_openctp"


def test_transaction_fee_verification_does_not_compare_historical_notice_to_current_openctp() -> None:
    exchange_rows = [
        {
            **_base_row(field_name="OpenRatioByVolume", value=2.0, effective_trading_day="2023-01-01"),
            "provider": "Agent:DCE",
            "source_key": "exchange/a/2023/open_volume",
            "source_notice_id": "大商所发〔2023〕1号",
            "source_url": "https://secondary.example.com/dce-notice",
        },
        {
            **_base_row(field_name="OpenRatioByMoney", value=0.0, effective_trading_day="2023-01-01"),
            "provider": "Agent:DCE",
            "source_key": "exchange/a/2023/open_money",
            "source_notice_id": "大商所发〔2023〕1号",
            "source_url": "https://secondary.example.com/dce-notice",
        },
    ]
    openctp_rows = [
        {
            **_base_row(field_name="OpenRatioByVolume", value=5.01),
            "provider": "OpenCTP:latest",
            "source_key": "openctp/a/open_volume",
            "source_notice_id": "OpenCTP latest snapshot",
        },
        {
            **_base_row(field_name="OpenRatioByMoney", value=0.0000008),
            "provider": "OpenCTP:latest",
            "source_key": "openctp/a/open_money",
            "source_notice_id": "OpenCTP latest snapshot",
        },
    ]
    exchange = build_unified_frame(pd.DataFrame(exchange_rows, columns=FIELD_HISTORY_COLUMNS), transaction_fee_source="exchange")
    openctp = build_unified_frame(pd.DataFrame(openctp_rows, columns=FIELD_HISTORY_COLUMNS), transaction_fee_source="openctp")

    verification = build_fee_verification_frame(exchange, openctp)
    row = verification[verification["leg"] == "open"].iloc[0]

    assert row["unit"] == "volume"
    assert row["verification_status"] == "historical_notice_secondary"


def _base_row(*, field_name: str, value: float, effective_trading_day: str = "1900-01-01") -> dict:
    return {
        "provider": "Agent:DCE",
        "source_key": f"exchange/a/{field_name}",
        "instrument": "A",
        "instrument_label": "豆一",
        "instrument_type": "future",
        "field_name": field_name,
        "effective_trading_day": effective_trading_day,
        "effective_timestamp": "",
        "value": value,
        "value_type": "",
        "contract_codes": "[]",
        "source_url": "https://www.dce.com.cn/",
        "source_date": "",
        "source_notice_id": "exchange",
        "raw_note": "",
    }

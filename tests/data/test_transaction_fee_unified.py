from __future__ import annotations

import pandas as pd

from sources.FieldHistory.views.TransactionFee import build_unified_frame
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

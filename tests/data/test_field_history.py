from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tools.data.field_history import (
    FieldHistoryProvider,
    HistoricalFieldFallbackPolicy,
    MissingHistoricalField,
    TimestampTradingDayResolver,
    load_historical_field_provider,
    save_historical_field_records,
)
from tools.data.hub import DataHub, SQLiteStore


def _records() -> list[dict]:
    return [
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "BZ",
            "instrument_label": "纯苯",
            "instrument_type": "future",
            "field_name": "MaxLimitOrderVolume",
            "effective_trading_day": "2026-01-05",
            "value": 500,
        },
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "BZ",
            "instrument_label": "纯苯",
            "instrument_type": "future",
            "field_name": "MaxLimitOrderVolume",
            "effective_trading_day": "2026-01-06",
            "effective_timestamp": "2026-01-05 21:00:00",
            "value": 100,
        },
    ]


def _resolver() -> TimestampTradingDayResolver:
    return TimestampTradingDayResolver({
        pd.Timestamp("2026-01-05 20:59:00"): pd.Timestamp("2026-01-05"),
        # 夜盘 21:00 属于下一个交易日。
        pd.Timestamp("2026-01-05 21:00:00"): pd.Timestamp("2026-01-06"),
        pd.Timestamp("2026-01-05 21:01:00"): pd.Timestamp("2026-01-06"),
    })


def test_field_history_resolves_by_timestamp_and_trading_day() -> None:
    provider = FieldHistoryProvider.from_records(_records())
    resolver = _resolver()

    before = provider.resolve_at(
        "BZ",
        "MaxLimitOrderVolume",
        pd.Timestamp("2026-01-05 20:59:00"),
        trading_day_resolver=resolver,
    )
    at_night_open = provider.resolve_at(
        "BZ",
        "MaxLimitOrderVolume",
        pd.Timestamp("2026-01-05 21:00:00"),
        trading_day_resolver=resolver,
    )

    assert before.value == 500
    assert at_night_open.value == 100
    assert at_night_open.effective_trading_day == pd.Timestamp("2026-01-06")
    assert at_night_open.effective_timestamp == pd.Timestamp("2026-01-05 21:00:00")


def test_field_history_values_for_index_preserves_timestamp_index() -> None:
    provider = FieldHistoryProvider.from_records(_records())
    index = pd.DatetimeIndex([
        pd.Timestamp("2026-01-05 20:59:00"),
        pd.Timestamp("2026-01-05 21:00:00"),
        pd.Timestamp("2026-01-05 21:01:00"),
    ])

    values = provider.values_for_index(
        "BZ",
        "MaxLimitOrderVolume",
        index,
        trading_day_resolver=_resolver(),
    )

    assert list(values.index) == list(index)
    assert values.tolist() == [500, 100, 100]


def test_field_history_strict_mode_raises_when_product_or_field_missing() -> None:
    provider = FieldHistoryProvider.from_records(_records())

    with pytest.raises(MissingHistoricalField):
        provider.resolve_at(
            "UNKNOWN",
            "MaxLimitOrderVolume",
            pd.Timestamp("2026-01-05 21:00:00"),
            trading_day_resolver=_resolver(),
            fallback=HistoricalFieldFallbackPolicy.STRICT_HISTORICAL,
        )


def test_field_history_store_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "field_history.sqlite"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key="field_history_test",
        label="field-history-test",
        path_getter=lambda: str(db_path),
    ))

    save_historical_field_records(
        _records(),
        store_key="field_history_test",
        replace_provider="test",
        replace_source_key="test/rules",
    )
    provider = load_historical_field_provider(store_key="field_history_test")

    resolved = provider.resolve_at(
        "BZ",
        "MaxLimitOrderVolume",
        pd.Timestamp("2026-01-05 21:00:00"),
        trading_day_resolver=_resolver(),
    )
    assert resolved.value == 100

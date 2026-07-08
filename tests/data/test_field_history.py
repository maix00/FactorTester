from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tools.data.field_history import (
    FIELD_HISTORY_COLUMNS,
    FieldHistoryProvider,
    HistoricalFieldFallbackPolicy,
    MissingHistoricalField,
    TimestampTradingDayResolver,
    load_market_rule_field_provider,
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


def test_market_rule_provider_separates_exchange_and_openctp_fee_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    exchange_row = {
        "provider": "DCE",
        "source_key": "exchange/a/open_fee",
        "instrument": "A",
        "instrument_label": "豆一",
        "instrument_type": "future",
        "field_name": "OpenRatioByVolume",
        "effective_trading_day": "1900-01-01",
        "effective_timestamp": "",
        "value": 2.0,
        "value_type": "",
        "contract_codes": "[]",
        "source_url": "exchange",
        "source_date": "",
        "source_notice_id": "exchange",
        "raw_note": "exchange base fee",
    }
    broker_row = {
        **exchange_row,
        "provider": "OpenCTP:latest",
        "source_key": "openctp/a/open_fee",
        "value": 2.01,
        "source_url": "OpenCTP latest",
        "source_notice_id": "OpenCTP latest snapshot",
        "raw_note": "broker effective fee",
    }
    monkeypatch.setattr(
        "tools.data.field_history.load_historical_field_frame",
        lambda **_: pd.DataFrame([exchange_row], columns=FIELD_HISTORY_COLUMNS),
    )
    monkeypatch.setattr(
        "tools.data.field_history.load_openctp_latest_market_rule_frame",
        lambda **_: pd.DataFrame([broker_row], columns=FIELD_HISTORY_COLUMNS),
    )
    resolver = TimestampTradingDayResolver({
        pd.Timestamp("2026-01-05 09:00:00"): pd.Timestamp("2026-01-05"),
    })

    exchange = load_market_rule_field_provider(transaction_fee_source="exchange")
    openctp = load_market_rule_field_provider(transaction_fee_source="openctp")

    assert exchange.resolve_at(
        "A",
        "OpenRatioByVolume",
        pd.Timestamp("2026-01-05 09:00:00"),
        trading_day_resolver=resolver,
    ).value == 2.0
    assert openctp.resolve_at(
        "A",
        "OpenRatioByVolume",
        pd.Timestamp("2026-01-05 09:00:00"),
        trading_day_resolver=resolver,
    ).value == 2.01


def test_contract_specific_fee_overrides_product_fee_baseline() -> None:
    rows = []
    for contract_codes, value in [("[]", 2.0), ('["2605"]', 6.0)]:
        rows.append({
            "provider": "DCE",
            "source_key": f"exchange/a/{contract_codes}",
            "instrument": "A",
            "instrument_label": "豆一",
            "instrument_type": "future",
            "field_name": "OpenRatioByVolume",
            "effective_trading_day": "1900-01-01",
            "effective_timestamp": "",
            "value": value,
            "value_type": "",
            "contract_codes": contract_codes,
            "source_url": "https://www.dce.com.cn/",
            "source_date": "",
            "source_notice_id": "exchange",
            "raw_note": "exchange fee",
        })
    provider = FieldHistoryProvider.from_records(rows)
    resolver = TimestampTradingDayResolver({
        pd.Timestamp("2026-01-05 09:00:00"): pd.Timestamp("2026-01-05"),
    })

    product = provider.resolve_at(
        "A",
        "OpenRatioByVolume",
        pd.Timestamp("2026-01-05 09:00:00"),
        trading_day_resolver=resolver,
    )
    contract = provider.resolve_at(
        "A2605.DCE",
        "OpenRatioByVolume",
        pd.Timestamp("2026-01-05 09:00:00"),
        trading_day_resolver=resolver,
    )

    assert product.value == 2.0
    assert contract.value == 6.0
    assert contract.contract_code == "2605"


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


def test_field_history_values_for_index_uses_vectorized_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FieldHistoryProvider.from_records(_records())

    def _unexpected_resolve_at(*args: object, **kwargs: object) -> None:
        raise AssertionError("values_for_index must not call resolve_at for each timestamp")

    monkeypatch.setattr(provider, "resolve_at", _unexpected_resolve_at)

    values = provider.values_for_index(
        "BZ",
        "MaxLimitOrderVolume",
        pd.DatetimeIndex([
            pd.Timestamp("2026-01-05 20:59:00"),
            pd.Timestamp("2026-01-05 21:00:00"),
            pd.Timestamp("2026-01-05 21:01:00"),
        ]),
        trading_day_resolver=_resolver(),
    )

    assert values.tolist() == [500, 100, 100]


def test_field_history_tz_aware_market_timestamps_use_local_wall_clock() -> None:
    provider = FieldHistoryProvider.from_records(_records())
    ts = pd.Timestamp("2026-01-05 21:01:00", tz="Asia/Shanghai")
    resolver = TimestampTradingDayResolver({
        pd.Timestamp("2026-01-05 21:01:00", tz="Asia/Shanghai"): pd.Timestamp("2026-01-06"),
    })

    resolved = provider.resolve_at(
        "BZ",
        "MaxLimitOrderVolume",
        ts,
        trading_day_resolver=resolver,
    )

    assert resolved.value == 100


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


def test_latest_available_fallback_uses_nearest_trading_day_not_last_row() -> None:
    provider = FieldHistoryProvider.from_records([
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "BZ",
            "instrument_type": "future",
            "field_name": "MaxLimitOrderVolume",
            "effective_trading_day": "2026-01-10",
            "value": 100,
        },
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "BZ",
            "instrument_type": "future",
            "field_name": "MaxLimitOrderVolume",
            "effective_trading_day": "2026-02-01",
            "value": 900,
        },
    ])

    resolved = provider.resolve_by_trading_day(
        "BZ",
        "MaxLimitOrderVolume",
        "2026-01-08",
        fallback=HistoricalFieldFallbackPolicy.LATEST_AVAILABLE,
    )

    assert resolved.value == 100
    assert resolved.effective_trading_day == pd.Timestamp("2026-01-10")
    assert resolved.approximated is True


def test_values_for_index_latest_available_fallback_uses_nearest_row_per_timestamp() -> None:
    provider = FieldHistoryProvider.from_records([
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "BZ",
            "instrument_type": "future",
            "field_name": "MaxLimitOrderVolume",
            "effective_trading_day": "2026-01-10",
            "value": 100,
        },
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "BZ",
            "instrument_type": "future",
            "field_name": "MaxLimitOrderVolume",
            "effective_trading_day": "2026-02-01",
            "value": 900,
        },
    ])
    timestamp = pd.Timestamp("2026-01-08 09:00:00")

    values = provider.values_for_index(
        "BZ",
        "MaxLimitOrderVolume",
        pd.DatetimeIndex([timestamp]),
        trading_day_resolver=TimestampTradingDayResolver({timestamp: pd.Timestamp("2026-01-08")}),
        fallback=HistoricalFieldFallbackPolicy.LATEST_AVAILABLE,
    )

    assert values.tolist() == [100]


def test_exchange_transaction_fee_latest_available_does_not_backfill_future_event() -> None:
    provider = FieldHistoryProvider.from_records([
        {
            "provider": "Agent:DCE",
            "source_key": "exchange/a/open_fee",
            "instrument": "A",
            "instrument_type": "future",
            "field_name": "OpenRatioByVolume",
            "effective_trading_day": "2026-06-22",
            "value": 2.0,
        },
    ])

    with pytest.raises(MissingHistoricalField):
        provider.resolve_by_trading_day(
            "A",
            "OpenRatioByVolume",
            "2026-01-05",
            fallback=HistoricalFieldFallbackPolicy.LATEST_AVAILABLE,
        )


def test_openctp_transaction_fee_latest_available_backfills_latest_snapshot() -> None:
    provider = FieldHistoryProvider.from_records([
        {
            "provider": "OpenCTP:latest",
            "source_key": "openctp/latest_snapshot/20260622/A/OpenRatioByVolume/product",
            "instrument": "A",
            "instrument_type": "future",
            "field_name": "OpenRatioByVolume",
            "effective_trading_day": "2026-06-22",
            "value": 2.01,
        },
    ])

    resolved = provider.resolve_by_trading_day(
        "A",
        "OpenRatioByVolume",
        "2026-01-05",
        fallback=HistoricalFieldFallbackPolicy.LATEST_AVAILABLE,
    )

    assert resolved.value == 2.01
    assert resolved.approximated is True


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


def test_field_history_separates_futures_and_options_for_same_code() -> None:
    provider = FieldHistoryProvider.from_records([
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "CU",
            "instrument_type": "future",
            "field_name": "MaxLimitOrderVolume",
            "effective_trading_day": "2026-01-05",
            "value": 500,
        },
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "CU",
            "instrument_type": "option",
            "field_name": "MaxLimitOrderVolume",
            "effective_trading_day": "2026-01-05",
            "value": 100,
        },
    ])

    future_value = provider.resolve_by_trading_day("CU", "MaxLimitOrderVolume", "2026-01-06")
    option_value = provider.resolve_by_trading_day(
        "CU",
        "MaxLimitOrderVolume",
        "2026-01-06",
        instrument_type="option",
    )

    assert future_value.value == 500
    assert option_value.value == 100


def test_field_history_contract_specific_rule_overrides_product_level_rule() -> None:
    provider = FieldHistoryProvider.from_records([
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "BZ",
            "instrument_type": "future",
            "field_name": "MinLimitOrderVolume",
            "effective_trading_day": "2026-06-23",
            "value": 1,
            "contract_codes": [],
        },
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "BZ",
            "instrument_type": "future",
            "field_name": "MinLimitOrderVolume",
            "effective_trading_day": "2026-03-09",
            "value": 4,
            "contract_codes": ["2606"],
        },
    ])

    product_value = provider.resolve_by_trading_day("BZ", "MinLimitOrderVolume", "2026-06-24")
    contract_value = provider.resolve_by_trading_day("BZ2606.DCE", "MinLimitOrderVolume", "2026-06-24")

    assert product_value.value == 1
    assert contract_value.value == 4
    assert contract_value.contract_code == "2606"


def test_field_history_pipe_contract_with_alpha_suffix_uses_product_baseline() -> None:
    provider = FieldHistoryProvider.from_records([
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "L_F",
            "instrument_type": "future",
            "field_name": "VolumeMultiple",
            "effective_trading_day": "1900-01-01",
            "value": 5,
            "contract_codes": [],
        },
    ])
    resolver = TimestampTradingDayResolver({
        pd.Timestamp("2026-01-05 09:01:00"): pd.Timestamp("2026-01-05"),
    })

    resolved = provider.resolve_at(
        "DCE|F|L|2605F",
        "VolumeMultiple",
        pd.Timestamp("2026-01-05 09:01:00"),
        trading_day_resolver=resolver,
        fallback=HistoricalFieldFallbackPolicy.LATEST_AVAILABLE,
    )

    assert resolved.value == 5
    assert resolved.instrument == "L_F"
    assert resolved.contract_code == "2605F"


def test_field_history_pipe_contract_with_alpha_suffix_prefers_exact_contract_rule() -> None:
    provider = FieldHistoryProvider.from_records([
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "L_F",
            "instrument_type": "future",
            "field_name": "VolumeMultiple",
            "effective_trading_day": "1900-01-01",
            "value": 5,
            "contract_codes": [],
        },
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "L_F",
            "instrument_type": "future",
            "field_name": "VolumeMultiple",
            "effective_trading_day": "2026-01-01",
            "value": 50,
            "contract_codes": ["2605F"],
        },
    ])

    resolved = provider.resolve_by_trading_day("DCE|F|L|2605F", "VolumeMultiple", "2026-01-05")

    assert resolved.value == 50
    assert resolved.instrument == "L_F"
    assert resolved.contract_code == "2605F"


def test_field_history_open_ended_baseline_applies_before_source_snapshot() -> None:
    provider = FieldHistoryProvider.from_records([
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "CU",
            "instrument_type": "future",
            "field_name": "MaxLimitOrderVolume",
            "effective_trading_day": "1900-01-01",
            "value": 500,
            "source_date": "2026-06-23",
        },
    ])

    resolved = provider.resolve_by_trading_day("CU", "MaxLimitOrderVolume", "2026-03-10")

    assert resolved.value == 500
    assert resolved.effective_trading_day == pd.Timestamp("1900-01-01")


def test_field_history_product_object_uses_main_contract_for_contract_specific_rule() -> None:
    class DummyFutures:
        name = "BZ.DCE"

        def get_contract_id_from_trading_day(self, trading_day):
            return "BZ2606.DCE"

    provider = FieldHistoryProvider.from_records([
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "BZ",
            "instrument_type": "future",
            "field_name": "MinLimitOrderVolume",
            "effective_trading_day": "2026-06-23",
            "value": 1,
            "contract_codes": [],
        },
        {
            "provider": "test",
            "source_key": "test/rules",
            "instrument": "BZ",
            "instrument_type": "future",
            "field_name": "MinLimitOrderVolume",
            "effective_trading_day": "2026-03-09",
            "value": 4,
            "contract_codes": ["2606"],
        },
    ])
    index = pd.DatetimeIndex([pd.Timestamp("2026-06-24 09:01:00")])

    values = provider.values_for_index(
        DummyFutures(),
        "MinLimitOrderVolume",
        index,
        trading_day_resolver=TimestampTradingDayResolver({
            pd.Timestamp("2026-06-24 09:01:00"): pd.Timestamp("2026-06-24"),
        }),
    )

    assert values.iloc[0] == 4


def test_field_history_from_contract_scope_applies_to_later_contracts_only() -> None:
    provider = FieldHistoryProvider.from_records([
        {
            "provider": "test",
            "source_key": "test/baseline",
            "instrument": "PK",
            "instrument_type": "future",
            "field_name": "OpenRatioByVolume",
            "effective_trading_day": "2026-01-01",
            "value": 4,
            "contract_codes": [],
        },
        {
            "provider": "test",
            "source_key": "test/from-2607",
            "instrument": "PK",
            "instrument_type": "future",
            "field_name": "OpenRatioByVolume",
            "effective_trading_day": "2026-06-24",
            "value": 2,
            "contract_scope_type": "from_contract",
            "contract_code_start": "2607",
        },
        {
            "provider": "test",
            "source_key": "test/old-2605-unchanged",
            "instrument": "PK",
            "instrument_type": "future",
            "field_name": "OpenRatioByVolume",
            "effective_trading_day": "2026-06-24",
            "value": 4,
            "contract_codes": ["2605"],
            "change_type": "exception_unchanged",
        },
    ])

    assert provider.resolve_by_trading_day("PK2605.CZC", "OpenRatioByVolume", "2026-06-25").value == 4
    assert provider.resolve_by_trading_day("PK2607.CZC", "OpenRatioByVolume", "2026-06-25").value == 2
    assert provider.resolve_by_trading_day("PK2701.CZC", "OpenRatioByVolume", "2026-06-25").value == 2


def test_field_history_vectorized_from_contract_scope_matches_single_lookup() -> None:
    provider = FieldHistoryProvider.from_records([
        {
            "provider": "test",
            "source_key": "test/baseline",
            "instrument": "PK",
            "instrument_type": "future",
            "field_name": "OpenRatioByVolume",
            "effective_trading_day": "2026-01-01",
            "value": 4,
            "contract_codes": [],
        },
        {
            "provider": "test",
            "source_key": "test/from-2607",
            "instrument": "PK",
            "instrument_type": "future",
            "field_name": "OpenRatioByVolume",
            "effective_trading_day": "2026-06-24",
            "value": 2,
            "contract_scope_type": "from_contract",
            "contract_code_start": "2607",
        },
    ])
    resolver = TimestampTradingDayResolver({
        pd.Timestamp("2026-06-25 09:01:00"): pd.Timestamp("2026-06-25"),
    })
    index = pd.DatetimeIndex([pd.Timestamp("2026-06-25 09:01:00")])

    old_values = provider.values_for_index("PK2605.CZC", "OpenRatioByVolume", index, trading_day_resolver=resolver)
    new_values = provider.values_for_index("PK2701.CZC", "OpenRatioByVolume", index, trading_day_resolver=resolver)

    assert old_values.iloc[0] == 4
    assert new_values.iloc[0] == 2

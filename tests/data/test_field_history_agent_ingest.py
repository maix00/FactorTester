from __future__ import annotations

import json

import pandas as pd
import pytest

from tools.data.field_history import (
    FieldHistoryProvider,
    HistoricalFieldIntegrityError,
    TimestampTradingDayResolver,
    load_historical_field_frame,
    save_historical_field_records,
)
from tools.data.field_history_agent_ingest import (
    AGENT_EVENT_TABLE,
    append_agent_field_change_events,
    audit_agent_event_previous_values,
    materialize_agent_events_to_history,
)
from tools.data.hub import DataHub, SQLiteStore
from sources.FieldHistory.scripts import backfill_dce_transaction_fee_inactive_units
from sources.FieldHistory.scripts import ingest_dce_listing_fee_baselines
from sources.FieldHistory.scripts import fix_shfe_listing_fee_baselines
from sources.FieldHistory.scripts import audit_2024_field_history_coverage
from sources.FieldHistory.scripts import ingest_dce_2023_margin_limit_notice
from sources.FieldHistory.scripts import ingest_dce_risk_management_rules
from sources.FieldHistory.scripts import ingest_gfex_listing_fee_baselines
from sources.FieldHistory.scripts import ingest_exchange_contract_rule_baselines
from sources.FieldHistory.scripts import ingest_exchange_order_volume_rules
from sources.FieldHistory.scripts import ingest_exchange_settlement_asof
from sources.FieldHistory.scripts import fetch_transaction_fee_settlement_snapshots
from sources.FieldHistory.scripts import ingest_czce_settlement_asof
from sources.FieldHistory.scripts import ingest_dce_business_rule_history
from sources.FieldHistory.scripts import ingest_dce_trading_management_rules
from sources.FieldHistory.scripts import ingest_dce_official_limit_order_baselines
from sources.FieldHistory.scripts import ingest_local_cnfutures_static_specs
from sources.FieldHistory.scripts.ingest_field_history_events import main as ingest_events_main


def test_agent_field_change_ingest_hashes_requester_key_and_materializes(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest.sqlite"
    store_key = "agent_ingest_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-test",
        path_getter=lambda: str(db_path),
    ))

    event_ids = append_agent_field_change_events(
        [
            {
                "data_source": "DCE",
                "field_group": "LimitOrderVolume",
                "source_url": "http://www.dce.com.cn/dce/content/2026/ywggytz/18627837.html",
                "source_accessed_at": "2026-06-29T12:00:00+08:00",
                "agent_name": "codex-test",
                "requester_key": "human-secret-key",
                "instrument": "BZ",
                "instrument_label": "纯苯",
                "instrument_type": "future",
                "field_name": "MinLimitOrderVolume",
                "effective_trading_day": "2026-03-10",
                "effective_timestamp": "2026-03-09 21:00:00",
                "value": 4,
                "contract_codes": ["2604"],
                "source_notice_id": "大商所发〔2026〕74号",
                "raw_note": "纯苯期货BZ2604、BZ2605、BZ2606合约交易指令每次最小开仓下单数量调整为4手",
                "evidence_text": "BZ2604、BZ2605、BZ2606 ... 4手",
                "parser_notes": "Parsed contract tokens and split the source sentence into one event per contract.",
            }
        ],
        store_key=store_key,
    )

    assert len(event_ids) == 1
    with DataHub.get_instance().connect_store(store_key) as conn:
        row = conn.execute(f"SELECT * FROM {AGENT_EVENT_TABLE}").fetchone()
        assert row["requester_key_hash"].startswith("hmac-sha256-v1:")
        assert "human-secret-key" not in json.dumps(dict(row), ensure_ascii=False)

    assert materialize_agent_events_to_history(store_key=store_key) == 1
    history = load_historical_field_frame(store_key=store_key)
    provider = FieldHistoryProvider(history)
    value = provider.resolve_at(
        "BZ2604.DCE",
        "MinLimitOrderVolume",
        pd.Timestamp("2026-03-10 09:01:00"),
        trading_day_resolver=TimestampTradingDayResolver({
            pd.Timestamp("2026-03-10 09:01:00"): pd.Timestamp("2026-03-10"),
        }),
    )

    assert value.value == 4
    assert value.provider == "Agent:DCE"
    assert value.source_key == f"agent/DCE/{event_ids[0]}"


def test_agent_field_change_ingest_accepts_explicit_multi_contract_scope(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest_multi_contract.sqlite"
    store_key = "agent_ingest_multi_contract_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-multi-contract-test",
        path_getter=lambda: str(db_path),
    ))

    append_agent_field_change_events(
        [
            {
                "data_source": "DCE",
                "field_group": "LimitOrderVolume",
                "source_url": "http://www.dce.com.cn/dce/content/2026/ywggytz/18627837.html",
                "source_accessed_at": "2026-06-29T12:00:00+08:00",
                "agent_name": "codex-test",
                "requester_key": "human-secret-key",
                "instrument": "BZ",
                "instrument_label": "纯苯",
                "instrument_type": "future",
                "field_name": "MinLimitOrderVolume",
                "effective_trading_day": "2026-03-10",
                "effective_timestamp": "2026-03-09 21:00:00",
                "value": 4,
                "contract_codes": ["2604", "2605", "2606"],
                "contract_scope_type": "explicit",
                "source_notice_id": "大商所发〔2026〕74号",
                "raw_note": "纯苯期货BZ2604、BZ2605、BZ2606合约交易指令每次最小开仓下单数量调整为4手",
            }
        ],
        store_key=store_key,
    )
    assert materialize_agent_events_to_history(store_key=store_key) == 1

    history = load_historical_field_frame(store_key=store_key)
    provider = FieldHistoryProvider(history)
    resolver = TimestampTradingDayResolver({
        pd.Timestamp("2026-03-10 09:01:00"): pd.Timestamp("2026-03-10"),
    })
    for contract in ["BZ2604.DCE", "BZ2605.DCE", "BZ2606.DCE"]:
        value = provider.resolve_at(
            contract,
            "MinLimitOrderVolume",
            pd.Timestamp("2026-03-10 09:01:00"),
            trading_day_resolver=resolver,
        )
        assert value.value == 4
    try:
        provider.resolve_at(
            "BZ2607.DCE",
            "MinLimitOrderVolume",
            pd.Timestamp("2026-03-10 09:01:00"),
            trading_day_resolver=resolver,
        )
    except Exception as exc:
        assert "no historical value" in str(exc)
    else:
        raise AssertionError("explicit multi-contract scope should not match unlisted contracts")


def test_dce_inactive_fee_unit_backfill_preserves_notice_scope(tmp_path) -> None:
    db_path = tmp_path / "dce_inactive_fee_unit.sqlite"
    store_key = "dce_inactive_fee_unit_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="dce-inactive-fee-unit-test",
        path_getter=lambda: str(db_path),
    ))

    append_agent_field_change_events(
        [
            {
                "event_id": "dce_bz_open_money",
                "data_source": "DCE",
                "field_group": "TransactionFee",
                "source_url": "https://www.dce.com.cn/dce/content/2025/ywggytz/8637864.html",
                "source_accessed_at": "2026-07-09T00:00:00+08:00",
                "agent_name": "Agent:DCE",
                "requester_key": "human-secret-key",
                "instrument": "BZ",
                "instrument_label": "纯苯",
                "instrument_type": "future",
                "field_name": "OpenRatioByMoney",
                "effective_trading_day": "2025-07-08",
                "effective_timestamp": "2025-07-08 09:00:00",
                "value": 0.0001,
                "contract_scope_type": "all",
                "source_notice_id": "大商所发〔2025〕243号",
            },
            {
                "event_id": "dce_jm2601_close_today_money",
                "data_source": "DCE",
                "field_group": "TransactionFee",
                "source_url": "https://www.dce.com.cn/dce/content/2025/ywggytz/18620456.html",
                "source_accessed_at": "2026-07-09T00:00:00+08:00",
                "agent_name": "Agent:DCE",
                "requester_key": "human-secret-key",
                "instrument": "JM",
                "instrument_label": "焦煤",
                "instrument_type": "future",
                "field_name": "CloseTodayRatioByMoney",
                "effective_trading_day": "2025-08-18",
                "effective_timestamp": "2025-08-15 21:00:00",
                "value": 0.0002,
                "contract_codes": ["2601"],
                "contract_scope_type": "explicit",
                "source_notice_id": "大商所发〔2025〕312号",
            },
            {
                "event_id": "broker_row_must_not_generate_exchange_zero",
                "data_source": "OpenCTP",
                "field_group": "TransactionFee",
                "source_url": "https://broker.example/fee",
                "source_accessed_at": "2026-07-09T00:00:00+08:00",
                "agent_name": "Agent:OpenCTP",
                "requester_key": "human-secret-key",
                "instrument": "BZ",
                "instrument_label": "纯苯",
                "instrument_type": "future",
                "field_name": "CloseRatioByMoney",
                "effective_trading_day": "2025-07-08",
                "effective_timestamp": "2025-07-08 09:00:00",
                "value": 0.0002,
                "contract_scope_type": "all",
            },
        ],
        store_key=store_key,
    )

    events = backfill_dce_transaction_fee_inactive_units.build_events(store_key=store_key)

    assert [(event["instrument"], event["field_name"]) for event in events] == [
        ("BZ", "OpenRatioByVolume"),
        ("JM", "CloseTodayRatioByVolume"),
    ]
    assert events[0]["contract_scope_type"] == "all"
    assert events[0]["contract_codes"] == []
    assert events[1]["contract_scope_type"] == "explicit"
    assert events[1]["contract_codes"] == ["2601"]
    assert all(event["value"] == 0 for event in events)


def test_gfex_listing_fee_baselines_use_normal_close_today_not_hedge_fee(tmp_path) -> None:
    db_path = tmp_path / "gfex_listing_fee_baselines.sqlite"
    store_key = "gfex_listing_fee_baselines_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="gfex-listing-fee-baselines-test",
        path_getter=lambda: str(db_path),
    ))

    events = ingest_gfex_listing_fee_baselines.build_events(store_key=store_key)
    by_key = {(event["instrument"], event["field_name"]): event for event in events}

    assert len(events) == 18
    assert by_key[("PS", "OpenRatioByMoney")]["value"] == 0.0001
    assert by_key[("PS", "CloseTodayRatioByMoney")]["value"] == 0.0001
    assert by_key[("PT", "CloseTodayRatioByMoney")]["value"] == 0.0
    assert by_key[("PD", "CloseTodayRatioByMoney")]["value"] == 0.0
    assert by_key[("PT", "OpenRatioByMoney")]["value"] == 0.0001
    assert by_key[("PD", "CloseRatioByVolume")]["value"] == 0.0
    assert all(event["change_type"] == "baseline" for event in events)
    assert all("套期保值" not in event["field_name"] for event in events)


def test_dce_listing_sources_materialize_same_as_corresponding_product_baselines(tmp_path) -> None:
    db_path = tmp_path / "dce_listing_baselines.sqlite"
    store_key = "dce_listing_baselines_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="dce-listing-baselines-test",
        path_getter=lambda: str(db_path),
    ))
    base_values = {
        "L": {
            "LongMarginRatioByMoney": 0.07,
            "ShortMarginRatioByMoney": 0.071,
            "LimitUpDownRatio": 0.06,
        },
        "PP": {
            "LongMarginRatioByMoney": 0.08,
            "ShortMarginRatioByMoney": 0.081,
            "LimitUpDownRatio": 0.07,
        },
        "V": {
            "LongMarginRatioByMoney": 0.09,
            "ShortMarginRatioByMoney": 0.091,
            "LimitUpDownRatio": 0.08,
        },
    }
    save_historical_field_records(
        [
            {
                "provider": "Official:DCE",
                "source_key": f"official/DCE/{instrument}/{field_name}",
                "instrument": instrument,
                "instrument_label": instrument,
                "instrument_type": "future",
                "field_name": field_name,
                "effective_trading_day": "2024-01-02",
                "effective_timestamp": "2024-01-02 09:00:00",
                "value": value,
                "exchange": "DCE",
                "contract_scope_type": "all",
                "change_type": "asof_confirmed",
                "source_notice_id": "DCE-base-product-asof",
                "source_url": "https://www.dce.com.cn/",
            }
            for instrument, fields in base_values.items()
            for field_name, value in fields.items()
        ],
        store_key=store_key,
    )

    events = ingest_dce_listing_fee_baselines.build_events(store_key=store_key)
    by_instrument: dict[str, dict[str, dict[str, object]]] = {}
    for event in events:
        by_instrument.setdefault(str(event["instrument"]), {})[str(event["field_name"])] = event

    for instrument, margin, limit in (("BZ", 0.08, 0.07), ("LG", 0.08, 0.06)):
        fields = by_instrument[instrument]
        assert fields["OpenRatioByMoney"]["value"] == 0.0001
        assert fields["OpenRatioByVolume"]["value"] == 0.0
        assert fields["CloseTodayRatioByMoney"]["value"] == 0.0001
        assert fields["LongMarginRatioByMoney"]["value"] == margin
        assert fields["ShortMarginRatioByMoney"]["value"] == margin
        assert fields["LimitUpDownRatio"]["value"] == limit
        assert fields["OpenRatioByMoney"]["field_group"] == "TransactionFee"
        assert fields["LongMarginRatioByMoney"]["field_group"] == "Margin"
        assert fields["LimitUpDownRatio"]["field_group"] == "TradingRules"

    for instrument in ("L_F", "PP_F", "V_F"):
        fields = by_instrument[instrument]
        assert fields["OpenRatioByVolume"]["value"] == 1.0
        assert fields["CloseTodayRatioByVolume"]["value"] == 1.0
        assert fields["OpenRatioByVolume"]["effective_trading_day"] == "2025-10-29"
        assert fields["OpenRatioByVolume"]["effective_timestamp"] == "2025-10-28 21:00:00"
        base_instrument = instrument.removesuffix("_F")
        assert fields["LongMarginRatioByMoney"]["value"] == base_values[base_instrument]["LongMarginRatioByMoney"]
        assert fields["ShortMarginRatioByMoney"]["value"] == base_values[base_instrument]["ShortMarginRatioByMoney"]
        assert fields["LimitUpDownRatio"]["value"] == base_values[base_instrument]["LimitUpDownRatio"]
        assert fields["LongMarginRatioByMoney"]["field_group"] == "Margin"
        assert fields["LimitUpDownRatio"]["field_group"] == "TradingRules"
        assert base_instrument in fields["LongMarginRatioByMoney"]["evidence_text"]
        assert "exchange defaults" in fields["LongMarginRatioByMoney"]["parser_notes"]


def test_dce_2023_margin_limit_notice_generates_all_mentioned_products(tmp_path) -> None:
    db_path = tmp_path / "dce_2023_margin_limit.sqlite"
    store_key = "dce_2023_margin_limit_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="dce-2023-margin-limit-test",
        path_getter=lambda: str(db_path),
    ))

    events = ingest_dce_2023_margin_limit_notice.build_events(store_key=store_key)
    by_key = {(event["instrument"], event["field_name"]): event for event in events}

    assert len(events) == 30
    assert by_key[("L", "LongMarginRatioByMoney")]["value"] == 0.07
    assert by_key[("PP", "ShortMarginRatioByMoney")]["value"] == 0.07
    assert by_key[("V", "LimitUpDownRatio")]["value"] == 0.06
    assert by_key[("CS", "LimitUpDownRatio")]["value"] == 0.05
    assert by_key[("P", "LongMarginRatioByMoney")]["value"] == 0.08
    assert all(event["source_notice_id"] == "大商所发〔2023〕139号" for event in events)
    assert all(event["change_type"] == "change" for event in events)


def test_dce_risk_management_rules_expand_to_contract_scoped_value_history(tmp_path) -> None:
    db_path = tmp_path / "dce_risk_rules.sqlite"
    store_key = "dce_risk_rules_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="dce-risk-rules-test",
        path_getter=lambda: str(db_path),
    ))

    append_agent_field_change_events(
        [
            {
                "event_id": "dce_l_margin_base",
                "data_source": "DCE",
                "field_group": "Margin",
                "source_url": "https://example.test/dce-l-base",
                "source_accessed_at": "2026-07-09T00:00:00+08:00",
                "agent_name": "Agent:DCE",
                "requester_key": "human-secret-key",
                "instrument": "L",
                "instrument_label": "聚乙烯",
                "instrument_type": "future",
                "field_name": "LongMarginRatioByMoney",
                "effective_trading_day": "2023-04-13",
                "effective_timestamp": "2023-04-12 15:00:00",
                "value": 0.07,
                "contract_scope_type": "all",
                "change_type": "change",
                "source_notice_id": "大商所发〔2023〕139号",
            }
        ],
        store_key=store_key,
    )
    assert materialize_agent_events_to_history(store_key=store_key, field_group="Margin") == 1

    events = ingest_dce_risk_management_rules.build_events(store_key=store_key)
    assert len(events) > 100
    assert {event["change_type"] for event in events} == {"rule"}
    assert all(isinstance(event["value"], float) for event in events)
    assert all(event["contract_scope_type"] == "explicit" for event in events)
    append_agent_field_change_events(events, store_key=store_key)
    materialize_agent_events_to_history(store_key=store_key, data_source="DCE", field_group="Margin")

    with DataHub.get_instance().connect_store(store_key) as conn:
        count = conn.execute(
            f"SELECT COUNT(*) FROM {AGENT_EVENT_TABLE} WHERE change_type = 'rule'"
        ).fetchone()[0]
    assert count == len(events)

    history = load_historical_field_frame(store_key=store_key)
    provider = FieldHistoryProvider(history)
    value = provider.resolve_by_trading_day(
        "L2401.DCE",
        "LongMarginRatioByMoney",
        pd.Timestamp("2024-01-02"),
    )
    assert value.value == 0.20
    assert value.source_notice_id == "DCE-risk-management-measures-delivery-calendar-rules"


def test_local_cnfutures_static_specs_generate_asof_and_listing_baselines(tmp_path) -> None:
    db_path = tmp_path / "local_static_specs.sqlite"
    store_key = "local_static_specs_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="local-static-specs-test",
        path_getter=lambda: str(db_path),
    ))

    events = ingest_local_cnfutures_static_specs.build_events(store_key=store_key)
    by_key = {(event["instrument"], event["field_name"]): event for event in events}

    assert by_key[("A", "VolumeMultiple")]["value"] == 10.0
    assert by_key[("A", "VolumeMultiple")]["change_type"] == "asof_confirmed"
    assert by_key[("A", "PriceTick")]["value"] == 1.0
    assert by_key[("BZ", "VolumeMultiple")]["value"] == 30.0
    assert by_key[("BZ", "VolumeMultiple")]["change_type"] == "baseline"


def test_dce_business_rule_parser_accepts_non_tonne_contract_units() -> None:
    assert ingest_dce_business_rule_history._parse_values(  # noqa: SLF001 - parser unit lock.
        "胶合板期货合约的交易单位为500张/手。"
        "胶合板期货合约的最小变动价位为0.05元/张。"
        "胶合板期货合约的交易指令每次最大下单数量为1000手。"
    ) == {
        "VolumeMultiple": 500.0,
        "PriceTick": 0.05,
        "MaxLimitOrderVolume": 1000.0,
        "MaxMarketOrderVolume": 1000.0,
    }
    assert ingest_dce_business_rule_history._parse_values(  # noqa: SLF001 - parser unit lock.
        "纤维板期货合约的交易单位为10立方米/手。"
    )["VolumeMultiple"] == 10.0


def test_dce_trading_management_rule_materializes_exchange_default_scope(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "dce_trading_management_rules.sqlite"
    store_key = "dce_trading_management_rules_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="dce-trading-management-rules-test",
        path_getter=lambda: str(db_path),
    ))
    version_row = {"secFutrsLawId": "law-1", "secFutrsLawVersion": "20231231", "fileno": "大商所发〔2023〕1号"}
    parsed_row = {
        "law_id": "law-1",
        "version": "20231231",
        "fileno": "大商所发〔2023〕1号",
        "source_url": "https://neris.csrc.gov.cn/falvfagui/rdqsHeader/mainbody?secFutrsLawId=law-1",
        "source_accessed_at": "2026-07-09T00:00:00+08:00",
        "min_order_volume": 1.0,
        "evidence": "期货合约交易指令每次最小下单数量为1手",
    }
    monkeypatch.setattr(ingest_dce_trading_management_rules, "_fetch_law_versions", lambda _session: [version_row])
    monkeypatch.setattr(ingest_dce_trading_management_rules, "_parsed_version", lambda _session, _row: parsed_row)
    monkeypatch.setattr(ingest_dce_trading_management_rules, "_session", lambda: object())

    events = ingest_dce_trading_management_rules.build_events(store_key=store_key)

    assert len(events) == 1
    assert events[0]["instrument"] == "*"
    assert events[0]["exchange"] == "DCE"
    assert events[0]["scope_type"] == "exchange_default"
    assert events[0]["field_name"] == "MinLimitOrderVolume"
    assert events[0]["value"] == 1.0
    append_agent_field_change_events(events, store_key=store_key)
    assert materialize_agent_events_to_history(store_key=store_key, field_group="TradingRules") == 1
    provider = FieldHistoryProvider(load_historical_field_frame(store_key=store_key))
    resolved = provider.resolve_by_trading_day("A.DCE", "MinLimitOrderVolume", "2024-01-02")

    assert resolved.value == 1.0
    assert resolved.provider == "Agent:CSRC-rules-db"


def test_dce_official_limit_order_baselines_use_official_content_urls(tmp_path) -> None:
    db_path = tmp_path / "dce_official_limit_order.sqlite"
    store_key = "dce_official_limit_order_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="dce-official-limit-order-test",
        path_getter=lambda: str(db_path),
    ))

    events = ingest_dce_official_limit_order_baselines.build_events(store_key=store_key)
    by_key = {(event["instrument"], event["field_name"]): event for event in events}

    assert by_key[("BZ", "MaxLimitOrderVolume")]["source_url"] == (
        "http://www.dce.com.cn/dce/content/2025/pzxz/8637789.html"
    )
    assert by_key[("BZ", "MaxMarketOrderVolume")]["source_url"] == (
        "http://www.dce.com.cn/dce/content/2025/pzxz/8637789.html"
    )
    assert "dalianshangpin/fgfz" not in str(by_key[("BZ", "MaxLimitOrderVolume")]["source_url"])
    assert by_key[("BZ", "MinLimitOrderVolume")]["value"] == 1.0
    for event in events:
        if event["data_source"] == "DCE":
            assert str(event["source_url"]).startswith("http://www.dce.com.cn/dce/content/")
            assert "dalianshangpin/fgfz" not in str(event["source_url"])
    assert by_key[("L_F", "MaxLimitOrderVolume")]["effective_timestamp"] == "2025-10-28 21:00:00"
    assert by_key[("L_F", "MaxMarketOrderVolume")]["value"] == 1000.0

    append_agent_field_change_events(events, store_key=store_key)
    assert materialize_agent_events_to_history(store_key=store_key, data_source="DCE", field_group="LimitOrderVolume")
    provider = FieldHistoryProvider(load_historical_field_frame(store_key=store_key))

    assert provider.resolve_by_trading_day("BZ.DCE", "MaxLimitOrderVolume", "2025-07-08").value == 1000.0
    assert provider.resolve_by_trading_day("BZ.DCE", "MaxMarketOrderVolume", "2025-07-08").value == 1000.0
    assert provider.resolve_by_trading_day("DCE|F|L|2605F", "MinLimitOrderVolume", "2025-10-29").value == 1.0


def test_coverage_audit_flags_current_snapshot_mismatch_as_missing_change() -> None:
    product = audit_2024_field_history_coverage.Product(exchange="DCE", instrument="L", label="聚乙烯")
    history = {
        ("L", "LongMarginRatioByMoney"): [
            {
                "provider": "Agent:DCE",
                "source_key": "agent/DCE/l-baseline",
                "instrument": "L",
                "instrument_label": "聚乙烯",
                "instrument_type": "future",
                "field_name": "LongMarginRatioByMoney",
                "effective_trading_day": "2020-01-01",
                "effective_timestamp": "2020-01-01 09:00:00",
                "value": "0.05",
                "value_type": "float",
                "change_type": "baseline",
                "exchange": "DCE",
                "contract_scope_type": "all",
                "source_notice_id": "DCE-L-baseline",
            },
            {
                "provider": "Agent:DCE",
                "source_key": "agent/DCE/l-current-snapshot",
                "instrument": "L",
                "instrument_label": "聚乙烯",
                "instrument_type": "future",
                "field_name": "LongMarginRatioByMoney",
                "effective_trading_day": "2026-07-01",
                "effective_timestamp": "2026-07-01 09:00:00",
                "value": "0.08",
                "value_type": "float",
                "change_type": "asof_confirmed",
                "exchange": "DCE",
                "contract_scope_type": "all",
                "source_notice_id": "DCE-current-settlement-snapshot",
            },
        ]
    }

    rows = audit_2024_field_history_coverage._current_snapshot_mismatch_rows(
        [product],
        history,
        asof_day="2024-01-02",
    )

    assert len(rows) == 1
    assert rows[0]["status"] == "current_snapshot_mismatch"
    assert rows[0]["instrument"] == "L"
    assert rows[0]["field_name"] == "LongMarginRatioByMoney"
    assert "missing intermediate change event" in rows[0]["detail"]


def test_shfe_listing_fee_fix_generates_inactive_unit_baselines(tmp_path) -> None:
    db_path = tmp_path / "shfe_listing_fee_fix.sqlite"
    store_key = "shfe_listing_fee_fix_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="shfe-listing-fee-fix-test",
        path_getter=lambda: str(db_path),
    ))
    append_agent_field_change_events(
        [
            {
                "event_id": "shfe_ad_listing_open_money",
                "data_source": "SHFE",
                "field_group": "TransactionFee",
                "source_url": "https://www.shfe.com.cn/publicnotice/notice/202505/t20250526_827862.html",
                "source_accessed_at": "2026-07-09T00:00:00+08:00",
                "agent_name": "Agent:SHFE",
                "requester_key": "human-secret-key",
                "instrument": "AD",
                "instrument_label": "铸造铝合金",
                "instrument_type": "future",
                "exchange": "SHFE",
                "field_name": "OpenRatioByMoney",
                "effective_trading_day": "2025-06-10",
                "effective_timestamp": "2025-06-10 09:00:00",
                "value": 0.0001,
                "change_type": "change",
                "source_notice_id": "上期发〔2025〕157号",
                "raw_note": "铸造铝合金期货自2025年6月10日起上市交易。交易手续费为成交金额的万分之一。",
            },
            {
                "event_id": "shfe_ad_later_change_money",
                "data_source": "SHFE",
                "field_group": "TransactionFee",
                "source_url": "https://www.shfe.com.cn/publicnotice/notice/202511/t20251104_829426.html",
                "source_accessed_at": "2026-07-09T00:00:00+08:00",
                "agent_name": "Agent:SHFE",
                "requester_key": "human-secret-key",
                "instrument": "AD",
                "instrument_label": "铸造铝合金",
                "instrument_type": "future",
                "exchange": "SHFE",
                "field_name": "OpenRatioByMoney",
                "effective_trading_day": "2025-11-10",
                "effective_timestamp": "2025-11-07 21:00:00",
                "value": 0.00005,
                "change_type": "change",
                "source_notice_id": "上期发〔2025〕317号",
                "raw_note": "自2025年11月10日交易起，铸造铝合金期货交易手续费调整为成交金额的万分之零点五。",
            },
        ],
        store_key=store_key,
    )
    materialize_agent_events_to_history(store_key=store_key, field_group="TransactionFee")

    with DataHub.get_instance().connect_store(store_key) as conn:
        listing_rows = fix_shfe_listing_fee_baselines._listing_money_rows(conn)
        generated = fix_shfe_listing_fee_baselines.build_inactive_unit_events(conn, listing_rows)
        fix_shfe_listing_fee_baselines._mark_listing_rows_as_baseline(conn, listing_rows)

    assert [row["event_id"] for row in listing_rows] == ["shfe_ad_listing_open_money"]
    assert len(generated) == 1
    assert generated[0]["field_name"] == "OpenRatioByVolume"
    assert generated[0]["value"] == 0
    assert generated[0]["change_type"] == "baseline"
    with DataHub.get_instance().connect_store(store_key) as conn:
        rows = conn.execute(
            f"SELECT event_id, change_type FROM {AGENT_EVENT_TABLE} ORDER BY event_id"
        ).fetchall()
    assert {row["event_id"]: row["change_type"] for row in rows} == {
        "shfe_ad_later_change_money": "change",
        "shfe_ad_listing_open_money": "baseline",
    }


def test_agent_ingest_infers_night_session_effective_timestamp(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest_night_session.sqlite"
    store_key = "agent_ingest_night_session_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-night-session-test",
        path_getter=lambda: str(db_path),
    ))

    append_agent_field_change_events(
        [
            {
                "data_source": "CZCE",
                "field_group": "TransactionFee",
                "source_url": "https://example.com/czce-notice",
                "source_accessed_at": "2026-07-09T00:00:00+08:00",
                "agent_name": "codex-test",
                "requester_key": "human-secret-key",
                "instrument": "CY",
                "instrument_label": "棉纱",
                "instrument_type": "future",
                "field_name": "OpenRatioByVolume",
                "effective_trading_day": "2024-09-02",
                "effective_session": "night",
                "value": 4,
                "source_notice_id": "郑商函〔2024〕test",
            }
        ],
        store_key=store_key,
    )

    assert materialize_agent_events_to_history(store_key=store_key) == 1
    history = load_historical_field_frame(store_key=store_key)
    row = history.iloc[0]
    assert pd.Timestamp(row["effective_trading_day"]) == pd.Timestamp("2024-09-02")
    assert pd.Timestamp(row["effective_timestamp"]) == pd.Timestamp("2024-09-01 21:00:00")


def test_agent_ingest_rejects_unknown_effective_session(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest_bad_session.sqlite"
    store_key = "agent_ingest_bad_session_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-bad-session-test",
        path_getter=lambda: str(db_path),
    ))

    with pytest.raises(ValueError, match="unsupported effective_session"):
        append_agent_field_change_events(
            [
                {
                    "data_source": "CZCE",
                    "field_group": "TransactionFee",
                    "source_url": "https://example.com/czce-notice",
                    "source_accessed_at": "2026-07-09T00:00:00+08:00",
                    "agent_name": "codex-test",
                    "requester_key": "human-secret-key",
                    "instrument": "CY",
                    "instrument_label": "棉纱",
                    "instrument_type": "future",
                    "field_name": "OpenRatioByVolume",
                    "effective_trading_day": "2024-09-02",
                    "effective_session": "auction",
                    "value": 4,
                }
            ],
            store_key=store_key,
        )


def test_agent_ingest_rejects_close_today_half_discount_as_half_fee(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest_close_today_half.sqlite"
    store_key = "agent_ingest_close_today_half_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-close-today-half-test",
        path_getter=lambda: str(db_path),
    ))

    with pytest.raises(ValueError, match="close-today fee must be 0"):
        append_agent_field_change_events(
            [
                {
                    "data_source": "CZCE",
                    "field_group": "TransactionFee",
                    "source_url": "https://www.czce.com.cn/test.pdf",
                    "source_accessed_at": "2026-07-09T00:00:00+08:00",
                    "agent_name": "codex-test",
                    "requester_key_hash": "test",
                    "instrument": "RM",
                    "instrument_label": "菜籽粕",
                    "instrument_type": "future",
                    "field_name": "CloseTodayRatioByVolume",
                    "effective_trading_day": "2012-12-28",
                    "effective_session": "day",
                    "value": 0.75,
                    "contract_scope_type": "all",
                    "change_type": "baseline",
                    "source_notice_id": "郑商发[2012]221号",
                    "raw_note": "菜籽粕期货交易手续费1.5元/手，自上市之日起当日开平仓手续费减半收取。",
                }
            ],
            store_key=store_key,
        )


def test_agent_field_change_ingest_materializes_exchange_default_scope(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest_exchange_default.sqlite"
    store_key = "agent_ingest_exchange_default_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-exchange-default-test",
        path_getter=lambda: str(db_path),
    ))

    append_agent_field_change_events(
        [
            {
                "data_source": "CZCE",
                "field_group": "LimitOrderVolume",
                "source_url": "https://www.czce.com.cn/cn/flfg/zcjywgz/ywbf/webinfo/2023/04/1684183719758137.htm",
                "source_accessed_at": "2026-07-08T12:00:00+08:00",
                "agent_name": "codex-test",
                "requester_key": "human-secret-key",
                "instrument": "*",
                "instrument_label": "郑商所期货默认",
                "instrument_type": "future",
                "scope_type": "exchange_default",
                "exchange": "CZC",
                "field_name": "MaxLimitOrderVolume",
                "effective_trading_day": "2022-12-01",
                "value": 1000,
                "contract_scope_type": "all",
                "change_type": "baseline",
                "source_notice_id": "郑商所公告〔2022〕74号",
                "raw_note": "期货限价指令每次最大下单量1000手。",
            }
        ],
        store_key=store_key,
    )

    assert materialize_agent_events_to_history(store_key=store_key) == 1
    provider = FieldHistoryProvider(load_historical_field_frame(store_key=store_key))
    resolved = provider.resolve_by_trading_day("CF.CZC", "MaxLimitOrderVolume", "2024-02-06")

    assert resolved.value == 1000
    assert resolved.provider == "Agent:CZCE"


def test_agent_field_change_previous_value_mismatch_is_an_audit_issue_not_ingest_gate(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest_previous_value.sqlite"
    store_key = "agent_ingest_previous_value_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-previous-value-test",
        path_getter=lambda: str(db_path),
    ))
    save_historical_field_records(
        [
            {
                "provider": "Official:CZCE",
                "source_key": "official/CZCE/cf-listing-baseline",
                "instrument": "CF",
                "instrument_label": "棉花",
                "instrument_type": "future",
                "field_name": "CloseRatioByVolume",
                "effective_trading_day": "2004-06-01",
                "effective_timestamp": "2004-06-01 09:00:00",
                "value": 8.0,
                "contract_scope_type": "all",
                "change_type": "baseline",
                "source_notice_id": "CF-listing-baseline",
                "source_url": "https://www.czce.com.cn/",
            }
        ],
        store_key=store_key,
    )
    append_agent_field_change_events(
        [
            {
                "event_id": "transaction_fee_notice_cf_wrong_previous",
                "data_source": "CZCE",
                "field_group": "TransactionFee",
                "source_url": "https://www.czce.com.cn/cn/test.pdf",
                "source_accessed_at": "2026-07-08T00:00:00+08:00",
                "agent_name": "codex-test",
                "requester_key": "human-secret-key",
                "instrument": "CF",
                "instrument_label": "棉花",
                "instrument_type": "future",
                "field_name": "CloseRatioByVolume",
                "effective_trading_day": "2012-06-01",
                "effective_timestamp": "2012-06-01 09:00:00",
                "value": 4.8,
                "previous_value": 6.0,
                "contract_scope_type": "all",
                "change_type": "change",
                "source_notice_id": "郑商所手续费调整测试",
            }
        ],
        store_key=store_key,
    )

    assert materialize_agent_events_to_history(store_key=store_key) == 1
    issues = audit_agent_event_previous_values(store_key=store_key)

    assert len(issues) == 1
    assert issues[0]["status"] == "previous_value_mismatch"
    assert issues[0]["instrument"] == "CF"
    assert issues[0]["field_name"] == "CloseRatioByVolume"
    assert issues[0]["previous_value"] == 6.0
    assert issues[0]["prior_value"] == "8.0"
    provider = FieldHistoryProvider(load_historical_field_frame(store_key=store_key))
    with pytest.raises(HistoricalFieldIntegrityError, match="previous_value mismatch"):
        provider.resolve_by_trading_day("CF.CZC", "CloseRatioByVolume", "2012-06-01")
    with pytest.raises(HistoricalFieldIntegrityError, match="previous_value mismatch"):
        provider.frame_for_index(
            ["CF.CZC"],
            "CloseRatioByVolume",
            [pd.Timestamp("2012-06-01 09:01:00")],
            trading_day_resolver=TimestampTradingDayResolver({
                pd.Timestamp("2012-06-01 09:01:00"): pd.Timestamp("2012-06-01"),
            }),
        )


def test_agent_field_change_ingest_accepts_matching_previous_value(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest_previous_value_ok.sqlite"
    store_key = "agent_ingest_previous_value_ok_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-previous-value-ok-test",
        path_getter=lambda: str(db_path),
    ))
    save_historical_field_records(
        [
            {
                "provider": "Official:CZCE",
                "source_key": "official/CZCE/cf-listing-baseline",
                "instrument": "CF",
                "instrument_label": "棉花",
                "instrument_type": "future",
                "field_name": "CloseRatioByVolume",
                "effective_trading_day": "2004-06-01",
                "effective_timestamp": "2004-06-01 09:00:00",
                "value": 8.0,
                "contract_scope_type": "all",
                "change_type": "baseline",
                "source_notice_id": "CF-listing-baseline",
                "source_url": "https://www.czce.com.cn/",
            }
        ],
        store_key=store_key,
    )
    append_agent_field_change_events(
        [
            {
                "event_id": "transaction_fee_notice_cf_matching_previous",
                "data_source": "CZCE",
                "field_group": "TransactionFee",
                "source_url": "https://www.czce.com.cn/cn/test.pdf",
                "source_accessed_at": "2026-07-08T00:00:00+08:00",
                "agent_name": "codex-test",
                "requester_key": "human-secret-key",
                "instrument": "CF",
                "instrument_label": "棉花",
                "instrument_type": "future",
                "field_name": "CloseRatioByVolume",
                "effective_trading_day": "2012-06-01",
                "effective_timestamp": "2012-06-01 09:00:00",
                "value": 4.8,
                "previous_value": 8.0,
                "contract_scope_type": "all",
                "change_type": "change",
                "source_notice_id": "郑商所手续费调整测试",
            }
        ],
        store_key=store_key,
    )

    assert materialize_agent_events_to_history(store_key=store_key) == 1
    provider = FieldHistoryProvider(load_historical_field_frame(store_key=store_key))
    resolved = provider.resolve_by_trading_day("CF.CZC", "CloseRatioByVolume", "2012-06-01")

    assert resolved.value == 4.8


def test_previous_value_audit_ignores_same_effective_time_product_change_for_contract_exception(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest_same_effective_exception.sqlite"
    store_key = "agent_ingest_same_effective_exception_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-same-effective-exception-test",
        path_getter=lambda: str(db_path),
    ))
    save_historical_field_records(
        [
            {
                "provider": "Official:CZCE",
                "source_key": "official/CZCE/cy-listing-baseline",
                "instrument": "CY",
                "instrument_label": "棉纱",
                "instrument_type": "future",
                "field_name": "CloseRatioByVolume",
                "effective_trading_day": "2017-08-18",
                "effective_timestamp": "2017-08-18 09:00:00",
                "value": 4.0,
                "contract_scope_type": "all",
                "change_type": "baseline",
                "source_notice_id": "郑商发〔2017〕212号",
                "source_url": "https://www.czce.com.cn/",
            }
        ],
        store_key=store_key,
    )
    append_agent_field_change_events(
        [
            {
                "event_id": "transaction_fee_notice_cy_20240902_product",
                "data_source": "CZCE",
                "field_group": "TransactionFee",
                "source_url": "https://www.czce.com.cn/cn/test.htm",
                "source_accessed_at": "2026-07-08T00:00:00+08:00",
                "agent_name": "codex-test",
                "requester_key": "human-secret-key",
                "instrument": "CY",
                "instrument_label": "棉纱",
                "instrument_type": "future",
                "field_name": "CloseRatioByVolume",
                "effective_trading_day": "2024-09-02",
                "effective_timestamp": "2024-08-30 21:00:00",
                "value": 1.0,
                "previous_value": 4.0,
                "contract_scope_type": "all",
                "change_type": "change",
                "source_notice_id": "郑商函〔2024〕587号",
            },
            {
                "event_id": "transaction_fee_notice_cy_20240902_exception",
                "data_source": "CZCE",
                "field_group": "TransactionFee",
                "source_url": "https://www.czce.com.cn/cn/test.htm",
                "source_accessed_at": "2026-07-08T00:00:00+08:00",
                "agent_name": "codex-test",
                "requester_key": "human-secret-key",
                "instrument": "CY",
                "instrument_label": "棉纱",
                "instrument_type": "future",
                "field_name": "CloseRatioByVolume",
                "effective_trading_day": "2024-09-02",
                "effective_timestamp": "2024-08-30 21:00:00",
                "value": 4.0,
                "previous_value": 4.0,
                "contract_codes": ["2409"],
                "contract_scope_type": "explicit",
                "change_type": "exception_unchanged",
                "source_notice_id": "郑商函〔2024〕587号",
            },
        ],
        store_key=store_key,
    )

    assert materialize_agent_events_to_history(store_key=store_key) == 2
    issues = audit_agent_event_previous_values(store_key=store_key)

    assert issues == []


def test_ingest_script_can_replace_corrected_source_events(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest_replace.sqlite"
    store_key = "agent_ingest_replace_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-replace-test",
        path_getter=lambda: str(db_path),
    ))
    first_path = tmp_path / "first.jsonl"
    corrected_path = tmp_path / "corrected.jsonl"
    base_event = {
        "event_id": "transaction_fee_notice_test_replace",
        "data_source": "CZCE",
        "field_group": "TransactionFee",
        "source_url": "https://www.czce.com.cn/test.pdf",
        "source_accessed_at": "2026-07-08T00:00:00+08:00",
        "agent_name": "codex-test",
        "instrument": "CY",
        "instrument_label": "棉纱",
        "instrument_type": "future",
        "field_name": "CloseTodayRatioByVolume",
        "effective_trading_day": "2017-08-18",
        "effective_timestamp": "2017-08-18 09:00:00",
        "contract_codes": [],
        "contract_scope_type": "all",
        "change_type": "baseline",
        "source_notice_id": "郑商发〔2017〕212号",
        "value": 2.0,
    }
    first_path.write_text(json.dumps(base_event, ensure_ascii=False) + "\n", encoding="utf-8")
    corrected = dict(base_event, value=0.0, parser_notes="corrected close-today fee")
    corrected_path.write_text(json.dumps(corrected, ensure_ascii=False) + "\n", encoding="utf-8")

    assert ingest_events_main([
        str(first_path),
        "--store-key",
        store_key,
        "--requester-key-hash",
        "test",
    ]) == 0
    assert ingest_events_main([
        str(corrected_path),
        "--store-key",
        store_key,
        "--requester-key-hash",
        "test",
        "--replace-existing",
    ]) == 0

    with DataHub.get_instance().connect_store(store_key) as conn:
        event_rows = conn.execute(
            f"SELECT value_json, parser_notes FROM {AGENT_EVENT_TABLE} WHERE event_id = ?",
            ("transaction_fee_notice_test_replace",),
        ).fetchall()
    assert len(event_rows) == 1
    assert json.loads(event_rows[0]["value_json"]) == 0.0
    assert event_rows[0]["parser_notes"] == "corrected close-today fee"

    history = load_historical_field_frame(store_key=store_key)
    values = history.loc[
        history["source_key"].eq("agent/CZCE/transaction_fee_notice_test_replace"),
        "value",
    ].tolist()
    assert values == ["0.0"]


def test_ingest_script_rejects_settlement_parameter_baselines(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest_reject_snapshot_baseline.sqlite"
    store_key = "agent_ingest_reject_snapshot_baseline_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-reject-snapshot-baseline-test",
        path_getter=lambda: str(db_path),
    ))
    event_path = tmp_path / "snapshot_baseline.jsonl"
    event = {
        "event_id": "transaction_fee_notice_test_snapshot_baseline",
        "data_source": "CZCE",
        "field_group": "TransactionFee",
        "source_url": "http://www.czce.com.cn/cn/DFSStaticFiles/Future/2018/20180122/FutureDataClearParams.txt",
        "source_accessed_at": "2026-07-08T00:00:00+08:00",
        "agent_name": "codex-test",
        "instrument": "CF",
        "instrument_label": "棉花",
        "instrument_type": "future",
        "field_name": "OpenRatioByVolume",
        "effective_trading_day": "2018-01-22",
        "effective_timestamp": "2018-01-22 09:00:00",
        "contract_codes": [],
        "contract_scope_type": "all",
        "change_type": "baseline",
        "source_notice_id": "CZCE-settlement-parameters-20180122-asof-baseline",
        "value": 4.3,
    }
    event_path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")

    try:
        ingest_events_main([
            str(event_path),
            "--store-key",
            store_key,
            "--requester-key-hash",
            "test",
        ])
    except ValueError as exc:
        assert "settlement parameter snapshots are audit evidence" in str(exc)
    else:
        raise AssertionError("settlement-parameter baseline events must be rejected")


def test_ingest_script_accepts_settlement_parameter_asof_confirmed(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest_asof_confirmed.sqlite"
    store_key = "agent_ingest_asof_confirmed_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-asof-confirmed-test",
        path_getter=lambda: str(db_path),
    ))
    event_path = tmp_path / "snapshot_asof_confirmed.jsonl"
    event = {
        "event_id": "transaction_fee_notice_test_snapshot_asof_confirmed",
        "data_source": "CZCE",
        "field_group": "TransactionFee",
        "source_url": "http://www.czce.com.cn/cn/DFSStaticFiles/Future/2024/20240102/FutureDataClearParams.txt",
        "source_accessed_at": "2026-07-09T00:00:00+08:00",
        "agent_name": "codex-test",
        "instrument": "CF",
        "instrument_label": "棉花",
        "instrument_type": "future",
        "field_name": "OpenRatioByVolume",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "2024-01-02 09:00:00",
        "contract_codes": [],
        "contract_scope_type": "all",
        "change_type": "asof_confirmed",
        "source_notice_id": "CZCE-settlement-parameters-20240102-asof-confirmed",
        "value": 4.3,
    }
    event_path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")

    assert ingest_events_main([
        str(event_path),
        "--store-key",
        store_key,
        "--requester-key-hash",
        "test",
    ]) == 0

    history = load_historical_field_frame(store_key=store_key)
    row = history.loc[
        history["source_key"].eq("agent/CZCE/transaction_fee_notice_test_snapshot_asof_confirmed")
    ].iloc[0]
    assert row["change_type"] == "asof_confirmed"
    assert row["value"] == "4.3"


def test_czce_settlement_asof_records_product_anchor_and_contract_overrides(monkeypatch) -> None:
    snapshot = "\n".join([
        "合约代码|交易保证金率(%)|涨跌停板(%)|交易手续费|手续费收取方式|日内平今仓交易手续费",
        "CF401|20|10|4.3|绝对值|4.3",
        "CF403|9|8|4.3|绝对值|0",
        "CF405|9|8|4.3|绝对值|0",
    ])
    monkeypatch.setattr(ingest_czce_settlement_asof, "_fetch_snapshot", lambda date: snapshot)

    events = ingest_czce_settlement_asof.build_events(date="20240102")
    close_today_volume = [
        event for event in events
        if event["instrument"] == "CF" and event["field_name"] == "CloseTodayRatioByVolume"
    ]

    product_rows = [event for event in close_today_volume if event["contract_scope_type"] == "all"]
    explicit_rows = [event for event in close_today_volume if event["contract_scope_type"] == "explicit"]
    assert len(product_rows) == 1
    assert product_rows[0]["value"] == 0.0
    assert product_rows[0]["contract_codes"] == []
    assert len(explicit_rows) == 1
    assert explicit_rows[0]["value"] == 4.3
    assert explicit_rows[0]["contract_codes"] == ["CF401"]


def test_shfe_ttrade_and_isunitoday_do_not_create_close_today_fees(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "o_cursor": [
                    {
                        "PRODUCTID": "rb_f",
                        "PRODUCTNAME": "螺纹钢",
                        "INSTRUMENTID": "rb2401",
                        "TRADEFEERATIO": 0.1,
                        "TRADEFEEUNIT": 0,
                        "TTRADEFEERATIO": 0.2,
                        "TTRADEFEEUNIT": 0,
                        "ISUNITODAY": 1,
                        "SPECLONGMARGINRATIO": 0.08,
                        "SPECSHORTMARGINRATIO": 0.08,
                    }
                ]
            }

    monkeypatch.setattr(ingest_exchange_settlement_asof.requests, "get", lambda *args, **kwargs: Response())

    rows = ingest_exchange_settlement_asof._fetch_shfe_like_rows(market="SHFE", date="20240102")

    assert len(rows) == 1
    values = rows[0]["values"]
    assert values["OpenRatioByMoney"] == 0.0001
    assert values["CloseRatioByMoney"] == 0.0001
    assert "CloseTodayRatioByMoney" not in values
    assert "CloseTodayRatioByVolume" not in values


def test_manual_dce_settlement_csv_is_parsed_as_asof_snapshot(tmp_path) -> None:
    csv_path = tmp_path / "结算参数表.csv"
    csv_path.write_text(
        "\ufeff大连商品交易所_结算参数表_20240102\n"
        "品种名称,合约,结算价,手续费投机非日内开仓,手续费投机非日内平仓,"
        "手续费投机日内开仓,手续费投机日内平仓,手续费套保非日内开仓,"
        "手续费套保非日内平仓,手续费套保日内开仓,手续费套保日内平仓,"
        "手续费收取方式,保证金率投机买,保证金率投机卖,保证金率套保买,保证金率套保卖\n"
        '豆一,a2401,"4,768",2,3,4,5,6,7,8,9,绝对值,20%,20%,20%,20%\n'
        '铁矿石,i2401,"1,000",0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,比例值,12%,12%,12%,12%\n',
        encoding="utf-8",
    )

    rows = fetch_transaction_fee_settlement_snapshots._dce_rows(
        "20240102",
        path=csv_path,
        source_accessed_at="2026-07-09T00:00:00+08:00",
    )
    by_key = {(row["instrument"], tuple(row["contract_codes"]), row["field_name"]): row for row in rows}

    assert by_key[("A", ("2401",), "OpenRatioByVolume")]["value"] == 2.0
    assert by_key[("A", ("2401",), "CloseRatioByVolume")]["value"] == 3.0
    assert by_key[("A", ("2401",), "CloseTodayRatioByVolume")]["value"] == 5.0
    assert by_key[("I", ("2401",), "OpenRatioByMoney")]["value"] == pytest.approx(0.1 / 10000.0)
    assert by_key[("I", ("2401",), "CloseRatioByMoney")]["value"] == pytest.approx(0.2 / 10000.0)
    assert by_key[("I", ("2401",), "CloseTodayRatioByMoney")]["value"] == pytest.approx(0.4 / 10000.0)
    assert {row["source_notice_id"] for row in rows} == {"DCE-settlement-parameters-20240102"}


def test_manual_dce_settlement_csv_builds_asof_ingest_anchors(tmp_path) -> None:
    csv_path = tmp_path / "结算参数表.csv"
    csv_path.write_text(
        "\ufeff大连商品交易所_结算参数表_20240102\n"
        "品种名称,合约,结算价,手续费投机非日内开仓,手续费投机非日内平仓,"
        "手续费投机日内开仓,手续费投机日内平仓,手续费套保非日内开仓,"
        "手续费套保非日内平仓,手续费套保日内开仓,手续费套保日内平仓,"
        "手续费收取方式,保证金率投机买,保证金率投机卖,保证金率套保买,保证金率套保卖\n"
        '豆一,a2401,"4,768",2,3,4,5,6,7,8,9,绝对值,20%,21%,20%,20%\n'
        '豆一,a2403,"4,900",2,3,4,1,6,7,8,9,绝对值,8%,9%,7%,7%\n',
        encoding="utf-8",
    )

    events = ingest_exchange_settlement_asof.build_events(
        market="DCE",
        date="20240102",
        dce_csv_by_date={"20240102": csv_path},
    )
    by_key = {
        (
            event["instrument"],
            event["field_name"],
            event["contract_scope_type"],
            tuple(event["contract_codes"]),
        ): event
        for event in events
    }

    product_close_today = by_key[("A", "CloseTodayRatioByVolume", "all", ())]
    explicit_close_today = by_key[("A", "CloseTodayRatioByVolume", "explicit", ("A2401",))]
    product_long_margin = by_key[("A", "LongMarginRatioByMoney", "all", ())]

    assert product_close_today["value"] == 1.0
    assert explicit_close_today["value"] == 5.0
    assert product_long_margin["value"] == 0.08
    assert product_close_today["change_type"] == "asof_confirmed"
    assert product_close_today["effective_timestamp"] == "2024-01-02 09:00:00"
    assert product_close_today["source_notice_id"] == "DCE-settlement-parameters-20240102-asof-confirmed"


def test_cffex_official_baselines_use_cffex_morning_open_time() -> None:
    fee_source = next(
        source
        for source in ingest_exchange_contract_rule_baselines.SOURCES
        if source["source_notice_id"] == "CFFEX-fee-schedule-20240701"
    )
    order_source = next(
        source
        for source in ingest_exchange_order_volume_rules.EXCHANGE_DEFAULTS
        if source["source_notice_id"] == "CFFEX-trading-rules-order-volume-asof-20240102"
    )

    assert fee_source["effective_timestamp"].endswith("09:30:00")
    assert order_source["effective_timestamp"].endswith("09:30:00")


def test_cffex_fee_table_parser_uses_official_stock_index_and_treasury_fees(monkeypatch) -> None:
    class Response:
        content = (
            "中国金融期货交易所结算参数\n"
            "期货合约,合约多头保证金标准,合约空头保证金标准,交易手续费标准,交割手续费标准,平今仓收取率\n"
            "IF2407,12%,12%,万分之0.23,,1000%\n"
            "T2409,2%,2%,3元/手,,0%\n"
        ).encode("gbk")

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(ingest_exchange_settlement_asof.requests, "get", lambda *args, **kwargs: Response())

    rows = ingest_exchange_settlement_asof._fetch_cffex_fee_rows(date="20240701")
    by_product = {row["instrument"]: row["values"] for row in rows}

    assert by_product["IF"]["OpenRatioByMoney"] == 0.23 / 10000.0
    assert by_product["IF"]["CloseTodayRatioByMoney"] == pytest.approx(2.3 / 10000.0)
    assert by_product["IF"]["OpenRatioByVolume"] == 0.0
    assert by_product["T"]["OpenRatioByVolume"] == 3.0
    assert by_product["T"]["CloseTodayRatioByVolume"] == 0.0
    assert by_product["T"]["OpenRatioByMoney"] == 0.0

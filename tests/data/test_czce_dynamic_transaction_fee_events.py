from __future__ import annotations

from sources.FieldHistory.scripts.build_czce_dynamic_transaction_fee_events import (
    RULE_2020_481,
    build_events,
)


def test_czce_2020_481_dynamic_rule_materializes_non_159_contracts() -> None:
    snapshots = [
        {
            "data_source": "CZCE",
            "instrument": "CF",
            "contract_codes": ["2302"],
            "field_name": "CloseTodayRatioByVolume",
            "effective_trading_day": "2022-09-01",
        },
        {
            "data_source": "CZCE",
            "instrument": "CF",
            "contract_codes": ["2305"],
            "field_name": "CloseTodayRatioByVolume",
            "effective_trading_day": "2022-12-01",
        },
        {
            "data_source": "CZCE",
            "instrument": "CY",
            "contract_codes": ["2302"],
            "field_name": "CloseTodayRatioByVolume",
            "effective_trading_day": "2022-09-01",
        },
    ]

    events = build_events(snapshots, rules=[RULE_2020_481])

    assert {tuple(event["contract_codes"]) for event in events} == {("2302",)}
    by_field = {event["field_name"]: event for event in events}
    assert by_field["OpenRatioByVolume"]["value"] == 2.0
    assert by_field["CloseRatioByVolume"]["value"] == 2.0
    assert by_field["CloseTodayRatioByVolume"]["value"] == 0.0
    assert by_field["CloseTodayRatioByMoney"]["value"] == 0.0
    assert by_field["CloseTodayRatioByVolume"]["effective_trading_day"] == "2022-09-01"
    assert by_field["CloseTodayRatioByVolume"]["effective_timestamp"] == ""


def test_czce_2020_481_dynamic_rule_falls_back_to_first_weekday_before_snapshot_calendar() -> None:
    snapshots = [
        {
            "data_source": "CZCE",
            "instrument": "TA",
            "contract_codes": ["2302"],
            "field_name": "CloseTodayRatioByVolume",
            "effective_trading_day": "2022-11-07",
        },
    ]

    events = build_events(snapshots, rules=[RULE_2020_481])

    assert events
    assert {event["effective_trading_day"] for event in events} == {"2022-09-01"}

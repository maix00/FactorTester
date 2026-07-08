from __future__ import annotations

from sources.FieldHistory.scripts.build_czce_dynamic_transaction_fee_events import (
    RULE_2020_481,
    build_events,
)


def test_czce_2020_481_dynamic_rule_materializes_only_1063_retained_contracts() -> None:
    snapshots = [
        {
            "data_source": "CZCE",
            "instrument": "CF",
            "contract_codes": ["2203"],
            "field_name": "CloseTodayRatioByVolume",
            "effective_trading_day": "2021-10-08",
        },
        {
            "data_source": "CZCE",
            "instrument": "CF",
            "contract_codes": ["2302"],
            "field_name": "CloseTodayRatioByVolume",
            "effective_trading_day": "2022-09-01",
        },
        {
            "data_source": "CZCE",
            "instrument": "TA",
            "contract_codes": ["2204"],
            "field_name": "CloseTodayRatioByVolume",
            "effective_trading_day": "2021-11-01",
        },
    ]

    events = build_events(snapshots, rules=[RULE_2020_481])

    generated = {(event["instrument"], tuple(event["contract_codes"])) for event in events}
    assert ("CF", ("2203",)) in generated
    assert ("TA", ("2204",)) in generated
    assert ("CF", ("2302",)) not in generated
    cf_by_field = {
        event["field_name"]: event for event in events
        if event["instrument"] == "CF" and event["contract_codes"] == ["2203"]
    }
    assert cf_by_field["OpenRatioByVolume"]["value"] == 2.0
    assert cf_by_field["CloseRatioByVolume"]["value"] == 2.0
    assert cf_by_field["CloseTodayRatioByVolume"]["value"] == 0.0
    assert cf_by_field["CloseTodayRatioByMoney"]["value"] == 0.0
    assert cf_by_field["CloseTodayRatioByVolume"]["effective_trading_day"] == "2021-10-08"
    assert cf_by_field["CloseTodayRatioByVolume"]["effective_timestamp"] == ""


def test_czce_2020_481_dynamic_rule_falls_back_to_first_weekday_before_snapshot_calendar() -> None:
    snapshots = [
        {
            "data_source": "CZCE",
            "instrument": "TA",
            "contract_codes": ["2204"],
            "field_name": "CloseTodayRatioByVolume",
            "effective_trading_day": "2022-11-07",
        },
    ]

    events = build_events(snapshots, rules=[RULE_2020_481])

    assert events
    ta_events = [event for event in events if event["instrument"] == "TA" and event["contract_codes"] == ["2204"]]
    assert ta_events
    assert {event["effective_trading_day"] for event in ta_events} == {"2021-11-01"}

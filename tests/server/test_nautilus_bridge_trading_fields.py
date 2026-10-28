"""Historical exchange rules remain distinct from current source snapshots."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from server.services.nautilus_bridge.trading_fields import (
    MARKET_RULE_FIELDS,
    EffectiveRule,
    TradingFieldContractError,
    TradingFieldEvent,
    TradingFieldSource,
    bind_historical_trading_fields,
    bind_trading_field_source,
    bind_trading_fields_from_catalog,
    freeze_bound_trading_field_timeline,
    freeze_trading_field_timeline,
    resolve_trading_fields_at,
)
from tools.data.field_history import FieldHistoryProvider

SOURCE = TradingFieldSource(
    "Local", "LocalCNFuturesContractMIN1", "Asia/Shanghai",
    "local_cnfutures_contract_minute_parquet_v1",
    latest_provider="OpenCTP:latest",
    latest_source_prefix="openctp/latest_snapshot",
)


def _provider(*, latest: bool = False, missing: str = "") -> FieldHistoryProvider:
    rows = []
    for name in MARKET_RULE_FIELDS:
        if name == missing:
            continue
        value = 10 if name == "VolumeMultiple" else 0.2 if name == "PriceTick" else 1
        rows.append({
            "provider": "OpenCTP:latest" if latest else "SHFE:exchange-notice",
            "source_key": "openctp/latest_snapshot/AU" if latest else f"exchange/au/{name}",
            "instrument": "AU", "instrument_type": "future", "field_name": name,
            "effective_trading_day": "2025-01-01", "value": value,
        })
    if not latest and missing != "CloseTodayRatioByVolume":
        rows.append({
            "provider": "SHFE:exchange-notice", "source_key": "exchange/au/close-today-change",
            "instrument": "AU", "instrument_type": "future",
            "field_name": "CloseTodayRatioByVolume",
            "effective_trading_day": "2025-01-03",
            "effective_timestamp": "2025-01-02 21:00:00", "value": 4,
        })
    return FieldHistoryProvider.from_records(rows)


def _rules() -> tuple[EffectiveRule, ...]:
    return (
        EffectiveRule("trading_sessions", pd.Timestamp("2025-01-01"), "exchange/calendar/au",
                      "exchange_calendar", {"intervals": [("09:00", "11:30"), ("13:30", "15:00")]}),
        EffectiveRule("daily_settlement", pd.Timestamp("2025-01-01"), "exchange/settlement/au",
                      "exchange_notice", {"eligible": True, "price_field": "settlement_price",
                                           "close_time": "15:00"}),
    )


def _event(hour: int, minute: int, trading_day: date) -> TradingFieldEvent:
    return TradingFieldEvent(pd.Timestamp(f"2025-01-02 {hour:02d}:{minute:02d}:00"), trading_day)


def test_freeze_exact_trading_day_and_timestamp_change() -> None:
    frozen = freeze_trading_field_timeline(
        source=SOURCE, instrument="AU.SHFE",
        events=[_event(20, 59, date(2025, 1, 2)),
                _event(21, 0, date(2025, 1, 3))],
        provider=_provider(), rules=_rules(),
    )
    assert frozen[0].value("CloseTodayRatioByVolume") == Decimal(1)
    assert frozen[1].value("CloseTodayRatioByVolume") == Decimal(4)
    assert frozen[1].trading_day == "2025-01-03"
    assert frozen[1].source.member_key == SOURCE.member_key
    assert next(item for item in frozen[1].fields
                if item.name == "CloseTodayRatioByVolume").effective_timestamp == "2025-01-02T21:00:00"
    assert frozen[1].daily_settlement.source_key == "exchange/settlement/au"
    assert frozen[1].daily_settlement_eligible is True
    assert frozen[1].should_apply_daily_settlement("eligible_products") is True
    assert frozen[1].should_apply_daily_settlement("disabled") is False


def test_noneligible_exchange_rule_does_not_schedule_daily_settlement() -> None:
    rules = (
        _rules()[0],
        EffectiveRule("daily_settlement", pd.Timestamp("2025-01-01"),
                      "exchange/settlement/au", "exchange_notice", {"eligible": False}),
    )
    frozen = resolve_trading_fields_at(
        source=SOURCE, instrument="AU.SHFE", event=_event(21, 0, date(2025, 1, 3)),
        provider=_provider(), rules=rules,
    )
    assert frozen.daily_settlement_eligible is False
    assert frozen.should_apply_daily_settlement("eligible_products") is False


def test_eligible_settlement_rule_requires_official_price_and_time() -> None:
    invalid_rules = (
        _rules()[0],
        EffectiveRule("daily_settlement", pd.Timestamp("2025-01-01"),
                      "exchange/settlement/au", "exchange_notice", {"eligible": True}),
    )
    with pytest.raises(TradingFieldContractError, match="eligible rules require"):
        resolve_trading_fields_at(
            source=SOURCE, instrument="AU.SHFE", event=_event(21, 0, date(2025, 1, 3)),
            provider=_provider(), rules=invalid_rules,
        )


def test_utc_event_clock_uses_source_exchange_timezone() -> None:
    frozen = resolve_trading_fields_at(
        source=SOURCE, instrument="AU.SHFE",
        event=TradingFieldEvent(pd.Timestamp("2025-01-02T13:00:00Z"), date(2025, 1, 3)),
        provider=_provider(), rules=_rules(),
    )
    assert frozen.timestamp == "2025-01-02T21:00:00"
    assert frozen.value("CloseTodayRatioByVolume") == 4


def test_missing_historical_field_fails_closed() -> None:
    with pytest.raises(TradingFieldContractError, match="missing PriceTick"):
        resolve_trading_fields_at(
            source=SOURCE, instrument="AU.SHFE",
            event=_event(21, 0, date(2025, 1, 3)),
            provider=_provider(missing="PriceTick"), rules=_rules(),
        )


def test_latest_snapshot_cannot_masquerade_as_history() -> None:
    with pytest.raises(TradingFieldContractError, match="latest/approximate snapshot"):
        resolve_trading_fields_at(
            source=SOURCE, instrument="AU.SHFE",
            event=_event(21, 0, date(2025, 1, 3)),
            provider=_provider(latest=True), rules=_rules(),
        )


@pytest.mark.parametrize("rules, match", [
    ((), "trading_sessions: no authoritative version"),
    ((_rules()[0],), "daily_settlement: no authoritative version"),
    ((EffectiveRule("trading_sessions", pd.Timestamp("2025-01-01"), "snapshot",
                    "observed", {"intervals": [("09:00", "15:00")]}), _rules()[1]),
     "lacks exchange provenance"),
])
def test_missing_or_inferred_calendar_rules_fail_closed(rules, match: str) -> None:
    with pytest.raises(TradingFieldContractError, match=match):
        resolve_trading_fields_at(
            source=SOURCE, instrument="AU.SHFE",
            event=_event(21, 0, date(2025, 1, 3)),
            provider=_provider(), rules=rules,
        )


def test_source_registry_binding_rejects_unadmitted_or_undated_feed() -> None:
    capability = SimpleNamespace(
        family_key="Local", member_key="MIN1", timezone="Asia/Shanghai",
        adapter_id="verified", delivery_mode="historical_snapshot",
    )
    bound = bind_trading_field_source(SimpleNamespace(
        capability=capability,
        bundle_related_members=("FieldHistory:market_rules:exchange",),
    ))
    assert bound.adapter_id == "verified"
    capability.adapter_id = None
    with pytest.raises(TradingFieldContractError, match="no verified adapter"):
        bind_trading_field_source(SimpleNamespace(
            capability=capability,
            bundle_related_members=("FieldHistory:market_rules:exchange",),
        ))


def test_source_owned_provider_binding_freezes_changing_fields() -> None:
    execution_provider = object()
    capability = SimpleNamespace(
        family_key="Local", member_key=SOURCE.member_key, timezone=SOURCE.timezone,
        adapter_id=SOURCE.adapter_id, delivery_mode="historical_snapshot",
    )
    resolved = SimpleNamespace(
        capability=capability, execution_provider=execution_provider,
        bundle_related_members=("FieldHistory:market_rules:exchange",),
    )
    loads: list[str] = []
    member = SimpleNamespace(
        key=SOURCE.member_key, timezone=SOURCE.timezone,
        execution_provider=execution_provider,
        trading_field_provider_ref="FieldHistory:market_rules:exchange",
        trading_field_related_members=("FieldHistory:market_rules:exchange",),
        trading_field_effective_clock="effective_timestamp_or_trading_day",
        load_trading_field_provider=lambda: (loads.append("loaded") or _changing_provider()),
    )
    assert loads == []
    binding = bind_historical_trading_fields(resolved, member)
    assert loads == ["loaded"]
    via_catalog = bind_trading_fields_from_catalog(
        resolved, [SimpleNamespace(key="Local", members=(member,))],
    )
    assert via_catalog.provider_ref == binding.provider_ref
    assert loads == ["loaded", "loaded"]
    resolved.member = member
    direct = bind_trading_fields_from_catalog(resolved)
    assert direct.provider_ref == binding.provider_ref
    assert loads == ["loaded", "loaded", "loaded"]
    frozen = freeze_bound_trading_field_timeline(
        binding=binding, instrument="AU.SHFE",
        events=[_event(20, 59, date(2025, 1, 2)),
                _event(21, 0, date(2025, 1, 3))], rules=_rules(),
    )
    assert [row.value("CloseTodayRatioByVolume") for row in frozen] == [1, 4]
    assert [row.value("VolumeMultiple") for row in frozen] == [10, 10]
    assert [row.value("LongMarginRatioByMoney") for row in frozen] == [1, 2]


def _changing_provider() -> FieldHistoryProvider:
    rows = _provider().frame.drop(columns=[column for column in _provider().frame.columns
                                           if column.startswith("_")]).to_dict("records")
    for name, value in (("LongMarginRatioByMoney", 2),):
        rows.append({
            "provider": "SHFE:exchange-notice", "source_key": f"exchange/au/{name}/change",
            "instrument": "AU", "instrument_type": "future", "field_name": name,
            "effective_trading_day": "2025-01-03",
            "effective_timestamp": "2025-01-02 21:00:00", "value": value,
        })
    return FieldHistoryProvider.from_records(rows)


def test_one_contract_cannot_change_multiplier_during_replay() -> None:
    frame = _changing_provider().frame
    rows = frame.drop(
        columns=[column for column in frame.columns
                 if column.startswith("_")],
    ).to_dict("records")
    rows.append({
        "provider": "SHFE:exchange-notice", "source_key": "exchange/au/multiplier/change",
        "instrument": "AU", "instrument_type": "future",
        "field_name": "VolumeMultiple", "effective_trading_day": "2025-01-03",
        "effective_timestamp": "2025-01-02 21:00:00", "value": 20,
    })
    with pytest.raises(TradingFieldContractError, match="VolumeMultiple changed"):
        freeze_trading_field_timeline(
            source=SOURCE, instrument="AU.SHFE",
            events=[_event(20, 59, date(2025, 1, 2)),
                    _event(21, 0, date(2025, 1, 3))],
            provider=FieldHistoryProvider.from_records(rows), rules=_rules(),
        )


def test_source_owned_provider_ref_is_not_hardcoded() -> None:
    execution_provider = object()
    capability = SimpleNamespace(
        family_key="Local", member_key=SOURCE.member_key, timezone=SOURCE.timezone,
        adapter_id=SOURCE.adapter_id, delivery_mode="historical_snapshot",
    )
    resolved = SimpleNamespace(
        capability=capability, execution_provider=execution_provider,
        bundle_related_members=("SourceOwned:rules:exchange",),
    )
    member = SimpleNamespace(
        key=SOURCE.member_key, timezone=SOURCE.timezone,
        execution_provider=execution_provider,
        trading_field_provider_ref="SourceOwned:rules:exchange",
        trading_field_related_members=("SourceOwned:rules:exchange",),
        trading_field_effective_clock="effective_timestamp_or_trading_day",
        load_trading_field_provider=lambda: _provider(),
    )
    binding = bind_historical_trading_fields(resolved, member)
    assert binding.provider_ref == "SourceOwned:rules:exchange"
    resolved.bundle_related_members = ("Other:rules",)
    with pytest.raises(TradingFieldContractError, match="not declared by the frozen Bundle"):
        bind_historical_trading_fields(resolved, member)


def test_source_owned_provider_binding_rejects_missing_or_mismatched_metadata() -> None:
    execution_provider = object()
    capability = SimpleNamespace(
        family_key="Local", member_key=SOURCE.member_key, timezone=SOURCE.timezone,
        adapter_id=SOURCE.adapter_id, delivery_mode="historical_snapshot",
    )
    resolved = SimpleNamespace(
        capability=capability, execution_provider=execution_provider,
        bundle_related_members=("FieldHistory:market_rules:exchange",),
    )
    member = SimpleNamespace(
        key=SOURCE.member_key, timezone=SOURCE.timezone,
        execution_provider=execution_provider,
        trading_field_provider_ref="", trading_field_effective_clock="unspecified",
        trading_field_related_members=("FieldHistory:market_rules:exchange",),
        load_trading_field_provider=lambda: _provider(),
    )
    with pytest.raises(TradingFieldContractError, match="no declared historical"):
        bind_historical_trading_fields(resolved, member)
    member.trading_field_provider_ref = "FieldHistory:market_rules:exchange"
    resolved.bundle_related_members = ()
    with pytest.raises(TradingFieldContractError, match="no valid related"):
        bind_historical_trading_fields(resolved, member)
    resolved.bundle_related_members = ("FieldHistory:market_rules:exchange",)
    member.trading_field_effective_clock = "wrong_clock"
    with pytest.raises(TradingFieldContractError, match="unsupported historical field clock"):
        bind_historical_trading_fields(resolved, member)
    member.trading_field_effective_clock = "effective_timestamp_or_trading_day"
    member.execution_provider = object()
    with pytest.raises(TradingFieldContractError, match="different source member"):
        bind_historical_trading_fields(resolved, member)
    with pytest.raises(TradingFieldContractError, match="exactly one registered source member"):
        bind_trading_fields_from_catalog(resolved, [SimpleNamespace(key="Other", members=(member,))])


def test_effective_rule_freezes_nested_source_payload() -> None:
    intervals = [["09:00", "15:00"]]
    rule = EffectiveRule("trading_sessions", pd.Timestamp("2025-01-01"),
                         "exchange/calendar", "exchange_calendar", {"intervals": intervals})
    intervals[0][0] = "10:00"
    assert rule.value["intervals"] == (("09:00", "15:00"),)
    with pytest.raises(TypeError):
        rule.value["intervals"] = ()


def test_conflicting_versions_and_disordered_events_fail_closed() -> None:
    duplicate = (*_rules(), EffectiveRule(
        "trading_sessions", pd.Timestamp("2025-01-01"), "exchange/second",
        "exchange_notice", {"intervals": [("09:00", "10:00")]}))
    with pytest.raises(TradingFieldContractError, match="conflicting versions"):
        resolve_trading_fields_at(
            source=SOURCE, instrument="AU.SHFE",
            event=_event(21, 0, date(2025, 1, 3)),
            provider=_provider(), rules=duplicate,
        )
    with pytest.raises(TradingFieldContractError, match="strictly time ordered"):
        freeze_trading_field_timeline(
            source=SOURCE, instrument="AU.SHFE",
            events=[_event(21, 0, date(2025, 1, 3)),
                    _event(20, 59, date(2025, 1, 2))],
            provider=_provider(), rules=_rules(),
        )

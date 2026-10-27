"""Freeze exchange trading rules at the event's actual effective time.

The source catalog describes a market-data feed, not a historical rule book.
Callers must bind an admitted feed to an explicit source-owned provider and
provide separately versioned session/settlement rules.  No latest snapshot,
calendar-date guess, or missing-field default is allowed into an execution run.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from tools.data.field_history import (
    OPENCTP_LATEST_FIELD_PROVIDER,
    OPENCTP_LATEST_FIELD_SOURCE_KEY,
)
from traderesearch_data.rules import TradingFieldProvider, TradingFieldValue

MARKET_RULE_FIELDS = (
    "VolumeMultiple", "PriceTick", "MinLimitOrderVolume", "MaxLimitOrderVolume",
    "OpenRatioByMoney", "OpenRatioByVolume",
    "CloseRatioByMoney", "CloseRatioByVolume",
    "CloseTodayRatioByMoney", "CloseTodayRatioByVolume",
    "LongMarginRatioByMoney", "LongMarginRatioByVolume",
    "ShortMarginRatioByMoney", "ShortMarginRatioByVolume",
)
POSITIVE_FIELDS = frozenset({"VolumeMultiple", "PriceTick", "MinLimitOrderVolume",
                             "MaxLimitOrderVolume"})


class TradingFieldContractError(ValueError):
    """Historical trading rules are absent, ambiguous, or non-authoritative."""


@dataclass(frozen=True, slots=True)
class TradingFieldSource:
    family_key: str
    member_key: str
    timezone: str
    adapter_id: str


@dataclass(frozen=True, slots=True)
class HistoricalTradingFieldBinding:
    source: TradingFieldSource
    provider_ref: str
    effective_clock: str
    provider: TradingFieldProvider


def bind_trading_field_source(resolved_source: Any) -> TradingFieldSource:
    """Bind a verified source-registry result without reading another feed."""
    capability = resolved_source.capability
    if (capability.adapter_id is None or not capability.family_key
            or not capability.member_key or not capability.timezone):
        raise TradingFieldContractError("market-data source has no verified adapter/timezone")
    if capability.delivery_mode != "historical_snapshot":
        raise TradingFieldContractError("source is not a frozen historical feed")
    try:
        ZoneInfo(capability.timezone)
    except KeyError as exc:
        raise TradingFieldContractError("source timezone is unknown") from exc
    return TradingFieldSource(
        capability.family_key, capability.member_key,
        capability.timezone, capability.adapter_id,
    )


def bind_historical_trading_fields(
    resolved_source: Any, source_member: Any,
) -> HistoricalTradingFieldBinding:
    """Lazily bind an admitted feed to its source-owned rule history.

    Catalog reads must never call this function.  The loader is invoked only
    while freezing an execution; merely seeing a data-source row is not enough.
    """
    source = bind_trading_field_source(resolved_source)
    if (str(getattr(source_member, "key", "")) != source.member_key
            or str(getattr(source_member, "timezone", "")) != source.timezone
            or source_member.execution_provider is not resolved_source.execution_provider):
        raise TradingFieldContractError("historical fields belong to a different source member")
    provider_ref = str(getattr(source_member, "trading_field_provider_ref", "") or "")
    related = tuple(getattr(source_member, "trading_field_related_members", ()) or ())
    effective_clock = str(getattr(source_member, "trading_field_effective_clock", "") or "")
    if not provider_ref:
        raise TradingFieldContractError(
            f"{source.member_key}: no declared historical trading-field provider binding"
        )
    if not related:
        raise TradingFieldContractError(
            f"{source.member_key}: no declared related historical member"
        )
    if any(not isinstance(value, str) or not value for value in related):
        raise TradingFieldContractError("related historical members must be non-empty strings")
    if provider_ref not in related:
        raise TradingFieldContractError(
            f"{source.member_key}: historical provider is not a declared related member"
        )
    if effective_clock != "effective_timestamp_or_trading_day":
        raise TradingFieldContractError(
            f"{source.member_key}: unsupported historical field clock {effective_clock!r}"
        )
    try:
        provider = source_member.load_trading_field_provider()
    except (AttributeError, OSError, RuntimeError, ValueError) as exc:
        raise TradingFieldContractError(
            f"{source.member_key}: historical field provider is unavailable"
        ) from exc
    if not isinstance(provider, TradingFieldProvider):
        raise TradingFieldContractError(
            f"{source.member_key}: historical field loader returned an invalid provider"
        )
    return HistoricalTradingFieldBinding(source, provider_ref, effective_clock, provider)


def bind_trading_fields_from_catalog(
    resolved_source: Any, declarations: Iterable[Any] | None = None,
) -> HistoricalTradingFieldBinding:
    """Pair a resolved NT feed with its registered source-owned history loader.

    This is an execution-time operation.  Manager discovery must use only the
    metadata projection and must never load the historical rule database.
    """
    if declarations is None and getattr(resolved_source, "member", None) is not None:
        return bind_historical_trading_fields(resolved_source, resolved_source.member)
    if declarations is None:
        from tools.data.source_catalog import data_source_declarations

        declarations = data_source_declarations()
    capability = resolved_source.capability
    matches = [member for declaration in declarations
               if declaration.key == capability.family_key
               for member in declaration.members
               if member.key == capability.member_key]
    if len(matches) != 1:
        raise TradingFieldContractError(
            f"{capability.member_key}: expected exactly one registered source member"
        )
    return bind_historical_trading_fields(resolved_source, matches[0])


@dataclass(frozen=True, slots=True)
class TradingFieldEvent:
    timestamp: datetime | pd.Timestamp
    trading_day: date


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    name: str
    value: Decimal
    effective_trading_day: str
    effective_timestamp: str | None
    provider: str
    source_key: str
    source_notice_id: str


@dataclass(frozen=True, slots=True)
class EffectiveRule:
    kind: str
    effective_at: datetime | pd.Timestamp
    source_key: str
    authority: str
    value: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _immutable_mapping(self.value))


def _immutable_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    def freeze(item: Any) -> Any:
        if isinstance(item, Mapping):
            return MappingProxyType({str(key): freeze(val) for key, val in item.items()})
        if isinstance(item, (list, tuple)):
            return tuple(freeze(val) for val in item)
        if item is None or isinstance(item, (str, int, float, bool, Decimal)):
            return item
        raise TradingFieldContractError("effective rule contains a mutable or unsupported value")

    return freeze(value)


@dataclass(frozen=True, slots=True)
class FrozenTradingFields:
    source: TradingFieldSource
    instrument: str
    timestamp: str
    trading_day: str
    fields: tuple[FieldEvidence, ...]
    trading_sessions: EffectiveRule
    daily_settlement: EffectiveRule

    @property
    def daily_settlement_eligible(self) -> bool:
        """Whether an authoritative exchange rule provides DMTM inputs.

        RunSpec chooses whether NautilusTrader's optional implementation is
        requested. The effective exchange rule supplies eligibility, official
        price field, and settlement time; it does not override RunSpec intent.
        """
        return self.daily_settlement.value["eligible"] is True

    def should_apply_daily_settlement(self, run_policy: str) -> bool:
        """Combine the frozen RunSpec policy with this product's rule evidence."""
        if run_policy not in {"eligible_products", "disabled"}:
            raise TradingFieldContractError(f"unknown daily settlement policy {run_policy!r}")
        return run_policy == "eligible_products" and self.daily_settlement_eligible

    def value(self, name: str) -> Decimal:
        for item in self.fields:
            if item.name == name:
                return item.value
        raise KeyError(name)


class _ExactDayResolver:
    def __init__(self, timestamp: pd.Timestamp, trading_day: date) -> None:
        self.timestamp = timestamp
        self.trading_day = pd.Timestamp(trading_day)

    def resolve_trading_day(self, timestamp: Any, instrument: str | None = None) -> pd.Timestamp:
        if pd.Timestamp(timestamp) != self.timestamp:
            raise TradingFieldContractError("event has no exact source trading_day")
        return self.trading_day


def _local_timestamp(value: datetime | pd.Timestamp, timezone: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        raise TradingFieldContractError("event timestamp is missing")
    if ts.tz is not None:
        ts = ts.tz_convert(ZoneInfo(timezone)).tz_localize(None)
    return ts


def _rule_at(
    rules: Iterable[EffectiveRule], kind: str, timestamp: pd.Timestamp,
    timezone: str,
) -> EffectiveRule:
    candidates: list[tuple[pd.Timestamp, EffectiveRule]] = []
    seen: set[pd.Timestamp] = set()
    for rule in rules:
        if rule.kind != kind:
            continue
        if (rule.authority not in {"exchange_notice", "exchange_calendar"}
                or not rule.source_key or not rule.value):
            raise TradingFieldContractError(f"{kind}: rule lacks exchange provenance/value")
        if kind == "trading_sessions" and not rule.value.get("intervals"):
            raise TradingFieldContractError("trading_sessions: intervals are required")
        if kind == "daily_settlement" and not isinstance(rule.value.get("eligible"), bool):
            raise TradingFieldContractError(
                "daily_settlement: eligible must be an explicit exchange-rule boolean"
            )
        if kind == "daily_settlement" and rule.value["eligible"] is True and (
            rule.value.get("price_field") != "settlement_price"
            or not rule.value.get("close_time")
        ):
            raise TradingFieldContractError(
                "daily_settlement: eligible rules require settlement_price and close_time"
            )
        at = _local_timestamp(rule.effective_at, timezone)
        if at in seen:
            raise TradingFieldContractError(f"{kind}: conflicting versions at {at.isoformat()}")
        seen.add(at)
        if at <= timestamp:
            candidates.append((at, rule))
    if not candidates:
        raise TradingFieldContractError(
            f"{kind}: no authoritative version effective at {timestamp.isoformat()}"
        )
    return max(candidates, key=lambda item: item[0])[1]


def _field_evidence(field: str, record: TradingFieldValue) -> FieldEvidence:
    if (record.approximated or not record.provider or not record.source_key
            or record.provider == OPENCTP_LATEST_FIELD_PROVIDER
            or record.source_key.startswith(OPENCTP_LATEST_FIELD_SOURCE_KEY)):
        raise TradingFieldContractError(f"{field}: latest/approximate snapshot is not historical evidence")
    try:
        value = Decimal(str(record.value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TradingFieldContractError(f"{field}: non-numeric historical value") from exc
    if not value.is_finite() or value < 0 or (field in POSITIVE_FIELDS and value == 0):
        raise TradingFieldContractError(f"{field}: invalid historical value {value}")
    if field in {"MinLimitOrderVolume", "MaxLimitOrderVolume"} and value != value.to_integral_value():
        raise TradingFieldContractError(f"{field}: order volume must be integral")
    return FieldEvidence(
        name=field, value=value,
        effective_trading_day=record.effective_trading_day.date().isoformat(),
        effective_timestamp=(record.effective_timestamp.isoformat()
                             if record.effective_timestamp is not None else None),
        provider=record.provider, source_key=record.source_key,
        source_notice_id=record.source_notice_id,
    )


def resolve_trading_fields_at(
    *, source: TradingFieldSource, instrument: str, event: TradingFieldEvent,
    provider: TradingFieldProvider, rules: Iterable[EffectiveRule],
) -> FrozenTradingFields:
    """Resolve every execution field against the event's exact trading day/time."""
    if not instrument or not source.adapter_id:
        raise TradingFieldContractError("instrument and admitted source are required")
    timestamp = _local_timestamp(event.timestamp, source.timezone)
    day = pd.Timestamp(event.trading_day)
    if pd.isna(day) or day != day.normalize():
        raise TradingFieldContractError("source trading_day must be an exact date")
    frozen_rules = tuple(rules)
    sessions = _rule_at(frozen_rules, "trading_sessions", timestamp, source.timezone)
    settlement = _rule_at(frozen_rules, "daily_settlement", timestamp, source.timezone)
    resolver = _ExactDayResolver(timestamp, day.date())
    fields: list[FieldEvidence] = []
    for name in MARKET_RULE_FIELDS:
        try:
            resolved = provider.resolve_at(
                instrument, name, timestamp,
                trading_day_resolver=resolver,
                fallback="strict_historical",
            )
        except LookupError as exc:
            raise TradingFieldContractError(
                f"{source.member_key}/{instrument}: missing {name} at {timestamp.isoformat()}: {exc}"
            ) from exc
        fields.append(_field_evidence(name, resolved))
    values = {field.name: field.value for field in fields}
    if values["MinLimitOrderVolume"] > values["MaxLimitOrderVolume"]:
        raise TradingFieldContractError("minimum order volume exceeds maximum")
    return FrozenTradingFields(
        source, instrument, timestamp.isoformat(), day.date().isoformat(),
        tuple(fields), sessions, settlement,
    )


def iter_trading_field_timeline(
    *, source: TradingFieldSource, instrument: str,
    events: Iterable[TradingFieldEvent], provider: TradingFieldProvider,
    rules: Iterable[EffectiveRule],
) -> Iterator[FrozenTradingFields]:
    """Stream source-aligned rules without retaining every bar's full snapshot."""
    frozen_rules = tuple(rules)
    previous: pd.Timestamp | None = None
    contract_multiplier: Decimal | None = None
    for event in events:
        timestamp = _local_timestamp(event.timestamp, source.timezone)
        if previous is not None and timestamp <= previous:
            raise TradingFieldContractError("events must be strictly time ordered")
        previous = timestamp
        frozen = resolve_trading_fields_at(
            source=source, instrument=instrument, event=event,
            provider=provider, rules=frozen_rules,
        )
        multiplier = frozen.value("VolumeMultiple")
        if contract_multiplier is None:
            contract_multiplier = multiplier
        elif multiplier != contract_multiplier:
            raise TradingFieldContractError(
                f"{source.member_key}/{instrument}: VolumeMultiple changed from "
                f"{contract_multiplier} to {multiplier} within one contract; "
                "verify the contract definition before running"
            )
        yield frozen
    if previous is None:
        raise TradingFieldContractError("cannot freeze an empty execution timeline")


def freeze_trading_field_timeline(
    *, source: TradingFieldSource, instrument: str,
    events: Iterable[TradingFieldEvent], provider: TradingFieldProvider,
    rules: Iterable[EffectiveRule],
) -> tuple[FrozenTradingFields, ...]:
    """Materialize an auditable timeline when every event snapshot is needed."""
    return tuple(iter_trading_field_timeline(
        source=source, instrument=instrument, events=events,
        provider=provider, rules=rules,
    ))


def freeze_bound_trading_field_timeline(
    *, binding: HistoricalTradingFieldBinding, instrument: str,
    events: Iterable[TradingFieldEvent], rules: Iterable[EffectiveRule],
) -> tuple[FrozenTradingFields, ...]:
    """Freeze one run against the exact source-owned provider captured at bind."""
    return freeze_trading_field_timeline(
        source=binding.source, instrument=instrument, events=events,
        provider=binding.provider, rules=rules,
    )

"""公共的历史字段存储与查询 helper。

该模块表示“某个产品/合约字段从某个交易日起生效”的时间序列规则。
数据源（例如 agent 清洗后的交易所公告、OpenCTP 或后续来源）只负责把自己的
原始事件归一化写入这里；回测侧（例如 MarketDataModule）只消费统一接口。
"""

from __future__ import annotations

import sys

if __name__ == "__main__":
    _script_dir = __file__.rsplit("/", 1)[0]
    if sys.path and sys.path[0] == _script_dir:
        sys.path.pop(0)
    _repo_root = _script_dir.rsplit("/", 2)[0]
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    sys.modules.setdefault("tools.data.field_history", sys.modules[__name__])

import json
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Protocol, cast

import pandas as pd

from tools.data.hub import DataHub
from tools.data.sqlite.db import connect_sqlite
from tools.data.types.time_index import DataIndex


HISTORICAL_FIELD_TABLE = "historical_field_values"

OPENCTP_LATEST_FIELD_PROVIDER = "OpenCTP:latest"
OPENCTP_LATEST_FIELD_SOURCE_KEY = "openctp/latest_snapshot"

OPENCTP_MARKET_RULE_FIELDS = (
    "VolumeMultiple",
    "PriceTick",
    "MinLimitOrderVolume",
    "MaxLimitOrderVolume",
    "OpenRatioByMoney",
    "OpenRatioByVolume",
    "CloseRatioByMoney",
    "CloseRatioByVolume",
    "CloseTodayRatioByMoney",
    "CloseTodayRatioByVolume",
    "LongMarginRatioByMoney",
    "LongMarginRatioByVolume",
    "ShortMarginRatioByMoney",
    "ShortMarginRatioByVolume",
)

TRANSACTION_FEE_FIELD_NAMES = (
    "OpenRatioByMoney",
    "OpenRatioByVolume",
    "CloseRatioByMoney",
    "CloseRatioByVolume",
    "CloseTodayRatioByMoney",
    "CloseTodayRatioByVolume",
)

TRANSACTION_FEE_SOURCE_EXCHANGE = "exchange"
TRANSACTION_FEE_SOURCE_OPENCTP = "openctp"
TRANSACTION_FEE_SOURCES = (
    TRANSACTION_FEE_SOURCE_EXCHANGE,
    TRANSACTION_FEE_SOURCE_OPENCTP,
)

FIELD_HISTORY_VALUE_CHANGE_TYPES = {
    "change",
    "baseline",
    "reaffirmation",
    "exception_unchanged",
    "asof_confirmed",
    "rule",
}

FIELD_HISTORY_COLUMNS = [
    "provider",
    "source_key",
    "instrument",
    "instrument_label",
    "instrument_type",
    "scope_type",
    "exchange",
    "field_name",
    "effective_trading_day",
    "effective_timestamp",
    "value",
    "value_type",
    "previous_value",
    "previous_value_type",
    "previous_value_note",
    "contract_codes",
    "contract_scope_type",
    "contract_code_start",
    "contract_code_end",
    "change_type",
    "source_url",
    "source_date",
    "source_notice_id",
    "raw_note",
]

FIELD_HISTORY_PRIMARY_KEY = [
    "provider",
    "source_key",
    "instrument",
    "instrument_type",
    "field_name",
    "effective_trading_day",
    "effective_timestamp",
    "contract_codes",
    "contract_scope_type",
    "contract_code_start",
    "contract_code_end",
]


class HistoricalFieldFallbackPolicy(str, Enum):
    STRICT_HISTORICAL = "strict_historical"
    LATEST_AVAILABLE = "latest_available"


class HistoricalFieldLookupError(LookupError):
    pass


class MissingTradingDay(HistoricalFieldLookupError):
    pass


class MissingHistoricalField(HistoricalFieldLookupError):
    pass


class HistoricalFieldIntegrityError(HistoricalFieldLookupError):
    pass


class TradingDayResolver(Protocol):
    def resolve_trading_day(self, timestamp: Any, instrument: str | None = None) -> pd.Timestamp: ...


@dataclass(frozen=True, slots=True)
class FieldInstrumentIdentity:
    raw_instrument: str
    product_code: str
    instrument_type: str = "future"
    contract_code: str | None = None
    exchange: str | None = None


@dataclass(frozen=True, slots=True)
class HistoricalFieldValue:
    instrument: str
    field_name: str
    value: Any
    effective_trading_day: pd.Timestamp
    effective_timestamp: pd.Timestamp | None = None
    source_key: str = ""
    provider: str = ""
    source_date: str = ""
    source_notice_id: str = ""
    approximated: bool = False
    contract_code: str | None = None


class TimestampTradingDayResolver:
    """根据实际时间戳查交易日。

    mapping 可以是:
    - DataFrame: index 为实际时间戳，包含 ``trading_day`` 列
    - Series: index 为实际时间戳，值为 trading_day
    - Mapping: {timestamp: trading_day}
    """

    def __init__(self, mapping: pd.DataFrame | pd.Series | Mapping[Any, Any], *, allow_asof: bool = True) -> None:
        if isinstance(mapping, pd.DataFrame):
            if "trading_day" not in mapping.columns:
                raise ValueError("timestamp/trading_day DataFrame must contain 'trading_day'")
            series = mapping["trading_day"]
        elif isinstance(mapping, pd.Series):
            series = mapping
        else:
            series = pd.Series(dict(mapping))
        index = pd.DatetimeIndex([_normalise_timestamp_key(value) for value in series.index])
        values = pd.to_datetime(series.to_numpy(), errors="coerce")
        self._series = pd.Series(values, index=index).dropna().sort_index()
        self._allow_asof = allow_asof
        # Keep cache lifetime and statistics scoped to this immutable mapping.
        # Decorating the class method directly would retain resolver instances
        # as global cache keys and make one run's metrics affect another's.
        self._resolve_cached = lru_cache(maxsize=16_384)(
            self._resolve_uncached,
        )

    def resolve_trading_day(self, timestamp: Any, instrument: str | None = None) -> pd.Timestamp:
        ts = _normalise_timestamp_key(timestamp)
        day = self._resolve_cached(ts)
        if day is not None:
            return day
        raise MissingTradingDay(
            f"no trading_day mapping for timestamp={ts.isoformat()}"
            + (f", instrument={instrument}" if instrument else "")
        )

    def _resolve_uncached(self, timestamp: pd.Timestamp) -> pd.Timestamp | None:
        """Resolve one immutable timestamp with a bounded run-scoped cache."""
        try:
            day = self._series.loc[timestamp]
        except KeyError:
            if self._allow_asof and not self._series.empty:
                ts_key = timestamp.to_datetime64()
                pos = self._series.index.searchsorted(ts_key, side="right") - 1
                if pos < 0:
                    pos = self._series.index.searchsorted(ts_key, side="left")
                if 0 <= pos < len(self._series):
                    return _normalise_trading_day(self._series.iloc[int(pos)])
            return None
        return _normalise_trading_day(day)

    def resolve_trading_days(self, timestamps: Sequence[Any], instrument: str | None = None) -> pd.DatetimeIndex:
        index = pd.DatetimeIndex([_normalise_timestamp_key(timestamp) for timestamp in timestamps])
        if index.empty:
            return pd.DatetimeIndex([])
        resolved = self._series.reindex(index)
        missing = resolved.isna()
        if bool(missing.any()):
            missing_index = pd.DatetimeIndex(index[missing.to_numpy()])
            if not self._allow_asof or self._series.empty:
                missing_ts = cast(pd.Timestamp, pd.Timestamp(cast(Any, missing_index)[0]))
                raise MissingTradingDay(
                    f"no trading_day mapping for timestamp={missing_ts.isoformat()}"
                    + (f", instrument={instrument}" if instrument else "")
                )
            positions = cast(Any, self._series.index.searchsorted(missing_index, side="right")) - 1
            missing_values: list[pd.Timestamp] = []
            for raw_pos, raw_ts in zip(list(positions), list(missing_index)):
                pos = int(cast(Any, raw_pos))
                ts = cast(pd.Timestamp, pd.Timestamp(raw_ts))
                if pos < 0:
                    pos = self._series.index.searchsorted(ts.to_datetime64(), side="left")
                if not (0 <= pos < len(self._series)):
                    raise MissingTradingDay(
                        f"no trading_day mapping for timestamp={ts.isoformat()}"
                        + (f", instrument={instrument}" if instrument else "")
                    )
                missing_values.append(_normalise_trading_day(self._series.iloc[int(pos)]))
            resolved.loc[missing] = missing_values
        return DataIndex.normalized_days(pd.DatetimeIndex(pd.to_datetime(resolved.to_numpy(), errors="coerce")))


class CalendarDateTradingDayResolver:
    """退化 resolver：直接把 timestamp 的自然日期当交易日。

    只适合明确没有交易日列的数据；真实交易数据模式应使用
    TimestampTradingDayResolver，并在缺映射时报错。
    """

    def resolve_trading_day(self, timestamp: Any, instrument: str | None = None) -> pd.Timestamp:
        return _normalise_trading_day(timestamp)


class FieldHistoryProvider:
    """内存历史字段查询器。"""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = _normalise_history_frame(frame)
        if not self.frame.empty:
            self.frame = cast(
                pd.DataFrame,
                self.frame[_series(self.frame, "change_type").isin(FIELD_HISTORY_VALUE_CHANGE_TYPES)].copy(),
            )
            self.frame = self.frame.sort_values(
                ["instrument", "field_name", "effective_trading_day", "effective_timestamp"]
            ).reset_index(drop=True)
            self.frame["_scope_codes"] = _series(self.frame, "contract_codes").map(_decode_contract_codes)
            self.frame["_scope_type"] = _series(self.frame, "contract_scope_type").map(_normalise_contract_scope_type)
            self.frame["_product_level"] = _series(self.frame, "_scope_type").map(lambda value: value == "all")
        self._subset_cache: dict[tuple[str, str, str, str], pd.DataFrame] = {}
        # The provider frame is immutable for the lifetime of a replay.  A
        # missing product/field combination is therefore just as stable as a
        # successful subset lookup; remember it so fallback/event lookups do
        # not rescan the full history frame on every request.
        self._missing_subset_cache: set[tuple[str, str, str, str]] = set()
        # Exchange defaults are shared by every product on that exchange.  A
        # small index avoids repeating the same boolean masks against the
        # complete frame for each product/field lookup.
        self._exchange_default_cache: dict[
            tuple[str, str, str], pd.DataFrame | None
        ] = {}
        self._subset_index = self._build_subset_index()

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]]) -> "FieldHistoryProvider":
        return cls(pd.DataFrame(list(records)))

    def resolve_by_trading_day(
        self,
        instrument: Any,
        field_name: str,
        trading_day: Any,
        *,
        instrument_type: str | None = "future",
        fallback: HistoricalFieldFallbackPolicy | str = HistoricalFieldFallbackPolicy.STRICT_HISTORICAL,
    ) -> HistoricalFieldValue:
        policy = HistoricalFieldFallbackPolicy(fallback)
        day = _normalise_trading_day(trading_day)
        identity = _resolve_field_instrument_identity(instrument, day, instrument_type=instrument_type)
        subset = self._subset(identity.product_code, field_name, identity.instrument_type, exchange=identity.exchange)
        eligible = cast(pd.DataFrame, subset[_series(subset, "effective_trading_day") <= day])
        eligible = _filter_contract_scope(eligible, identity.contract_code)
        approximated = False
        if eligible.empty:
            if policy == HistoricalFieldFallbackPolicy.LATEST_AVAILABLE and not subset.empty:
                scoped_fallback = _filter_contract_scope(subset, identity.contract_code)
                scoped_fallback = _nearest_fallback_candidates(scoped_fallback, field_name)
                eligible = _nearest_by_trading_day(scoped_fallback, day)
                approximated = not eligible.empty
            if eligible.empty:
                first = _series(subset, "effective_trading_day").min() if not subset.empty else None
                suffix = f"; first effective day is {first.date()}" if first is not None else ""
                raise MissingHistoricalField(
                    f"no historical value for {identity.raw_instrument}.{field_name} at trading_day={day.date()}{suffix}"
                )
        if "_contract_scope_priority" in eligible.columns:
            eligible = cast(
                pd.DataFrame,
                eligible[
                    _series(eligible, "_contract_scope_priority")
                    == _series(eligible, "_contract_scope_priority").max()
                ],
            )
        row = _sort_history_candidates(eligible, effective_key="effective_trading_day").iloc[-1]
        self._assert_previous_value_integrity(
            row,
            subset,
            contract_code=identity.contract_code,
            raw_instrument=identity.raw_instrument,
            field_name=field_name,
        )
        return HistoricalFieldValue(
            instrument=identity.product_code,
            field_name=field_name,
            value=_decode_value(row["value"], row.get("value_type")),
            effective_trading_day=_normalise_trading_day(row["effective_trading_day"]),
            effective_timestamp=_optional_timestamp(row.get("effective_timestamp")),
            source_key=str(row.get("source_key") or ""),
            provider=str(row.get("provider") or ""),
            source_date=str(row.get("source_date") or ""),
            source_notice_id=str(row.get("source_notice_id") or ""),
            approximated=approximated,
            contract_code=identity.contract_code,
        )

    def resolve_at(
        self,
        instrument: Any,
        field_name: str,
        timestamp: Any,
        *,
        trading_day_resolver: TradingDayResolver | None,
        instrument_type: str | None = "future",
        fallback: HistoricalFieldFallbackPolicy | str = HistoricalFieldFallbackPolicy.STRICT_HISTORICAL,
    ) -> HistoricalFieldValue:
        if trading_day_resolver is None:
            raise MissingTradingDay("trading_day_resolver is required for timestamp lookup")
        ts = _normalise_timestamp_key(timestamp)
        trading_day = trading_day_resolver.resolve_trading_day(ts, _instrument_name(instrument))
        identity = _resolve_field_instrument_identity(instrument, trading_day, instrument_type=instrument_type)
        policy = HistoricalFieldFallbackPolicy(fallback)
        subset = self._subset(identity.product_code, field_name, identity.instrument_type, exchange=identity.exchange)
        effective_timestamp = _series(subset, "effective_timestamp")
        effective_trading_day = _series(subset, "effective_trading_day")
        timestamp_mask = effective_timestamp.notna() & (effective_timestamp <= ts)
        trading_day_mask = effective_timestamp.isna() & (effective_trading_day <= trading_day)
        candidates = cast(pd.DataFrame, subset[timestamp_mask | trading_day_mask]).copy()
        candidates = _filter_contract_scope(candidates, identity.contract_code)
        approximated = False
        if candidates.empty:
            if policy == HistoricalFieldFallbackPolicy.LATEST_AVAILABLE and not subset.empty:
                scoped_fallback = _filter_contract_scope(subset, identity.contract_code)
                scoped_fallback = _nearest_fallback_candidates(scoped_fallback, field_name)
                candidates = _nearest_by_timestamp(scoped_fallback, ts, trading_day)
                approximated = not candidates.empty
            if candidates.empty:
                raise MissingHistoricalField(
                    f"no historical value for {identity.raw_instrument}.{field_name} at "
                    f"timestamp={ts.isoformat()}, trading_day={trading_day.date()}"
                )
        candidates["_effective_sort_key"] = _series(candidates, "effective_timestamp").fillna(
            _series(candidates, "effective_trading_day")
        )
        if "_contract_scope_priority" in candidates.columns:
            candidates = cast(
                pd.DataFrame,
                candidates[
                    _series(candidates, "_contract_scope_priority")
                    == _series(candidates, "_contract_scope_priority").max()
                ],
            )
        row = _sort_history_candidates(candidates, effective_key="_effective_sort_key").iloc[-1]
        self._assert_previous_value_integrity(
            row,
            subset,
            contract_code=identity.contract_code,
            raw_instrument=identity.raw_instrument,
            field_name=field_name,
        )
        return HistoricalFieldValue(
            instrument=identity.product_code,
            field_name=field_name,
            value=_decode_value(row["value"], row.get("value_type")),
            effective_trading_day=_normalise_trading_day(row["effective_trading_day"]),
            effective_timestamp=_optional_timestamp(row.get("effective_timestamp")),
            source_key=str(row.get("source_key") or ""),
            provider=str(row.get("provider") or ""),
            source_date=str(row.get("source_date") or ""),
            source_notice_id=str(row.get("source_notice_id") or ""),
            approximated=approximated,
            contract_code=identity.contract_code,
        )

    def values_for_index(
        self,
        instrument: Any,
        field_name: str,
        index: Iterable[Any],
        *,
        trading_day_resolver: TradingDayResolver,
        instrument_type: str | None = "future",
        fallback: HistoricalFieldFallbackPolicy | str = HistoricalFieldFallbackPolicy.STRICT_HISTORICAL,
    ) -> pd.Series:
        query_frame = self.query_frame_for_index(
            instrument,
            index,
            trading_day_resolver=trading_day_resolver,
            instrument_type=instrument_type,
        )
        return self.values_for_query_frame(
            instrument,
            field_name,
            query_frame,
            fallback=fallback,
        )

    def query_frame_for_index(
        self,
        instrument: Any,
        index: Iterable[Any],
        *,
        trading_day_resolver: TradingDayResolver,
        instrument_type: str | None = "future",
    ) -> pd.DataFrame:
        timestamps = [_normalise_timestamp_key(timestamp) for timestamp in index]
        if not timestamps:
            return pd.DataFrame(columns=[
                "_row", "timestamp", "trading_day", "product_code", "instrument_type", "contract_code", "exchange"
            ])
        trading_days = [
            trading_day_resolver.resolve_trading_day(timestamp, _instrument_name(instrument))
            for timestamp in timestamps
        ]
        identities = [
            _resolve_field_instrument_identity(instrument, trading_day, instrument_type=instrument_type)
            for trading_day in trading_days
        ]
        query_frame = pd.DataFrame({
            "_row": list(range(len(timestamps))),
            "timestamp": timestamps,
            "trading_day": trading_days,
            "product_code": [identity.product_code for identity in identities],
            "instrument_type": [identity.instrument_type for identity in identities],
            "contract_code": [identity.contract_code or "" for identity in identities],
            "exchange": [identity.exchange or "" for identity in identities],
        })
        return query_frame

    def query_frame_for_timestamps(
        self,
        instrument: Any,
        timestamps: Sequence[Any],
        trading_days: Sequence[Any],
        *,
        instrument_type: str | None = "future",
    ) -> pd.DataFrame:
        normalized_timestamps = [_normalise_timestamp_key(timestamp) for timestamp in timestamps]
        normalized_days = [_normalise_trading_day(day) for day in trading_days]
        if len(normalized_timestamps) != len(normalized_days):
            raise ValueError("timestamps and trading_days must have the same length")
        if not normalized_timestamps:
            return pd.DataFrame(columns=[
                "_row", "timestamp", "trading_day", "product_code", "instrument_type", "contract_code", "exchange"
            ])
        identities_by_day = {
            day: _resolve_field_instrument_identity(instrument, day, instrument_type=instrument_type)
            for day in dict.fromkeys(normalized_days)
        }
        identities = [identities_by_day[day] for day in normalized_days]
        return pd.DataFrame({
            "_row": list(range(len(normalized_timestamps))),
            "timestamp": normalized_timestamps,
            "trading_day": normalized_days,
            "product_code": [identity.product_code for identity in identities],
            "instrument_type": [identity.instrument_type for identity in identities],
            "contract_code": [identity.contract_code or "" for identity in identities],
            "exchange": [identity.exchange or "" for identity in identities],
        })

    def values_for_query_frame(
        self,
        instrument: Any,
        field_name: str,
        query_frame: pd.DataFrame,
        *,
        fallback: HistoricalFieldFallbackPolicy | str = HistoricalFieldFallbackPolicy.STRICT_HISTORICAL,
    ) -> pd.Series:
        policy = HistoricalFieldFallbackPolicy(fallback)
        if query_frame.empty:
            return pd.Series([], index=pd.DatetimeIndex([]), name=field_name, dtype=object)
        timestamps = list(_series(query_frame, "timestamp"))
        row_values: list[pd.Series] = []
        for key, group in query_frame.groupby(["product_code", "instrument_type", "exchange"], sort=False):
            product_code, resolved_type, exchange = cast(tuple[Any, Any, Any], key)
            try:
                subset = self._subset(
                    str(product_code),
                    field_name,
                    str(resolved_type),
                    exchange=str(exchange or "") or None,
                )
            except MissingHistoricalField:
                if policy == HistoricalFieldFallbackPolicy.STRICT_HISTORICAL:
                    raise
                # No historical rows for this instrument at all -- under a
                # fallback policy there is nothing to fall back to, so leave
                # these rows as None rather than aborting the whole lookup.
                continue
            values = _vectorized_values_from_subset(
                subset,
                group,
                policy=policy,
                raw_instrument=_instrument_name(instrument),
                field_name=field_name,
            )
            row_values.append(values)
        if row_values:
            ordered_values = pd.concat(row_values).reindex(_series(query_frame, "_row"))
        else:
            ordered_values = pd.Series([None] * len(timestamps), index=_series(query_frame, "_row"), dtype=object)
        result = pd.Series(
            list(ordered_values),
            index=pd.DatetimeIndex(timestamps),
            name=field_name,
            dtype=object,
        )
        return result

    def frame_for_index(
        self,
        instruments: Sequence[Any],
        field_name: str,
        index: Iterable[Any],
        *,
        trading_day_resolver: TradingDayResolver,
        instrument_type: str | None = "future",
        fallback: HistoricalFieldFallbackPolicy | str = HistoricalFieldFallbackPolicy.STRICT_HISTORICAL,
    ) -> pd.DataFrame:
        columns = {
            _instrument_name(instrument): self.values_for_index(
                instrument,
                field_name,
                index,
                trading_day_resolver=trading_day_resolver,
                instrument_type=instrument_type,
                fallback=fallback,
            )
            for instrument in instruments
        }
        return pd.DataFrame(columns)

    def _assert_previous_value_integrity(
        self,
        row: pd.Series,
        subset: pd.DataFrame,
        *,
        contract_code: str | None,
        raw_instrument: str,
        field_name: str,
    ) -> None:
        previous_value = _decode_optional_value(row.get("previous_value"), row.get("previous_value_type"))
        if previous_value is None:
            return
        prior = _prior_history_row_for_previous_value(subset, row, contract_code=contract_code)
        if prior is None:
            raise HistoricalFieldIntegrityError(
                _previous_value_integrity_message(
                    row,
                    raw_instrument=raw_instrument,
                    field_name=field_name,
                    reason="no prior historical value",
                    prior=None,
                    expected=previous_value,
                )
            )
        actual = _decode_value(prior.get("value"), prior.get("value_type"))
        if not _same_decoded_value(actual, previous_value):
            raise HistoricalFieldIntegrityError(
                _previous_value_integrity_message(
                    row,
                    raw_instrument=raw_instrument,
                    field_name=field_name,
                    reason=f"previous_value mismatch: expected {previous_value!r}, found {actual!r}",
                    prior=prior,
                    expected=previous_value,
                )
            )

    def _subset(
        self,
        instrument: str,
        field_name: str,
        instrument_type: str | None,
        *,
        exchange: str | None = None,
    ) -> pd.DataFrame:
        normalized_exchange = str(exchange or "").upper()
        cache_key = (instrument, field_name, instrument_type or "", normalized_exchange)
        cached = self._subset_cache.get(cache_key)
        if cached is not None:
            return cached
        if cache_key in self._missing_subset_cache:
            suffix = f", exchange={normalized_exchange}" if normalized_exchange else ""
            raise MissingHistoricalField(
                f"no historical field rows for {instrument}.{field_name}{suffix}"
            )
        if self.frame.empty:
            raise MissingHistoricalField("historical field table is empty")
        parts: list[pd.DataFrame] = []
        if instrument_type:
            subset = self._subset_index.get((instrument, field_name, instrument_type or ""))
            if subset is not None and not subset.empty:
                parts.append(subset)
        if not parts:
            instrument_matches = cast(pd.DataFrame, self.frame[_series(self.frame, "instrument") == instrument])
            if not instrument_matches.empty:
                type_matches = instrument_matches
                if instrument_type:
                    type_matches = cast(
                        pd.DataFrame,
                        instrument_matches[_series(instrument_matches, "instrument_type") == instrument_type],
                    )
                subset = cast(pd.DataFrame, type_matches[_series(type_matches, "field_name") == field_name])
                if not subset.empty:
                    parts.append(subset)
        if normalized_exchange:
            exchange_default = self._exchange_default_subset(normalized_exchange, field_name, instrument_type)
            if exchange_default is not None and not exchange_default.empty:
                parts.append(exchange_default)
        if not parts:
            suffix = f", exchange={normalized_exchange}" if normalized_exchange else ""
            self._missing_subset_cache.add(cache_key)
            raise MissingHistoricalField(f"no historical field rows for {instrument}.{field_name}{suffix}")
        subset = pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]
        self._subset_cache[cache_key] = subset
        return subset

    def _exchange_default_subset(
        self,
        exchange: str,
        field_name: str,
        instrument_type: str | None,
    ) -> pd.DataFrame | None:
        cache_key = (str(exchange or "").upper(), field_name, instrument_type or "")
        if cache_key in self._exchange_default_cache:
            return self._exchange_default_cache[cache_key]
        indexed = self._subset_index.get(("*", field_name, instrument_type or "")) if instrument_type else None
        if indexed is None:
            indexed = cast(pd.DataFrame, self.frame[_series(self.frame, "instrument") == "*"])
            indexed = cast(pd.DataFrame, indexed[_series(indexed, "field_name") == field_name])
            if instrument_type:
                indexed = cast(pd.DataFrame, indexed[_series(indexed, "instrument_type") == instrument_type])
        if indexed.empty:
            self._exchange_default_cache[cache_key] = None
            return None
        scope = _series(indexed, "scope_type").astype(str).str.lower()
        exchanges = _series(indexed, "exchange").astype(str).str.upper()
        result = cast(pd.DataFrame, indexed[(scope == "exchange_default") & (exchanges == cache_key[0])])
        self._exchange_default_cache[cache_key] = result
        return result

    def _build_subset_index(self) -> dict[tuple[str, str, str], pd.DataFrame]:
        if self.frame.empty:
            return {}
        result: dict[tuple[str, str, str], pd.DataFrame] = {}
        for key, group in self.frame.groupby(["instrument", "field_name", "instrument_type"], sort=False):
            instrument, field_name, instrument_type = cast(tuple[Any, Any, Any], key)
            result[(str(instrument), str(field_name), str(instrument_type or ""))] = cast(pd.DataFrame, group)
        return result


def save_historical_field_records(
    records: Iterable[Mapping[str, Any]],
    *,
    store_key: str = "openctp",
    replace_provider: str | None = None,
    replace_source_key: str | None = None,
) -> str:
    """写入公共历史字段表。

    若传入 replace_provider / replace_source_key，会先删除对应来源的数据，再追加新值；
    这样一个数据源重复同步时不会产生重复历史行。
    """
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    path = hub._get_sqlite_store(store_key).path()
    df = _normalise_history_frame(pd.DataFrame(list(records)))
    storage_df = _serialise_history_frame(df)
    with hub.connect_store(store_key) as conn:
        _ensure_schema(conn)
        if replace_provider is not None or replace_source_key is not None:
            clauses: list[str] = []
            params: list[Any] = []
            if replace_provider is not None:
                clauses.append("provider = ?")
                params.append(replace_provider)
            if replace_source_key is not None:
                clauses.append("source_key = ?")
                params.append(replace_source_key)
            conn.execute(
                f'DELETE FROM "{HISTORICAL_FIELD_TABLE}" WHERE {" AND ".join(clauses)}',
                params,
            )
        _upsert_history_frame(conn, storage_df)
    return path


def load_historical_field_frame(*, store_key: str = "openctp") -> pd.DataFrame:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    try:
        with hub.connect_store(store_key) as conn:
            _ensure_schema(conn)
            return pd.read_sql_query(f'SELECT * FROM "{HISTORICAL_FIELD_TABLE}"', conn)
    except sqlite3.Error:
        return pd.DataFrame(columns=FIELD_HISTORY_COLUMNS)


def summarize_historical_field_coverage(
    product_names: Sequence[str],
    *,
    store_key: str = "openctp",
) -> list[dict[str, Any]]:
    """Summarize scoped FieldHistory coverage with one aggregate SQL query.

    This intentionally returns audit-safe identities and coverage only. Values,
    database paths, raw notes, and source URLs remain in the evidence store.
    """
    names = [str(name).strip() for name in product_names if str(name).strip()]
    if not names:
        return []
    products_by_code: dict[str, list[str]] = {}
    for name in names:
        code = name.split(".", 1)[0].split("|", 1)[0].upper()
        products_by_code.setdefault(code, []).append(name)
    codes = sorted(products_by_code)
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT
            UPPER(instrument) AS product_code,
            field_name,
            COUNT(*) AS record_count,
            MIN(effective_trading_day) AS coverage_start,
            MAX(effective_trading_day) AS coverage_end,
            GROUP_CONCAT(DISTINCT provider) AS providers,
            COUNT(DISTINCT source_key) AS source_count
        FROM {HISTORICAL_FIELD_TABLE}
        WHERE UPPER(instrument) IN ({placeholders})
        GROUP BY UPPER(instrument), field_name
        ORDER BY UPPER(instrument), field_name
    """
    try:
        with hub.connect_store(store_key) as conn:
            _ensure_schema(conn)
            rows = conn.execute(sql, codes).fetchall()
    except sqlite3.Error:
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        code = str(row["product_code"])
        for product in products_by_code.get(code, []):
            result.append({
                "product": product,
                "field": str(row["field_name"]),
                "record_count": int(row["record_count"]),
                "coverage_start": str(row["coverage_start"] or ""),
                "coverage_end": str(row["coverage_end"] or ""),
                "providers": sorted(filter(None, str(row["providers"] or "").split(","))),
                "source_count": int(row["source_count"]),
            })
    return result


def load_historical_field_provider(*, store_key: str = "openctp") -> FieldHistoryProvider:
    return FieldHistoryProvider(load_historical_field_frame(store_key=store_key))


def load_market_rule_field_provider(
    *,
    store_key: str = "openctp",
    include_openctp_latest: bool = True,
    transaction_fee_source: str = TRANSACTION_FEE_SOURCE_EXCHANGE,
) -> FieldHistoryProvider:
    """Load FieldHistory rows plus OpenCTP's latest contract specs.

    FieldHistory remains the single consumer-facing interface. Agent-cleaned
    exchange events are stored in ``historical_field_values``; OpenCTP latest
    rows are folded in here as an open-past baseline so backtests can still run
    before every historical notice has been cleaned. Contract-level rows keep a
    single ``contract_codes`` value, so querying a Futures product first expands
    through its term structure and then matches the fee/spec row for the active
    contract.
    """
    frame = load_historical_field_frame(store_key=store_key)
    frame = _filter_transaction_fee_source_frame(
        frame,
        transaction_fee_source=transaction_fee_source,
        is_openctp_latest=False,
    )
    if not include_openctp_latest:
        return FieldHistoryProvider(frame)
    latest = load_openctp_latest_market_rule_frame(store_key=store_key)
    latest = _filter_transaction_fee_source_frame(
        latest,
        transaction_fee_source=transaction_fee_source,
        is_openctp_latest=True,
    )
    if latest.empty:
        return FieldHistoryProvider(frame)
    combined = pd.concat([frame, latest], ignore_index=True) if not frame.empty else latest
    return FieldHistoryProvider(combined)


def _filter_transaction_fee_source_frame(
    frame: pd.DataFrame,
    *,
    transaction_fee_source: str,
    is_openctp_latest: bool,
) -> pd.DataFrame:
    """Keep non-fee market-rule fields, and choose one fee source class.

    Exchange fees are official FieldHistory events. Broker fees are OpenCTP's
    account snapshot. Both still share non-fee fields such as VolumeMultiple
    and margin ratios, so filtering applies only to TransactionFee fields.
    """
    source = _normalise_transaction_fee_source(transaction_fee_source)
    if frame.empty or "field_name" not in frame.columns:
        return frame
    is_fee = cast(pd.Series, frame["field_name"]).isin(TRANSACTION_FEE_FIELD_NAMES)
    provider_is_openctp = cast(pd.Series, frame["provider"]).astype(str) == OPENCTP_LATEST_FIELD_PROVIDER
    is_openctp_source = provider_is_openctp | bool(is_openctp_latest)
    if source == TRANSACTION_FEE_SOURCE_EXCHANGE:
        mask = ~is_fee | ~is_openctp_source
    elif source == TRANSACTION_FEE_SOURCE_OPENCTP:
        mask = ~is_fee | is_openctp_source
    else:  # pragma: no cover - _normalise_transaction_fee_source validates.
        raise ValueError(f"unsupported transaction_fee_source: {source!r}")
    return cast(pd.DataFrame, frame.loc[mask].copy())


def _normalise_transaction_fee_source(value: object) -> str:
    source = str(value or TRANSACTION_FEE_SOURCE_EXCHANGE).strip().lower()
    aliases = {
        "auto": TRANSACTION_FEE_SOURCE_EXCHANGE,
        "automatic": TRANSACTION_FEE_SOURCE_EXCHANGE,
        "exchange_base": TRANSACTION_FEE_SOURCE_EXCHANGE,
        "broker_openctp": TRANSACTION_FEE_SOURCE_OPENCTP,
        "openctp_broker": TRANSACTION_FEE_SOURCE_OPENCTP,
    }
    source = aliases.get(source, source)
    if source not in TRANSACTION_FEE_SOURCES:
        raise ValueError(
            f"unsupported transaction_fee_source: {value!r}; "
            f"expected one of {', '.join(TRANSACTION_FEE_SOURCES)}"
        )
    return source


def load_openctp_latest_market_rule_frame(*, store_key: str = "openctp") -> pd.DataFrame:
    """Represent OpenCTP latest contract specs as FieldHistory records."""
    try:
        from sources.OpenCTP.client import read_cnfutures_contract_specs_for_date, read_latest_cnfutures_product_specs
    except Exception:
        return pd.DataFrame(columns=FIELD_HISTORY_COLUMNS)

    try:
        specs = read_cnfutures_contract_specs_for_date(None, allow_latest_fallback=True)
    except Exception:
        return pd.DataFrame(columns=FIELD_HISTORY_COLUMNS)
    if specs.empty:
        return pd.DataFrame(columns=FIELD_HISTORY_COLUMNS)

    source_date = str(specs.attrs.get("fee_source_date") or "")
    effective_trading_day = _source_date_to_trading_day(source_date)
    source_key_suffix = source_date or "latest"
    rows: list[dict[str, Any]] = []
    for _, spec in specs.iterrows():
        product_id = str(spec.get("ProductID") or "").strip().upper()
        if not product_id:
            continue
        instrument_id = str(spec.get("InstrumentID") or spec.get("NormalizedInstrumentID") or "").strip()
        contract_code = _contract_code_from_instrument_name(f"{instrument_id}.DUMMY")
        if not contract_code:
            contract_code = _contract_month_from_instrument_id(instrument_id, product_id)
        contract_codes = [contract_code] if contract_code else []
        instrument_label = str(spec.get("InstrumentName") or "")
        for field_name in OPENCTP_MARKET_RULE_FIELDS:
            if field_name not in spec.index:
                continue
            value = spec.get(field_name)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            rows.append({
                "provider": OPENCTP_LATEST_FIELD_PROVIDER,
                "source_key": f"{OPENCTP_LATEST_FIELD_SOURCE_KEY}/{source_key_suffix}/{instrument_id}/{field_name}",
                "instrument": product_id,
                "instrument_label": instrument_label,
                "instrument_type": "future",
                "field_name": field_name,
                "effective_trading_day": effective_trading_day,
                "effective_timestamp": "",
                "value": value,
                "value_type": "",
                "contract_codes": contract_codes,
                "source_url": "OpenCTP latest cnfutures contract specs",
                "source_date": source_date,
                "source_notice_id": "OpenCTP latest snapshot",
                "raw_note": "Latest OpenCTP contract-level snapshot used as baseline until exchange notice history is cleaned.",
            })
    try:
        product_specs = read_latest_cnfutures_product_specs()
    except Exception:
        product_specs = pd.DataFrame()
    if not product_specs.empty:
        product_source_date = str(product_specs.attrs.get("fee_source_date") or source_date or "")
        product_effective_trading_day = _source_date_to_trading_day(product_source_date)
        product_source_key_suffix = product_source_date or source_key_suffix
        for _, spec in product_specs.iterrows():
            product_id = str(spec.get("ProductID") or "").strip().upper()
            if not product_id:
                continue
            instrument_label = str(spec.get("InstrumentName") or "")
            for field_name in OPENCTP_MARKET_RULE_FIELDS:
                if field_name not in spec.index:
                    continue
                value = spec.get(field_name)
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    continue
                rows.append({
                    "provider": OPENCTP_LATEST_FIELD_PROVIDER,
                    "source_key": f"{OPENCTP_LATEST_FIELD_SOURCE_KEY}/{product_source_key_suffix}/{product_id}/{field_name}/product",
                    "instrument": product_id,
                    "instrument_label": instrument_label,
                    "instrument_type": "future",
                    "field_name": field_name,
                    "effective_trading_day": product_effective_trading_day,
                    "effective_timestamp": "",
                    "value": value,
                    "value_type": "",
                    "contract_codes": [],
                    "source_url": "OpenCTP latest cnfutures product specs",
                    "source_date": product_source_date,
                    "source_notice_id": "OpenCTP latest snapshot",
                    "raw_note": "Latest OpenCTP product-level market-rule baseline used when no contract-specific historical event is available.",
                })
    return _normalise_history_frame(pd.DataFrame(rows))


def _source_date_to_trading_day(source_date: str) -> str:
    timestamp = pd.to_datetime(str(source_date or "").strip(), format="%Y%m%d", errors="coerce")
    if pd.isna(timestamp):
        timestamp = pd.to_datetime(str(source_date or "").strip(), errors="coerce")
    if pd.isna(timestamp):
        raise ValueError("OpenCTP latest market-rule snapshot is missing source_date; refusing to create a baseline")
    return pd.Timestamp(timestamp).strftime("%Y-%m-%d")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (HISTORICAL_FIELD_TABLE,),
    ).fetchone()
    if existing is not None and _primary_key_columns(conn) != FIELD_HISTORY_PRIMARY_KEY:
        existing_df = pd.read_sql_query(f'SELECT * FROM "{HISTORICAL_FIELD_TABLE}"', conn)
        conn.execute(f'DROP TABLE "{HISTORICAL_FIELD_TABLE}"')
        _create_schema(conn)
        storage_df = _serialise_history_frame(_normalise_history_frame(existing_df))
        storage_df.to_sql(HISTORICAL_FIELD_TABLE, conn, if_exists="append", index=False)
        return
    _create_schema(conn)
    if existing is not None:
        _migrate_contract_scope_values(conn)


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {HISTORICAL_FIELD_TABLE} (
            provider TEXT NOT NULL,
            source_key TEXT NOT NULL,
            instrument TEXT NOT NULL,
            instrument_label TEXT,
            instrument_type TEXT NOT NULL,
            scope_type TEXT NOT NULL DEFAULT 'product',
            exchange TEXT,
            field_name TEXT NOT NULL,
            effective_trading_day TEXT NOT NULL,
            effective_timestamp TEXT,
            value TEXT NOT NULL,
            value_type TEXT NOT NULL,
            previous_value TEXT,
            previous_value_type TEXT,
            previous_value_note TEXT,
            contract_codes TEXT NOT NULL,
            contract_scope_type TEXT NOT NULL DEFAULT 'all',
            contract_code_start TEXT,
            contract_code_end TEXT,
            change_type TEXT NOT NULL DEFAULT 'change',
            source_url TEXT,
            source_date TEXT,
            source_notice_id TEXT,
            raw_note TEXT,
            PRIMARY KEY (provider, source_key, instrument, instrument_type, field_name, effective_trading_day, effective_timestamp, contract_codes, contract_scope_type, contract_code_start, contract_code_end)
        )
        """
    )
    existing_columns = {
        row["name"]
        for row in conn.execute(f'PRAGMA table_info("{HISTORICAL_FIELD_TABLE}")').fetchall()
    }
    if "effective_timestamp" not in existing_columns:
        conn.execute(f'ALTER TABLE "{HISTORICAL_FIELD_TABLE}" ADD COLUMN effective_timestamp TEXT')
    if "source_notice_id" not in existing_columns:
        conn.execute(f'ALTER TABLE "{HISTORICAL_FIELD_TABLE}" ADD COLUMN source_notice_id TEXT')
    if "previous_value" not in existing_columns:
        conn.execute(f'ALTER TABLE "{HISTORICAL_FIELD_TABLE}" ADD COLUMN previous_value TEXT')
    if "previous_value_type" not in existing_columns:
        conn.execute(f'ALTER TABLE "{HISTORICAL_FIELD_TABLE}" ADD COLUMN previous_value_type TEXT')
    if "previous_value_note" not in existing_columns:
        conn.execute(f'ALTER TABLE "{HISTORICAL_FIELD_TABLE}" ADD COLUMN previous_value_note TEXT')
    if "scope_type" not in existing_columns:
        conn.execute(f'ALTER TABLE "{HISTORICAL_FIELD_TABLE}" ADD COLUMN scope_type TEXT NOT NULL DEFAULT "product"')
    if "exchange" not in existing_columns:
        conn.execute(f'ALTER TABLE "{HISTORICAL_FIELD_TABLE}" ADD COLUMN exchange TEXT')
    if "contract_scope_type" not in existing_columns:
        conn.execute(f'ALTER TABLE "{HISTORICAL_FIELD_TABLE}" ADD COLUMN contract_scope_type TEXT NOT NULL DEFAULT "all"')
    if "contract_code_start" not in existing_columns:
        conn.execute(f'ALTER TABLE "{HISTORICAL_FIELD_TABLE}" ADD COLUMN contract_code_start TEXT')
    if "contract_code_end" not in existing_columns:
        conn.execute(f'ALTER TABLE "{HISTORICAL_FIELD_TABLE}" ADD COLUMN contract_code_end TEXT')
    if "change_type" not in existing_columns:
        conn.execute(f'ALTER TABLE "{HISTORICAL_FIELD_TABLE}" ADD COLUMN change_type TEXT NOT NULL DEFAULT "change"')
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{HISTORICAL_FIELD_TABLE}_lookup
        ON {HISTORICAL_FIELD_TABLE} (instrument, field_name, effective_trading_day, effective_timestamp)
        """
    )


def _migrate_contract_scope_values(conn: sqlite3.Connection) -> None:
    existing_df = pd.read_sql_query(f'SELECT * FROM "{HISTORICAL_FIELD_TABLE}"', conn)
    if existing_df.empty:
        return
    normalised = _serialise_history_frame(_normalise_history_frame(existing_df))
    comparable_columns = [column for column in FIELD_HISTORY_COLUMNS if column in existing_df.columns]
    old = existing_df[comparable_columns].fillna("").astype(str).reset_index(drop=True)
    new = normalised[comparable_columns].fillna("").astype(str).reset_index(drop=True)
    if len(old) == len(new) and old.equals(new):
        return
    conn.execute(f'DELETE FROM "{HISTORICAL_FIELD_TABLE}"')
    normalised.to_sql(HISTORICAL_FIELD_TABLE, conn, if_exists="append", index=False)


def _upsert_history_frame(conn: sqlite3.Connection, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    columns = FIELD_HISTORY_COLUMNS
    placeholders = ", ".join(["?"] * len(columns))
    quoted_columns = ", ".join(columns)
    conn.executemany(
        f'INSERT OR REPLACE INTO "{HISTORICAL_FIELD_TABLE}" ({quoted_columns}) VALUES ({placeholders})',
        [tuple(row[column] for column in columns) for _, row in frame.iterrows()],
    )


def _ensure_store_registered(hub: DataHub, store_key: str) -> None:
    if store_key == "openctp":
        hub.ensure_visits_schema()


def _primary_key_columns(conn: sqlite3.Connection) -> list[str]:
    try:
        rows = conn.execute(f'PRAGMA table_info("{HISTORICAL_FIELD_TABLE}")').fetchall()
    except sqlite3.Error:
        return []
    keyed = sorted(
        ((int(row["pk"]), str(row["name"])) for row in rows if int(row["pk"]) > 0),
        key=lambda item: item[0],
    )
    return [name for _, name in keyed]


def _normalise_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=FIELD_HISTORY_COLUMNS)
    df = frame.copy()
    for column in FIELD_HISTORY_COLUMNS:
        if column not in df.columns:
            df[column] = "" if column not in {"value", "previous_value", "effective_trading_day"} else None
    df = cast(pd.DataFrame, df[FIELD_HISTORY_COLUMNS].copy())
    df["instrument"] = _series(df, "instrument").astype(str).str.strip()
    df["field_name"] = _series(df, "field_name").astype(str).str.strip()
    df["provider"] = _series(df, "provider").astype(str).str.strip()
    df["source_key"] = _series(df, "source_key").astype(str).str.strip()
    df["instrument_type"] = _series(df, "instrument_type").replace("", "unknown").fillna("unknown")
    df["scope_type"] = _series(df, "scope_type").replace("", "product").fillna("product")
    df["scope_type"] = _series(df, "scope_type").astype(str).str.strip().str.lower()
    df["exchange"] = _series(df, "exchange").fillna("").astype(str).str.strip().str.upper()
    df["effective_trading_day"] = cast(
        pd.Series,
        pd.to_datetime(_series(df, "effective_trading_day"), errors="coerce"),
    ).dt.normalize()
    df["effective_timestamp"] = cast(
        pd.Series,
        pd.to_datetime(_series(df, "effective_timestamp"), errors="coerce"),
    )
    df = cast(pd.DataFrame, df.loc[_series(df, "effective_trading_day").notna()].copy())
    df = cast(pd.DataFrame, df[(_series(df, "instrument") != "") & (_series(df, "field_name") != "")])
    df["value_type"] = _series(df, "value_type").replace("", None)
    value_pairs = _series(df, "value").map(_encode_value)
    df["value"] = value_pairs.map(lambda item: item[0])
    df["value_type"] = _series(df, "value_type").fillna(value_pairs.map(lambda item: item[1]))
    previous_pairs = _series(df, "previous_value").map(_encode_optional_value)
    df["previous_value"] = previous_pairs.map(lambda item: item[0])
    df["previous_value_type"] = _series(df, "previous_value_type").replace("", None).fillna(
        previous_pairs.map(lambda item: item[1])
    ).fillna("")
    df["previous_value_note"] = _series(df, "previous_value_note").map(_clean_optional_text)
    df["contract_codes"] = _series(df, "contract_codes").map(_encode_contract_codes)
    df["contract_scope_type"] = [
        _normalise_contract_scope_type(scope_type, contract_codes=contract_codes, start=start, end=end)
        for scope_type, contract_codes, start, end in zip(
            _series(df, "contract_scope_type"),
            _series(df, "contract_codes"),
            _series(df, "contract_code_start"),
            _series(df, "contract_code_end"),
        )
    ]
    df["contract_code_start"] = _series(df, "contract_code_start").map(lambda value: _clean_optional_text(value).upper())
    df["contract_code_end"] = _series(df, "contract_code_end").map(lambda value: _clean_optional_text(value).upper())
    df["change_type"] = _series(df, "change_type").map(_normalise_change_type)
    df = df.drop_duplicates(subset=FIELD_HISTORY_PRIMARY_KEY, keep="last")
    return df


def _serialise_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    df["effective_trading_day"] = _series(df, "effective_trading_day").dt.strftime("%Y-%m-%d")
    df["effective_timestamp"] = _series(df, "effective_timestamp").map(
        lambda value: "" if pd.isna(value) else pd.Timestamp(value).isoformat()
    )
    return df


def _encode_optional_value(value: Any) -> tuple[str, str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "", ""
    text = str(value).strip() if isinstance(value, str) else None
    if text is not None and text == "":
        return "", ""
    encoded, value_type = _encode_value(value)
    return encoded, value_type


def _normalise_timestamp_key(value: Any) -> pd.Timestamp:
    ts = cast(pd.Timestamp, pd.Timestamp(value))
    if pd.isna(ts):
        raise MissingTradingDay(f"invalid timestamp: {value!r}")
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts


def _normalise_trading_day(value: Any) -> pd.Timestamp:
    ts = cast(pd.Timestamp, pd.Timestamp(value))
    if pd.isna(ts):
        raise MissingTradingDay(f"invalid trading day: {value!r}")
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.normalize()


def _optional_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "nat"}:
        return None
    return _normalise_timestamp_key(text)


def _encode_contract_codes(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            return text
        if text:
            return json.dumps([item.strip() for item in text.split(",") if item.strip()], ensure_ascii=False)
        return "[]"
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "[]"
    if not isinstance(value, Iterable):
        return json.dumps([str(value)], ensure_ascii=False)
    return json.dumps(list(value), ensure_ascii=False)


_PIPE_CONTRACT_PATTERN = re.compile(r"^(?P<exchange>[A-Z]+)\|F\|(?P<product>[A-Za-z]+)\|(?P<contract>\d{3,4}[A-Z]*)$")
_DOTTED_CONTRACT_PATTERN = re.compile(r"^(?P<product>[A-Za-z]+)(?P<contract>\d{3,4}[A-Z]*)\.(?P<exchange>[A-Za-z]+)$")
_DOTTED_PRODUCT_PATTERN = re.compile(r"^(?P<product>[A-Za-z]+)\.(?P<exchange>[A-Za-z]+)(?:@.+)?$")


def _instrument_name(instrument: Any) -> str:
    return str(getattr(instrument, "name", instrument) or "").strip()


def _resolve_field_instrument_identity(
    instrument: Any,
    trading_day: Any | None = None,
    *,
    instrument_type: str | None,
) -> FieldInstrumentIdentity:
    raw_name = _instrument_name(instrument)
    resolved_type = instrument_type or "future"
    contract_code = _contract_code_from_instrument_name(raw_name)

    product_obj = None
    if hasattr(instrument, "get_parent_product"):
        try:
            product_obj = instrument.get_parent_product()
        except Exception:
            product_obj = None
    if product_obj is not None:
        product_name = _instrument_name(product_obj)
        parsed_product = _product_code_from_contract_name(raw_name)
        return FieldInstrumentIdentity(
            raw_instrument=raw_name,
            product_code=parsed_product or _product_code_from_product_name(product_name),
            instrument_type=resolved_type,
            contract_code=contract_code,
            exchange=_exchange_from_instrument_name(raw_name) or _exchange_from_instrument_name(product_name),
        )

    if trading_day is not None and hasattr(instrument, "get_contract_id_from_trading_day"):
        try:
            current_contract = instrument.get_contract_id_from_trading_day(trading_day)
        except Exception:
            current_contract = None
        if current_contract:
            contract_code = _contract_code_from_instrument_name(str(current_contract))

    product_code = _product_code_from_product_name(raw_name)
    if trading_day is not None and not contract_code:
        contract_code = _contract_code_for_product_name_at(raw_name, trading_day)
    if contract_code:
        parsed_product = _product_code_from_contract_name(raw_name)
        if parsed_product:
            product_code = parsed_product

    return FieldInstrumentIdentity(
        raw_instrument=raw_name,
        product_code=product_code,
        instrument_type=resolved_type,
        contract_code=contract_code,
        exchange=_exchange_from_instrument_name(raw_name),
    )


def _contract_code_for_product_name_at(name: str, trading_day: Any) -> str | None:
    """Resolve a product-level CN futures name to its contract code at ``trading_day``.

    Field history stores exchange-supplied contract-scoped rows and product-scoped
    fallback rows in the same table. Product-level requests such as ``AP.CZC``
    therefore still need a time-specific contract code so contract rows win when
    available, while product rows remain the fallback.
    """
    text = str(name or "").strip()
    if not text or _contract_code_from_instrument_name(text):
        return None
    if not _DOTTED_PRODUCT_PATTERN.match(text):
        return None
    day_key = str(_normalise_trading_day(trading_day).date())
    return _cached_contract_code_for_product_name_at(text, day_key)


@lru_cache(maxsize=4096)
def _cached_contract_code_for_product_name_at(name: str, trading_day: str) -> str | None:
    try:
        product = _cached_cn_futures_product_for_name(name)
    except Exception:
        return None
    try:
        current_contract = product.get_contract_id_from_trading_day(trading_day)
    except Exception:
        return None
    if not current_contract:
        return None
    return _contract_code_from_instrument_name(str(current_contract))


@lru_cache(maxsize=512)
def _cached_cn_futures_product_for_name(name: str) -> Any:
    from sources.LocalCNFutures.CNFutures import CNFutures

    return CNFutures.get_by_product_name(name) or CNFutures(name)


def _product_code_from_product_name(name: str) -> str:
    text = str(name or "").strip()
    pipe_match = _PIPE_CONTRACT_PATTERN.match(text)
    if pipe_match:
        return _field_history_product_code(pipe_match.group("product"), pipe_match.group("contract"))
    contract_match = _DOTTED_CONTRACT_PATTERN.match(text)
    if contract_match:
        return _field_history_product_code(contract_match.group("product"), contract_match.group("contract"))
    product_match = _DOTTED_PRODUCT_PATTERN.match(text)
    if product_match:
        return product_match.group("product").upper()
    if "." in text:
        text = text.split(".", 1)[0]
    if "@" in text:
        text = text.split("@", 1)[0]
    return text.upper()


def _product_code_from_contract_name(name: str) -> str | None:
    pipe_match = _PIPE_CONTRACT_PATTERN.match(name)
    if pipe_match:
        return _field_history_product_code(pipe_match.group("product"), pipe_match.group("contract"))
    contract_match = _DOTTED_CONTRACT_PATTERN.match(name)
    if contract_match:
        return _field_history_product_code(contract_match.group("product"), contract_match.group("contract"))
    return None


def _field_history_product_code(product: str, contract_code: str | None = None) -> str:
    product_code = str(product or "").strip().upper()
    contract = str(contract_code or "").strip().upper()
    if contract.endswith("F") and product_code and not product_code.endswith("_F"):
        return f"{product_code}_F"
    return product_code


def _contract_code_from_instrument_name(name: str) -> str | None:
    pipe_match = _PIPE_CONTRACT_PATTERN.match(name)
    if pipe_match:
        return pipe_match.group("contract")
    contract_match = _DOTTED_CONTRACT_PATTERN.match(name)
    if contract_match:
        return contract_match.group("contract")
    return None


def _exchange_from_instrument_name(name: str) -> str | None:
    text = str(name or "").strip()
    pipe_match = _PIPE_CONTRACT_PATTERN.match(text)
    if pipe_match:
        exchange = pipe_match.group("exchange").upper()
        return {
            "CZCE": "CZC",
            "SHFE": "SHF",
            "CFFEX": "CFE",
            "GFEX": "GFE",
            "INE": "INE",
            "DCE": "DCE",
        }.get(exchange, exchange)
    contract_match = _DOTTED_CONTRACT_PATTERN.match(text)
    if contract_match:
        return contract_match.group("exchange").upper()
    product_match = _DOTTED_PRODUCT_PATTERN.match(text)
    if product_match:
        return product_match.group("exchange").upper()
    return None


def _contract_month_from_instrument_id(instrument_id: str, product_id: str) -> str | None:
    text = str(instrument_id or "").strip().upper()
    product = str(product_id or "").strip().upper()
    if product and text.startswith(product):
        suffix = text[len(product):]
        if re.fullmatch(r"\d{3,4}[A-Z]*", suffix or ""):
            return suffix
    match = re.search(r"(\d{3,4}[A-Z]*)$", text)
    return match.group(1) if match else None


def _decode_contract_codes(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = [item.strip() for item in text.split(",")]
    else:
        parsed = value
    if isinstance(parsed, Iterable) and not isinstance(parsed, (str, bytes)):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [str(parsed).strip()] if str(parsed).strip() else []


def _normalise_contract_scope_type(
    value: Any,
    *,
    contract_codes: Any = None,
    start: Any = None,
    end: Any = None,
) -> str:
    text = _clean_optional_text(value).lower()
    if _clean_optional_text(start):
        return "range" if _clean_optional_text(end) else "from_contract"
    if _decode_contract_codes(contract_codes):
        return "explicit"
    if text in {"all", "explicit", "from_contract", "range"}:
        return text
    return "all"


def _normalise_change_type(value: Any) -> str:
    text = _clean_optional_text(value).lower()
    if text in FIELD_HISTORY_VALUE_CHANGE_TYPES or text == "rule":
        return text
    return "change"


def _clean_optional_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def _contract_scope_matches(
    *,
    scope_type: Any,
    scope_codes: list[str],
    contract_code: str | None,
    start: Any = "",
    end: Any = "",
) -> bool:
    scope = _normalise_contract_scope_type(scope_type, contract_codes=scope_codes, start=start, end=end)
    contract = str(contract_code or "").strip().upper()
    if scope == "all":
        return True
    if not contract:
        return False
    if scope == "explicit":
        return contract in {str(code).strip().upper() for code in scope_codes}
    start_text = str(start or "").strip().upper()
    end_text = str(end or "").strip().upper()
    if scope in {"from_contract", "range"} and start_text:
        if _compare_contract_code(contract, start_text) < 0:
            return False
        if scope == "range" and end_text and _compare_contract_code(contract, end_text) > 0:
            return False
        return True
    return False


def _contract_scope_priority(
    *,
    scope_type: Any,
    scope_codes: list[str],
    contract_code: str | None,
    start: Any = "",
    end: Any = "",
) -> int:
    if not _contract_scope_matches(
        scope_type=scope_type,
        scope_codes=scope_codes,
        contract_code=contract_code,
        start=start,
        end=end,
    ):
        return -1
    scope = _normalise_contract_scope_type(scope_type, contract_codes=scope_codes, start=start, end=end)
    return {
        "all": 0,
        "from_contract": 1,
        "range": 2,
        "explicit": 3,
    }.get(scope, 0)


def _compare_contract_code(left: str, right: str) -> int:
    left_key = _contract_code_sort_key(left)
    right_key = _contract_code_sort_key(right)
    return (left_key > right_key) - (left_key < right_key)


def _contract_code_sort_key(value: Any) -> tuple[int, str]:
    text = str(value or "").strip().upper()
    match = re.fullmatch(r"(\d{3,4})([A-Z]*)", text)
    if not match:
        return (-1, text)
    number = match.group(1)
    if len(number) == 3:
        number = f"2{number}"
    return (int(number), match.group(2))


def _filter_contract_scope(frame: pd.DataFrame, contract_code: str | None) -> pd.DataFrame:
    if frame.empty:
        return frame
    df = frame.copy()
    scopes = _series(df, "contract_codes").map(_decode_contract_codes)
    scope_types = _series(df, "contract_scope_type").map(_normalise_contract_scope_type)
    field_scope_types = _series(df, "scope_type").astype(str).str.lower()
    starts = _series(df, "contract_code_start")
    ends = _series(df, "contract_code_end")
    if contract_code:
        priorities = pd.Series([
            _contract_scope_priority(
                scope_type=scope_type,
                scope_codes=codes,
                contract_code=contract_code,
                start=start,
                end=end,
            )
            for scope_type, codes, start, end in zip(scope_types, scopes, starts, ends)
        ], index=df.index)
        scoped = cast(pd.DataFrame, df[priorities >= 0].copy())
        if scoped.empty:
            return scoped
        scoped["_contract_scope_priority"] = priorities.loc[scoped.index] + 1
        scoped.loc[field_scope_types.loc[scoped.index] == "exchange_default", "_contract_scope_priority"] = 0
        scoped = scoped.sort_values(
            by=["effective_trading_day", "effective_timestamp", "_contract_scope_priority"],
        )
        return scoped
    scoped = cast(pd.DataFrame, df[scope_types == "all"].copy())
    if not scoped.empty:
        scoped["_contract_scope_priority"] = 1
        exchange_default = field_scope_types.loc[scoped.index] == "exchange_default"
        scoped.loc[exchange_default, "_contract_scope_priority"] = 0
    return scoped


def _field_provider_priority(provider: Any) -> int:
    text = str(provider or "")
    if "Agent:" in text:
        return 1
    if OPENCTP_LATEST_FIELD_PROVIDER in text:
        return 0
    return 1


def _sort_history_candidates(frame: pd.DataFrame, *, effective_key: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    candidates = frame.copy()
    candidates["_provider_priority"] = _series(candidates, "provider").map(_field_provider_priority)
    sort_columns = [effective_key, "_provider_priority"]
    if "_contract_scope_priority" in candidates.columns:
        sort_columns.insert(0, "_contract_scope_priority")
    return cast(pd.DataFrame, candidates.sort_values(by=sort_columns, kind="mergesort"))


def _nearest_by_trading_day(frame: pd.DataFrame, trading_day: pd.Timestamp) -> pd.DataFrame:
    if frame.empty:
        return frame
    candidates = frame.copy()
    effective_day = _series(candidates, "effective_trading_day")
    candidates["_fallback_distance"] = (effective_day - trading_day).abs()
    candidates["_fallback_is_after"] = effective_day > trading_day
    sort_columns = ["_fallback_distance", "_fallback_is_after", "effective_trading_day", "effective_timestamp"]
    ascending = [True, True, False, False]
    if "_contract_scope_priority" in candidates.columns:
        sort_columns.append("_contract_scope_priority")
        ascending.append(False)
    candidates["_provider_priority"] = _series(candidates, "provider").map(_field_provider_priority)
    sort_columns.append("_provider_priority")
    ascending.append(False)
    return cast(pd.DataFrame, candidates.sort_values(by=sort_columns, ascending=ascending).head(1))


def _nearest_by_timestamp(
    frame: pd.DataFrame,
    timestamp: pd.Timestamp,
    trading_day: pd.Timestamp,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    candidates = frame.copy()
    effective_timestamp = _series(candidates, "effective_timestamp")
    effective_day = _series(candidates, "effective_trading_day")
    timestamp_distance = (effective_timestamp - timestamp).abs()
    day_distance = (effective_day - trading_day).abs()
    candidates["_fallback_distance"] = timestamp_distance.where(effective_timestamp.notna(), day_distance)
    candidates["_fallback_is_after"] = (effective_timestamp > timestamp).where(
        effective_timestamp.notna(),
        effective_day > trading_day,
    )
    candidates["_effective_sort_key"] = effective_timestamp.fillna(effective_day)
    sort_columns = ["_fallback_distance", "_fallback_is_after", "_effective_sort_key"]
    ascending = [True, True, False]
    if "_contract_scope_priority" in candidates.columns:
        sort_columns.append("_contract_scope_priority")
        ascending.append(False)
    candidates["_provider_priority"] = _series(candidates, "provider").map(_field_provider_priority)
    sort_columns.append("_provider_priority")
    ascending.append(False)
    return cast(pd.DataFrame, candidates.sort_values(by=sort_columns, ascending=ascending).head(1))


def _vectorized_values_from_subset(
    subset: pd.DataFrame,
    queries: pd.DataFrame,
    *,
    policy: HistoricalFieldFallbackPolicy,
    raw_instrument: str,
    field_name: str,
) -> pd.Series:
    records = subset
    if "_scope_codes" not in records.columns or "_product_level" not in records.columns:
        records = records.copy()
        records["_scope_codes"] = _series(records, "contract_codes").map(_decode_contract_codes)
        records["_scope_type"] = _series(records, "contract_scope_type").map(_normalise_contract_scope_type)
        records["_product_level"] = _series(records, "_scope_type").map(lambda value: value == "all")
    constant = _constant_product_level_value(records, queries)
    if constant is not None:
        return pd.Series([constant] * len(queries), index=_series(queries, "_row"), dtype=object)
    candidates: list[pd.DataFrame] = []
    for contract_code, group in queries.groupby("contract_code", sort=False):
        contract = str(cast(Any, contract_code) or "")
        if contract:
            field_scope_types = _series(records, "scope_type").astype(str).str.lower()
            priorities = pd.Series([
                _contract_scope_priority(
                    scope_type=scope_type,
                    scope_codes=codes,
                    contract_code=contract,
                    start=start,
                    end=end,
                )
                for scope_type, codes, start, end in zip(
                    _series(records, "contract_scope_type"),
                    _series(records, "_scope_codes"),
                    _series(records, "contract_code_start"),
                    _series(records, "contract_code_end"),
                )
            ], index=records.index)
            scoped = cast(pd.DataFrame, records[priorities >= 0].copy())
            scoped["_scope_priority"] = priorities.loc[scoped.index] + 1
            scoped.loc[field_scope_types.loc[scoped.index] == "exchange_default", "_scope_priority"] = 0
        else:
            scoped = cast(pd.DataFrame, records[_series(records, "_product_level")].copy())
            scoped["_scope_priority"] = 1
            field_scope_types = _series(scoped, "scope_type").astype(str).str.lower()
            scoped.loc[field_scope_types == "exchange_default", "_scope_priority"] = 0
        if scoped.empty:
            continue
        for priority, priority_records in scoped.groupby("_scope_priority", sort=False):
            priority_value = int(cast(Any, priority))
            day_records = cast(
                pd.DataFrame,
                priority_records[_series(priority_records, "effective_timestamp").isna()].copy(),
            )
            ts_records = cast(
                pd.DataFrame,
                priority_records[_series(priority_records, "effective_timestamp").notna()].copy(),
            )
            day_candidates = _merge_asof_history_candidate(
                group,
                day_records,
                query_key="trading_day",
                record_key="effective_trading_day",
                scope_priority=priority_value,
            )
            if day_candidates is not None:
                candidates.append(day_candidates)
            ts_candidates = _merge_asof_history_candidate(
                group,
                ts_records,
                query_key="timestamp",
                record_key="effective_timestamp",
                scope_priority=priority_value,
            )
            if ts_candidates is not None:
                candidates.append(ts_candidates)

    result = pd.Series(index=queries["_row"], dtype=object)
    if candidates:
        all_candidates = pd.concat(candidates, ignore_index=True)
        all_candidates = all_candidates.sort_values(
            ["_row", "_scope_priority", "_effective_sort_key", "_provider_priority"],
            kind="mergesort",
        )
        best = all_candidates.groupby("_row", sort=False).tail(1)
        _assert_vectorized_previous_value_integrity(
            subset,
            best,
            raw_instrument=raw_instrument,
            field_name=field_name,
        )
        row_numbers = [int(cast(Any, row_number)) for row_number in best["_row"]]
        value_types = best["value_type"] if "value_type" in best.columns else pd.Series([""] * len(best))
        decoded_values = [
            _decode_value(value, value_type)
            for value, value_type in zip(best["value"], value_types)
        ]
        result = pd.Series(decoded_values, index=pd.Index(row_numbers), dtype=object).reindex(queries["_row"])

    missing_rows = [int(cast(Any, row)) for row, value in result.items() if pd.isna(value)]
    if missing_rows and policy == HistoricalFieldFallbackPolicy.LATEST_AVAILABLE and not subset.empty:
        query_by_row = queries.set_index("_row", drop=False)
        for row_number in missing_rows:
            query = query_by_row.loc[row_number]
            fallback = _nearest_by_timestamp(
                _nearest_fallback_candidates(
                    _filter_contract_scope(subset, str(query.get("contract_code") or "")),
                    field_name,
                ),
                _normalise_timestamp_key(query["timestamp"]),
                _normalise_trading_day(query["trading_day"]),
            )
            if fallback.empty:
                continue
            fallback_row = fallback.iloc[0]
            _assert_previous_value_integrity_row(
                fallback_row,
                subset,
                contract_code=str(query.get("contract_code") or ""),
                raw_instrument=raw_instrument,
                field_name=field_name,
            )
            result.at[row_number] = _decode_value(fallback_row["value"], fallback_row.get("value_type"))
        missing_rows = [int(cast(Any, row)) for row, value in result.items() if pd.isna(value)]
    if missing_rows:
        raise MissingHistoricalField(
            f"no historical value for {raw_instrument}.{field_name} at {len(missing_rows)} timestamp(s)"
        )
    return result


def _nearest_fallback_candidates(frame: pd.DataFrame, field_name: str) -> pd.DataFrame:
    """Limit source-specific nearest fallback semantics.

    Exchange transaction-fee events are dated official changes and must only
    apply forward from their effective time. OpenCTP latest rows are brokerage
    snapshots, so they may be used as a latest-available baseline for earlier
    timestamps when explicitly selected as the transaction-fee source.
    """
    if frame.empty or field_name not in TRANSACTION_FEE_FIELD_NAMES or "provider" not in frame.columns:
        return frame
    provider = _series(frame, "provider").astype(str)
    openctp = cast(pd.DataFrame, frame.loc[provider == OPENCTP_LATEST_FIELD_PROVIDER].copy())
    return openctp


def _constant_product_level_value(records: pd.DataFrame, queries: pd.DataFrame) -> object | None:
    if len(records) != 1 or queries.empty:
        return None
    row = records.iloc[0]
    if _decode_optional_value(row.get("previous_value"), row.get("previous_value_type")) is not None:
        return None
    scope_codes = row.get("_scope_codes")
    if not isinstance(scope_codes, list) or scope_codes:
        return None
    effective_ts = _optional_timestamp(row.get("effective_timestamp"))
    if effective_ts is not None:
        min_ts = pd.Timestamp(_series(queries, "timestamp").min())
        if effective_ts > min_ts:
            return None
    else:
        effective_day = _normalise_trading_day(row.get("effective_trading_day"))
        min_day = _normalise_trading_day(_series(queries, "trading_day").min())
        if effective_day > min_day:
            return None
    return _decode_value(row.get("value"), row.get("value_type"))


def _merge_asof_history_candidate(
    queries: pd.DataFrame,
    records: pd.DataFrame,
    *,
    query_key: str,
    record_key: str,
    scope_priority: int,
) -> pd.DataFrame | None:
    if queries.empty or records.empty:
        return None
    left_columns = ["_row", query_key]
    if "contract_code" in queries.columns:
        left_columns.append("contract_code")
    left = cast(pd.DataFrame, queries[left_columns].copy())
    left[query_key] = pd.to_datetime(left[query_key], errors="coerce").astype("datetime64[ns]")
    left = cast(pd.DataFrame, left.sort_values(by=cast(Any, query_key)))
    right_columns = list(dict.fromkeys([
        record_key,
        "value",
        "value_type",
        "effective_trading_day",
        "effective_timestamp",
        "provider",
        "source_key",
        "source_notice_id",
        "previous_value",
        "previous_value_type",
        "contract_codes",
        "contract_scope_type",
        "contract_code_start",
        "contract_code_end",
    ]))
    right = cast(pd.DataFrame, records[[column for column in right_columns if column in records.columns]].copy())
    right[record_key] = pd.to_datetime(right[record_key], errors="coerce").astype("datetime64[ns]")
    right = cast(pd.DataFrame, right.sort_values(by=cast(Any, record_key)))
    merged = pd.merge_asof(
        left,
        right,
        left_on=query_key,
        right_on=record_key,
        direction="backward",
    )
    merged = cast(pd.DataFrame, merged[_series(merged, "effective_trading_day").notna()].copy())
    if merged.empty:
        return None
    merged["_scope_priority"] = scope_priority
    merged["_effective_sort_key"] = _series(merged, "effective_timestamp").fillna(
        _series(merged, "effective_trading_day")
    )
    merged["_provider_priority"] = _series(merged, "provider").map(_field_provider_priority)
    return cast(pd.DataFrame, merged[[
        "_row",
        "contract_code",
        "_scope_priority",
        "_effective_sort_key",
        "_provider_priority",
        "value",
        "value_type",
        *[
            column for column in (
                "effective_trading_day",
                "effective_timestamp",
                "provider",
                "source_key",
                "source_notice_id",
                "previous_value",
                "previous_value_type",
                "contract_codes",
                "contract_scope_type",
                "contract_code_start",
                "contract_code_end",
            )
            if column in merged.columns
        ],
    ]])


def _assert_vectorized_previous_value_integrity(
    subset: pd.DataFrame,
    selected: pd.DataFrame,
    *,
    raw_instrument: str,
    field_name: str,
) -> None:
    for _, row in selected.iterrows():
        _assert_previous_value_integrity_row(
            row,
            subset,
            contract_code=str(row.get("contract_code") or ""),
            raw_instrument=raw_instrument,
            field_name=field_name,
        )


def _assert_previous_value_integrity_row(
    row: pd.Series,
    subset: pd.DataFrame,
    *,
    contract_code: str | None,
    raw_instrument: str,
    field_name: str,
) -> None:
    previous_value = _decode_optional_value(row.get("previous_value"), row.get("previous_value_type"))
    if previous_value is None:
        return
    prior = _prior_history_row_for_previous_value(subset, row, contract_code=contract_code)
    if prior is None:
        raise HistoricalFieldIntegrityError(
            _previous_value_integrity_message(
                row,
                raw_instrument=raw_instrument,
                field_name=field_name,
                reason="no prior historical value",
                prior=None,
                expected=previous_value,
            )
        )
    actual = _decode_value(prior.get("value"), prior.get("value_type"))
    if not _same_decoded_value(actual, previous_value):
        raise HistoricalFieldIntegrityError(
            _previous_value_integrity_message(
                row,
                raw_instrument=raw_instrument,
                field_name=field_name,
                reason=f"previous_value mismatch: expected {previous_value!r}, found {actual!r}",
                prior=prior,
                expected=previous_value,
            )
        )


def _prior_history_row_for_previous_value(
    subset: pd.DataFrame,
    row: pd.Series,
    *,
    contract_code: str | None,
) -> pd.Series | None:
    if subset.empty:
        return None
    records = subset
    if "_scope_codes" not in records.columns or "_scope_type" not in records.columns:
        records = records.copy()
        records["_scope_codes"] = _series(records, "contract_codes").map(_decode_contract_codes)
        records["_scope_type"] = _series(records, "contract_scope_type").map(_normalise_contract_scope_type)
    current_day = _history_row_effective_day(row)
    candidates = records.copy()
    before_mask = pd.Series(
        [_history_row_effective_day(candidate) < current_day for _, candidate in candidates.iterrows()],
        index=candidates.index,
    )
    candidates = cast(pd.DataFrame, candidates[before_mask].copy())
    if candidates.empty:
        return None
    priorities = pd.Series([
        _contract_scope_priority(
            scope_type=scope_type,
            scope_codes=codes,
            contract_code=contract_code,
            start=start,
            end=end,
        )
        for scope_type, codes, start, end in zip(
            _series(candidates, "contract_scope_type"),
            _series(candidates, "_scope_codes"),
            _series(candidates, "contract_code_start"),
            _series(candidates, "contract_code_end"),
        )
    ], index=candidates.index)
    candidates = cast(pd.DataFrame, candidates[priorities >= 0].copy())
    if candidates.empty:
        return None
    candidates["_contract_scope_priority"] = priorities.loc[candidates.index]
    max_priority = _series(candidates, "_contract_scope_priority").max()
    candidates = cast(pd.DataFrame, candidates[_series(candidates, "_contract_scope_priority") == max_priority])
    candidates["_previous_value_sort_key"] = [
        _history_row_effective_key(candidate) for _, candidate in candidates.iterrows()
    ]
    candidates = _sort_history_candidates(candidates, effective_key="_previous_value_sort_key")
    return cast(pd.Series, candidates.iloc[-1])


def _history_row_effective_key(row: Mapping[str, Any] | pd.Series) -> tuple[pd.Timestamp, pd.Timestamp]:
    day = _history_row_effective_day(row)
    ts = _optional_timestamp(row.get("effective_timestamp"))
    if ts is None:
        ts = day
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return day, ts


def _history_row_effective_day(row: Mapping[str, Any] | pd.Series) -> pd.Timestamp:
    return _normalise_trading_day(row.get("effective_trading_day"))


def _decode_optional_value(value: Any, value_type: Any) -> Any:
    text = _clean_optional_text(value)
    if not text:
        return None
    return _decode_value(text, value_type)


def _same_decoded_value(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-12
    except (TypeError, ValueError):
        return str(left) == str(right)


def _previous_value_integrity_message(
    row: Mapping[str, Any] | pd.Series,
    *,
    raw_instrument: str,
    field_name: str,
    reason: str,
    prior: Mapping[str, Any] | pd.Series | None,
    expected: Any,
) -> str:
    notice = str(row.get("source_notice_id") or row.get("source_key") or "")
    prior_notice = "" if prior is None else str(prior.get("source_notice_id") or prior.get("source_key") or "")
    prior_suffix = "" if not prior_notice else f"; prior={prior_notice}"
    return (
        "historical field previous_value integrity failed: "
        f"{raw_instrument}.{field_name} effective={row.get('effective_trading_day')} "
        f"notice={notice}: {reason}; declared_previous={expected!r}{prior_suffix}"
    )


def _series(frame: pd.DataFrame, column: str) -> pd.Series:
    return cast(pd.Series, frame[column])


def _encode_value(value: Any) -> tuple[str, str]:
    if isinstance(value, bool):
        return json.dumps(value), "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value), "int"
    if isinstance(value, float):
        return repr(value), "float"
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "", "none"
    return str(value), "str"


def _decode_value(value: Any, value_type: Any) -> Any:
    text = "" if value is None else str(value)
    typ = "" if value_type is None else str(value_type)
    if typ == "int":
        return int(float(text))
    if typ == "float":
        return float(text)
    if typ == "bool":
        return json.loads(text)
    if typ == "none":
        return None
    return text


def _load_provider_from_sqlite_path(db_path: str) -> FieldHistoryProvider:
    with connect_sqlite(db_path) as conn:
        try:
            frame = pd.read_sql_query(f'SELECT * FROM "{HISTORICAL_FIELD_TABLE}"', conn)
        except sqlite3.Error as exc:
            raise RuntimeError(f"cannot read {HISTORICAL_FIELD_TABLE} from {db_path}") from exc
    return FieldHistoryProvider(frame)


def _product_from_name(name: str) -> Any:
    from sources.LocalCNFutures.CNFutures import CNFutures, CNFuturesContract

    text = str(name or "").strip()
    if _DOTTED_CONTRACT_PATTERN.match(text) or _PIPE_CONTRACT_PATTERN.match(text):
        return CNFuturesContract(text)
    return CNFutures(text)


def _parent_product_from_contract_name(name: str) -> Any | None:
    from sources.LocalCNFutures.CNFutures import CNFutures

    text = str(name or "").strip()
    contract_match = _DOTTED_CONTRACT_PATTERN.match(text)
    if contract_match:
        return CNFutures(f"{contract_match.group('product').upper()}.{contract_match.group('exchange').upper()}")
    pipe_match = _PIPE_CONTRACT_PATTERN.match(text)
    if pipe_match:
        exchange = pipe_match.group("exchange").upper()
        exchange_short = {
            "DCE": "DCE",
            "SHFE": "SHF",
            "INE": "INE",
            "CZCE": "CZC",
            "GFEX": "GFE",
            "CFFEX": "CFE",
        }.get(exchange, exchange)
        return CNFutures(f"{pipe_match.group('product').upper()}.{exchange_short}")
    return None


def _localise_timestamp(value: str, timezone: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise MissingTradingDay(f"invalid timestamp: {value!r}")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(timezone)
    return cast(pd.Timestamp, timestamp)


def _price_frame_for_market_data_query(product: Any, timestamp: pd.Timestamp) -> pd.DataFrame:
    query_timestamp = _normalise_timestamp_key(timestamp)
    try:
        frame = product.get_price_data(query_timestamp - pd.Timedelta(days=1), query_timestamp + pd.Timedelta(days=1))
    except Exception:
        frame = pd.DataFrame()
    if frame.empty and hasattr(product, "get_parent_product"):
        try:
            parent = product.get_parent_product()
        except Exception:
            parent = None
        if parent is not None:
            frame = parent.get_price_data(query_timestamp - pd.Timedelta(days=1), query_timestamp + pd.Timedelta(days=1))
    if frame.empty:
        parent = _parent_product_from_contract_name(_instrument_name(product))
        if parent is not None:
            frame = parent.get_price_data(query_timestamp - pd.Timedelta(days=1), query_timestamp + pd.Timedelta(days=1))
    if frame.empty:
        raise MissingTradingDay(
            f"no market data around timestamp={timestamp} for product={_instrument_name(product)}"
        )
    return frame


def build_trading_day_resolver_from_market_data(frame: pd.DataFrame) -> TimestampTradingDayResolver:
    """Build the same timestamp -> trading_day resolver MarketDataModule uses."""
    if isinstance(frame.index, pd.MultiIndex):
        days = DataIndex.trading_day_index_from_index(frame.index)
        timestamps = DataIndex.event_timestamps_from_index(frame.index)
    elif "trading_day" in frame.columns:
        days = pd.DatetimeIndex(pd.to_datetime(frame["trading_day"], errors="coerce"))
        timestamps = pd.DatetimeIndex(frame.index)
    else:
        raise MissingTradingDay(
            "market-data query requires a trading_day column or MultiIndex level; "
            "do not infer night-session trading days from calendar dates"
        )
    mapping: dict[pd.Timestamp, pd.Timestamp] = {}
    for ts, day in zip(timestamps, days):
        if pd.isna(ts) or pd.isna(day):
            continue
        timestamp_key = cast(pd.Timestamp, pd.Timestamp(cast(Any, ts)))
        trading_day_timestamp = cast(pd.Timestamp, pd.Timestamp(cast(Any, day)))
        trading_day = cast(pd.Timestamp, trading_day_timestamp.normalize())
        mapping[timestamp_key] = trading_day
    if not mapping:
        raise MissingTradingDay("market-data query contains no usable timestamp/trading_day mapping")
    return TimestampTradingDayResolver(mapping)


def resolve_historical_field_values_for_product(
    product: Any,
    timestamp: Any,
    *,
    provider: FieldHistoryProvider,
    trading_day_resolver: TradingDayResolver,
    field_names: Iterable[object],
    instrument_type: str | None = "future",
    fallback: HistoricalFieldFallbackPolicy | str = HistoricalFieldFallbackPolicy.STRICT_HISTORICAL,
) -> dict[str, HistoricalFieldValue]:
    """Resolve market-rule fields exactly as MarketDataModule consumes them."""
    ts = _normalise_timestamp_key(timestamp)
    values: dict[str, HistoricalFieldValue] = {}
    for field_name in field_names:
        field = str(field_name)
        values[field] = provider.resolve_at(
            product,
            field,
            ts,
            trading_day_resolver=trading_day_resolver,
            instrument_type=instrument_type,
            fallback=fallback,
        )
    return values


def resolve_historical_fields_for_product(
    product: Any,
    timestamp: Any,
    *,
    provider: FieldHistoryProvider,
    trading_day_resolver: TradingDayResolver,
    field_names: Iterable[object],
    instrument_type: str | None = "future",
    fallback: HistoricalFieldFallbackPolicy | str = HistoricalFieldFallbackPolicy.STRICT_HISTORICAL,
) -> dict[str, object]:
    return {
        field_name: resolved.value
        for field_name, resolved in resolve_historical_field_values_for_product(
            product,
            timestamp,
            provider=provider,
            trading_day_resolver=trading_day_resolver,
            field_names=field_names,
            instrument_type=instrument_type,
            fallback=fallback,
        ).items()
    }


def historical_fields_frame_for_products(
    products: Sequence[Any],
    index: Iterable[Any],
    *,
    provider: FieldHistoryProvider,
    trading_day_resolver: TradingDayResolver,
    field_names: Iterable[object],
    instrument_type: str | None = "future",
    fallback: HistoricalFieldFallbackPolicy | str = HistoricalFieldFallbackPolicy.STRICT_HISTORICAL,
) -> dict[str, pd.DataFrame]:
    """Vectorized MarketDataModule-style lookup for products and timestamps.

    Returns one DataFrame per field, indexed by the supplied timestamps and
    columned by Product objects. This is the batch counterpart of
    ``resolve_historical_fields_for_product`` and uses FieldHistoryProvider's
    vectorized ``frame_for_index`` path.
    """
    timestamps = _timestamps_for_historical_field_index(index)
    trading_days = list(_trading_days_for_historical_field_index(
        timestamps,
        trading_day_resolver=trading_day_resolver,
    ))
    query_frames = {
        _instrument_name(product): provider.query_frame_for_timestamps(
            product,
            timestamps,
            trading_days,
            instrument_type=instrument_type,
        )
        for product in products
    }
    result: dict[str, pd.DataFrame] = {}
    for field_name in field_names:
        field = str(field_name)
        columns = {
            product_name: provider.values_for_query_frame(
                product_name,
                field,
                query_frame,
                fallback=fallback,
            )
            for product_name, query_frame in query_frames.items()
        }
        result[field] = pd.DataFrame(columns)
    return result


def _trading_days_for_historical_field_index(
    timestamps: Sequence[Any],
    *,
    trading_day_resolver: TradingDayResolver,
) -> pd.DatetimeIndex:
    batch_resolver = getattr(trading_day_resolver, "resolve_trading_days", None)
    if callable(batch_resolver):
        return pd.DatetimeIndex(batch_resolver(timestamps))
    return DataIndex.normalized_days(pd.DatetimeIndex([
        trading_day_resolver.resolve_trading_day(timestamp)
        for timestamp in timestamps
    ]))


def _timestamps_for_historical_field_index(index: Iterable[Any]) -> list[Any]:
    if isinstance(index, pd.MultiIndex):
        return list(DataIndex.event_timestamps_from_index(index))
    return list(index)


def main(argv: Sequence[str] | None = None) -> int:
    """Run a MarketDataModule-style historical-field lookup."""
    import argparse
    import importlib.util
    from pathlib import Path

    from tools.testers.backtest.engines.native.state import BacktestRunState
    from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext

    repo_root = Path(__file__).resolve().parents[2]
    market_data_path = str(repo_root / "tools/testers/backtest/modules/market_data.py")
    market_data_spec = importlib.util.spec_from_file_location("_field_history_market_data_audit", market_data_path)
    if market_data_spec is None or market_data_spec.loader is None:
        raise RuntimeError(f"cannot load MarketDataModule from {market_data_path}")
    market_data_module = importlib.util.module_from_spec(market_data_spec)
    market_data_spec.loader.exec_module(market_data_module)
    MarketDataModule = market_data_module.MarketDataModule
    current_historical_fields_at = market_data_module.current_historical_fields_at
    historical_field_frames_for_market_data = market_data_module.historical_field_frames_for_market_data

    try:
        from settings import CACHE_DB_PATH
        default_db_path = str(CACHE_DB_PATH)
    except Exception:
        default_db_path = "/Users/maxdeux/Documents/GTHT/data/sqlite/unifieddata.sqlite"

    parser = argparse.ArgumentParser(description="Query historical market-rule fields via Product + market-data trading-day mapping.")
    parser.add_argument("product", help="Product object name, e.g. BZ.DCE; contract names such as BZ2606.DCE also work")
    parser.add_argument("timestamp", help="Exchange-local timestamp to query; include timezone when possible")
    parser.add_argument(
        "--fields",
        nargs="+",
        default=["MaxLimitOrderVolume", "MaxMarketOrderVolume", "MinLimitOrderVolume"],
        help="Field names to query",
    )
    parser.add_argument("--instrument-type", default="future", choices=["future", "option", "unknown"], help="Instrument type")
    parser.add_argument("--db", default="", help="SQLite DB path; omitted uses FieldHistory + OpenCTP latest market-rule provider")
    parser.add_argument("--timezone", default="Asia/Shanghai", help="Timezone for timestamps without an explicit offset")
    parser.add_argument(
        "--trading-day",
        default="",
        help=(
            "Explicit trading day for manual audits at non-trading timestamps. "
            "When omitted, the query uses the same market-data timestamp mapping as MarketDataModule."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    provider = _load_provider_from_sqlite_path(args.db) if args.db else load_market_rule_field_provider()
    product = _product_from_name(args.product)
    timestamp = _localise_timestamp(args.timestamp, str(args.timezone))
    if args.trading_day:
        resolver = TimestampTradingDayResolver({_normalise_timestamp_key(timestamp): args.trading_day})
        price_frame = pd.DataFrame({product: [1.0]}, index=pd.DatetimeIndex([_normalise_timestamp_key(timestamp)]))
    else:
        price_frame = _price_frame_for_market_data_query(product, timestamp)
        resolver = build_trading_day_resolver_from_market_data(price_frame)
    trading_day = resolver.resolve_trading_day(timestamp, _instrument_name(product))
    raw_prices = pd.DataFrame({product: [1.0]}, index=pd.DatetimeIndex([_normalise_timestamp_key(timestamp)]))
    historical_field_frames = historical_field_frames_for_market_data(
        [product],
        raw_prices.index,
        provider=provider,
        trading_day_resolver=resolver,
        field_names=tuple(args.fields),
        policy=str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value),
    )

    account = BacktestRunState()
    setattr(account, "raw_market_data", {
        "raw_prices": raw_prices,
        "historical_field_provider": provider,
        "trading_day_resolver": resolver,
        "historical_field_policy": str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value),
        "historical_field_names": tuple(args.fields),
        "historical_field_frames": historical_field_frames,
    })
    setup_ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    MarketDataModule.load_raw_market_data.compute(account, setup_ctx)
    MarketDataModule.causal_valuation.compute(account, setup_ctx)

    event_ctx = FlowContext(timestamp=_normalise_timestamp_key(timestamp), event_queue=EventQueue())
    MarketDataModule.lookup_historical_fields_on_signal.compute(account, event_ctx)
    module_values = current_historical_fields_at(account, _normalise_timestamp_key(timestamp))
    product_values = module_values.get(str(product), {})

    print(f"db={args.db}")
    print(
        f"product={_instrument_name(product)} timestamp={timestamp} "
        f"trading_day={trading_day.date()} instrument_type={args.instrument_type}"
    )
    resolved_values = resolve_historical_field_values_for_product(
        product,
        timestamp,
        provider=provider,
        trading_day_resolver=resolver,
        field_names=args.fields,
        instrument_type=args.instrument_type,
    )
    for field_name in args.fields:
        resolved = resolved_values[str(field_name)]
        module_value = product_values.get(str(field_name))
        print(
            f"{field_name}: value={module_value} "
            f"product={resolved.instrument} contract={resolved.contract_code or '-'} "
            f"effective_day={resolved.effective_trading_day.date()} "
            f"effective_timestamp={resolved.effective_timestamp or '-'} "
            f"provider={resolved.provider}/{resolved.source_key} via=MarketDataModule"
        )
    return 0


if __name__ == "__main__":
    # Manual audit case:
    # Product query goes through Product -> market-data trading_day mapping ->
    # FieldHistoryProvider, matching the MarketDataModule consumption shape.
    AUDIT_PRODUCT = "BZ.DCE"
    AUDIT_PRODUCT = "DCE|F|BZ|2604"
    AUDIT_TIMESTAMP = "2026-03-09 21:00:00+08:00"
    raise SystemExit(main(None if len(sys.argv) > 1 else [AUDIT_PRODUCT, AUDIT_TIMESTAMP]))

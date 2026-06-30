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
from typing import Any, Protocol, cast

import pandas as pd

from tools.data.hub import DataHub


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

FIELD_HISTORY_COLUMNS = [
    "provider",
    "source_key",
    "instrument",
    "instrument_label",
    "instrument_type",
    "field_name",
    "effective_trading_day",
    "effective_timestamp",
    "value",
    "value_type",
    "contract_codes",
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


class TradingDayResolver(Protocol):
    def resolve_trading_day(self, timestamp: Any, instrument: str | None = None) -> pd.Timestamp: ...


@dataclass(frozen=True, slots=True)
class FieldInstrumentIdentity:
    raw_instrument: str
    product_code: str
    instrument_type: str = "future"
    contract_code: str | None = None


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

    def resolve_trading_day(self, timestamp: Any, instrument: str | None = None) -> pd.Timestamp:
        ts = _normalise_timestamp_key(timestamp)
        try:
            day = self._series.loc[ts]
        except KeyError as exc:
            if self._allow_asof and not self._series.empty:
                pos = self._series.index.searchsorted(ts, side="right") - 1
                if pos < 0:
                    pos = self._series.index.searchsorted(ts, side="left")
                if 0 <= pos < len(self._series):
                    return _normalise_trading_day(self._series.iloc[int(pos)])
            raise MissingTradingDay(
                f"no trading_day mapping for timestamp={ts.isoformat()}"
                + (f", instrument={instrument}" if instrument else "")
            ) from exc
        return _normalise_trading_day(day)


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
            self.frame = self.frame.sort_values(
                ["instrument", "field_name", "effective_trading_day", "effective_timestamp"]
            ).reset_index(drop=True)

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
        subset = self._subset(identity.product_code, field_name, identity.instrument_type)
        eligible = cast(pd.DataFrame, subset[_series(subset, "effective_trading_day") <= day])
        eligible = _filter_contract_scope(eligible, identity.contract_code)
        approximated = False
        if eligible.empty:
            if policy == HistoricalFieldFallbackPolicy.LATEST_AVAILABLE and not subset.empty:
                eligible = subset.tail(1)
                approximated = True
            else:
                first = _series(subset, "effective_trading_day").min() if not subset.empty else None
                suffix = f"; first effective day is {first.date()}" if first is not None else ""
                raise MissingHistoricalField(
                    f"no historical value for {identity.raw_instrument}.{field_name} at trading_day={day.date()}{suffix}"
                )
        row = eligible.iloc[-1]
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
        subset = self._subset(identity.product_code, field_name, identity.instrument_type)
        effective_timestamp = _series(subset, "effective_timestamp")
        effective_trading_day = _series(subset, "effective_trading_day")
        timestamp_mask = effective_timestamp.notna() & (effective_timestamp <= ts)
        trading_day_mask = effective_timestamp.isna() & (effective_trading_day <= trading_day)
        candidates = cast(pd.DataFrame, subset[timestamp_mask | trading_day_mask]).copy()
        candidates = _filter_contract_scope(candidates, identity.contract_code)
        approximated = False
        if candidates.empty:
            if policy == HistoricalFieldFallbackPolicy.LATEST_AVAILABLE and not subset.empty:
                candidates = subset.tail(1).copy()
                approximated = True
            else:
                raise MissingHistoricalField(
                    f"no historical value for {identity.raw_instrument}.{field_name} at "
                    f"timestamp={ts.isoformat()}, trading_day={trading_day.date()}"
                )
        candidates["_effective_sort_key"] = _series(candidates, "effective_timestamp").fillna(
            _series(candidates, "effective_trading_day")
        )
        sort_columns = ["_effective_sort_key"]
        if "_contract_scope_priority" in candidates.columns:
            sort_columns.append("_contract_scope_priority")
        row = candidates.sort_values(by=sort_columns).iloc[-1]
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
        policy = HistoricalFieldFallbackPolicy(fallback)
        timestamps = [_normalise_timestamp_key(timestamp) for timestamp in index]
        if not timestamps:
            return pd.Series([], index=pd.DatetimeIndex([]), name=field_name, dtype=object)
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
        })
        result = pd.Series([None] * len(timestamps), index=pd.DatetimeIndex(timestamps), name=field_name, dtype=object)
        for key, group in query_frame.groupby(["product_code", "instrument_type"], sort=False):
            product_code, resolved_type = cast(tuple[Any, Any], key)
            try:
                subset = self._subset(str(product_code), field_name, str(resolved_type))
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
            for row_number, value in values.items():
                result.iloc[int(cast(Any, row_number))] = value
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

    def _subset(self, instrument: str, field_name: str, instrument_type: str | None) -> pd.DataFrame:
        if self.frame.empty:
            raise MissingHistoricalField("historical field table is empty")
        instrument_matches = cast(pd.DataFrame, self.frame[_series(self.frame, "instrument") == instrument])
        if instrument_matches.empty:
            raise MissingHistoricalField(f"no historical field rows for instrument={instrument}")
        type_matches = instrument_matches
        if instrument_type:
            type_matches = cast(
                pd.DataFrame,
                instrument_matches[_series(instrument_matches, "instrument_type") == instrument_type],
            )
            if type_matches.empty:
                raise MissingHistoricalField(
                    f"no historical field rows for instrument={instrument}, instrument_type={instrument_type}"
                )
        subset = cast(pd.DataFrame, type_matches[_series(type_matches, "field_name") == field_name])
        if subset.empty:
            raise MissingHistoricalField(f"no historical field rows for {instrument}.{field_name}")
        return subset


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


def load_historical_field_provider(*, store_key: str = "openctp") -> FieldHistoryProvider:
    return FieldHistoryProvider(load_historical_field_frame(store_key=store_key))


def load_market_rule_field_provider(
    *,
    store_key: str = "openctp",
    include_openctp_latest: bool = True,
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
    if not include_openctp_latest:
        return FieldHistoryProvider(frame)
    latest = load_openctp_latest_market_rule_frame(store_key=store_key)
    if latest.empty:
        return FieldHistoryProvider(frame)
    combined = pd.concat([frame, latest], ignore_index=True) if not frame.empty else latest
    return FieldHistoryProvider(combined)


def load_openctp_latest_market_rule_frame(*, store_key: str = "openctp") -> pd.DataFrame:
    """Represent OpenCTP latest contract specs as FieldHistory records."""
    try:
        from sources.OpenCTP.client import read_cnfutures_contract_specs_for_date
    except Exception:
        return pd.DataFrame(columns=FIELD_HISTORY_COLUMNS)

    try:
        specs = read_cnfutures_contract_specs_for_date(None, allow_latest_fallback=True)
    except Exception:
        return pd.DataFrame(columns=FIELD_HISTORY_COLUMNS)
    if specs.empty:
        return pd.DataFrame(columns=FIELD_HISTORY_COLUMNS)

    source_date = str(specs.attrs.get("fee_source_date") or "")
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
                "effective_trading_day": "1900-01-01",
                "effective_timestamp": "",
                "value": value,
                "value_type": "",
                "contract_codes": contract_codes,
                "source_url": "OpenCTP latest cnfutures contract specs",
                "source_date": source_date,
                "source_notice_id": "OpenCTP latest snapshot",
                "raw_note": "Latest OpenCTP contract-level snapshot used as baseline until exchange notice history is cleaned.",
            })
    return _normalise_history_frame(pd.DataFrame(rows))


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


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {HISTORICAL_FIELD_TABLE} (
            provider TEXT NOT NULL,
            source_key TEXT NOT NULL,
            instrument TEXT NOT NULL,
            instrument_label TEXT,
            instrument_type TEXT NOT NULL,
            field_name TEXT NOT NULL,
            effective_trading_day TEXT NOT NULL,
            effective_timestamp TEXT,
            value TEXT NOT NULL,
            value_type TEXT NOT NULL,
            contract_codes TEXT NOT NULL,
            source_url TEXT,
            source_date TEXT,
            source_notice_id TEXT,
            raw_note TEXT,
            PRIMARY KEY (provider, source_key, instrument, instrument_type, field_name, effective_trading_day, effective_timestamp, contract_codes)
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
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{HISTORICAL_FIELD_TABLE}_lookup
        ON {HISTORICAL_FIELD_TABLE} (instrument, field_name, effective_trading_day, effective_timestamp)
        """
    )


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
            df[column] = "" if column not in {"value", "effective_trading_day"} else None
    df = cast(pd.DataFrame, df[FIELD_HISTORY_COLUMNS].copy())
    df["instrument"] = _series(df, "instrument").astype(str).str.strip()
    df["field_name"] = _series(df, "field_name").astype(str).str.strip()
    df["provider"] = _series(df, "provider").astype(str).str.strip()
    df["source_key"] = _series(df, "source_key").astype(str).str.strip()
    df["instrument_type"] = _series(df, "instrument_type").replace("", "unknown").fillna("unknown")
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
    df["contract_codes"] = _series(df, "contract_codes").map(_encode_contract_codes)
    df = df.drop_duplicates(subset=FIELD_HISTORY_PRIMARY_KEY, keep="last")
    return df


def _serialise_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    df["effective_trading_day"] = _series(df, "effective_trading_day").dt.strftime("%Y-%m-%d")
    df["effective_timestamp"] = _series(df, "effective_timestamp").map(
        lambda value: "" if pd.isna(value) else pd.Timestamp(value).isoformat()
    )
    return df


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


_PIPE_CONTRACT_PATTERN = re.compile(r"^(?P<exchange>[A-Z]+)\|F\|(?P<product>[A-Za-z]+)\|(?P<contract>\d{3,4})$")
_DOTTED_CONTRACT_PATTERN = re.compile(r"^(?P<product>[A-Za-z]+)(?P<contract>\d{3,4})\.(?P<exchange>[A-Za-z]+)$")
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
        return FieldInstrumentIdentity(
            raw_instrument=raw_name,
            product_code=_product_code_from_product_name(product_name),
            instrument_type=resolved_type,
            contract_code=contract_code,
        )

    if trading_day is not None and hasattr(instrument, "get_contract_id_from_trading_day"):
        try:
            current_contract = instrument.get_contract_id_from_trading_day(trading_day)
        except Exception:
            current_contract = None
        if current_contract:
            contract_code = _contract_code_from_instrument_name(str(current_contract))

    product_code = _product_code_from_product_name(raw_name)
    if contract_code:
        parsed_product = _product_code_from_contract_name(raw_name)
        if parsed_product:
            product_code = parsed_product

    return FieldInstrumentIdentity(
        raw_instrument=raw_name,
        product_code=product_code,
        instrument_type=resolved_type,
        contract_code=contract_code,
    )


def _product_code_from_product_name(name: str) -> str:
    text = str(name or "").strip()
    pipe_match = _PIPE_CONTRACT_PATTERN.match(text)
    if pipe_match:
        return pipe_match.group("product").upper()
    contract_match = _DOTTED_CONTRACT_PATTERN.match(text)
    if contract_match:
        return contract_match.group("product").upper()
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
        return pipe_match.group("product").upper()
    contract_match = _DOTTED_CONTRACT_PATTERN.match(name)
    if contract_match:
        return contract_match.group("product").upper()
    return None


def _contract_code_from_instrument_name(name: str) -> str | None:
    pipe_match = _PIPE_CONTRACT_PATTERN.match(name)
    if pipe_match:
        return pipe_match.group("contract")
    contract_match = _DOTTED_CONTRACT_PATTERN.match(name)
    if contract_match:
        return contract_match.group("contract")
    return None


def _contract_month_from_instrument_id(instrument_id: str, product_id: str) -> str | None:
    text = str(instrument_id or "").strip().upper()
    product = str(product_id or "").strip().upper()
    if product and text.startswith(product):
        suffix = text[len(product):]
        if suffix.isdigit():
            return suffix
    match = re.search(r"(\d{3,4})$", text)
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


def _filter_contract_scope(frame: pd.DataFrame, contract_code: str | None) -> pd.DataFrame:
    if frame.empty:
        return frame
    df = frame.copy()
    scopes = _series(df, "contract_codes").map(_decode_contract_codes)
    product_level = scopes.map(lambda codes: len(codes) == 0)
    if contract_code:
        contract_level = scopes.map(lambda codes: contract_code in codes)
        scoped = cast(pd.DataFrame, df[contract_level | product_level].copy())
        if scoped.empty:
            return scoped
        scoped["_contract_scope_priority"] = [
            1 if contract_code in codes else 0
            for codes in scopes.loc[scoped.index]
        ]
        scoped = scoped.sort_values(
            by=["effective_trading_day", "effective_timestamp", "_contract_scope_priority"],
        )
        return scoped
    return cast(pd.DataFrame, df[product_level].copy())


def _vectorized_values_from_subset(
    subset: pd.DataFrame,
    queries: pd.DataFrame,
    *,
    policy: HistoricalFieldFallbackPolicy,
    raw_instrument: str,
    field_name: str,
) -> pd.Series:
    records = subset.copy()
    records["_scope_codes"] = _series(records, "contract_codes").map(_decode_contract_codes)
    records["_product_level"] = _series(records, "_scope_codes").map(lambda codes: len(codes) == 0)
    candidates: list[pd.DataFrame] = []
    for contract_code, group in queries.groupby("contract_code", sort=False):
        contract = str(cast(Any, contract_code) or "")
        if contract:
            scoped = cast(
                pd.DataFrame,
                records[
                    _series(records, "_product_level")
                    | _series(records, "_scope_codes").map(lambda codes: contract in codes)
                ].copy(),
            )
            scoped["_scope_priority"] = _series(scoped, "_scope_codes").map(
                lambda codes: 1 if contract in codes else 0
            )
        else:
            scoped = cast(pd.DataFrame, records[_series(records, "_product_level")].copy())
            scoped["_scope_priority"] = 0
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
            ["_row", "_effective_sort_key", "_scope_priority"],
            kind="mergesort",
        )
        best = all_candidates.groupby("_row", sort=False).tail(1)
        for _, row in best.iterrows():
            row_number = int(cast(Any, row["_row"]))
            result.at[row_number] = _decode_value(row["value"], row.get("value_type"))

    missing_rows = [int(cast(Any, row)) for row, value in result.items() if pd.isna(value)]
    if missing_rows and policy == HistoricalFieldFallbackPolicy.LATEST_AVAILABLE and not subset.empty:
        fallback_row = subset.sort_values(by=["effective_trading_day", "effective_timestamp"]).iloc[-1]
        fallback_value = _decode_value(fallback_row["value"], fallback_row.get("value_type"))
        for row_number in missing_rows:
            result.at[row_number] = fallback_value
        missing_rows = []
    if missing_rows:
        raise MissingHistoricalField(
            f"no historical value for {raw_instrument}.{field_name} at {len(missing_rows)} timestamp(s)"
        )
    return result


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
    left = cast(pd.DataFrame, queries[["_row", query_key]].copy())
    left[query_key] = pd.to_datetime(left[query_key], errors="coerce").astype("datetime64[ns]")
    left = cast(pd.DataFrame, left.sort_values(by=cast(Any, query_key)))
    right_columns = list(dict.fromkeys([
        record_key,
        "value",
        "value_type",
        "effective_trading_day",
        "effective_timestamp",
    ]))
    right = cast(pd.DataFrame, records[right_columns].copy())
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
    return cast(pd.DataFrame, merged[[
        "_row",
        "_scope_priority",
        "_effective_sort_key",
        "value",
        "value_type",
    ]])


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
    with sqlite3.connect(db_path) as conn:
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
        names = list(frame.index.names)
        day_level = "DAY1" if "DAY1" in names else ("trading_day" if "trading_day" in names else names[0])
        timestamp_candidates = [name for name in names if name not in {day_level, None}]
        timestamp_level = (
            "MIN1" if "MIN1" in names
            else ("trade_time" if "trade_time" in names else (timestamp_candidates[-1] if timestamp_candidates else names[-1]))
        )
        day_level_key = cast(str | int, day_level)
        timestamp_level_key = cast(str | int, timestamp_level)
        days = pd.DatetimeIndex(pd.to_datetime(list(frame.index.get_level_values(day_level_key)), errors="coerce"))
        timestamps = pd.DatetimeIndex(pd.to_datetime(list(frame.index.get_level_values(timestamp_level_key)), errors="coerce"))
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
    timestamps = list(index)
    return {
        str(field_name): provider.frame_for_index(
            products,
            str(field_name),
            timestamps,
            trading_day_resolver=trading_day_resolver,
            instrument_type=instrument_type,
            fallback=fallback,
        )
        for field_name in field_names
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run a MarketDataModule-style historical-field lookup."""
    import argparse
    import importlib.util
    from pathlib import Path

    from tools.testers.backtest.engines.native.ledger import AccountState
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

    account = AccountState()
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

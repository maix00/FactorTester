"""公共的历史字段存储与查询 helper。

该模块表示“某个产品/合约字段从某个交易日起生效”的时间序列规则。
数据源（例如 Guosen、OpenCTP 或后续交易所公告）只负责把自己的原始事件
归一化写入这里；回测侧（例如 MarketDataModule）只消费统一接口。
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
    approximated: bool = False
    contract_code: str | None = None


class TimestampTradingDayResolver:
    """根据实际时间戳查交易日。

    mapping 可以是:
    - DataFrame: index 为实际时间戳，包含 ``trading_day`` 列
    - Series: index 为实际时间戳，值为 trading_day
    - Mapping: {timestamp: trading_day}
    """

    def __init__(self, mapping: pd.DataFrame | pd.Series | Mapping[Any, Any]) -> None:
        if isinstance(mapping, pd.DataFrame):
            if "trading_day" not in mapping.columns:
                raise ValueError("timestamp/trading_day DataFrame must contain 'trading_day'")
            series = mapping["trading_day"]
        elif isinstance(mapping, pd.Series):
            series = mapping
        else:
            series = pd.Series(dict(mapping))
        index = pd.DatetimeIndex(pd.to_datetime(series.index))
        values = pd.to_datetime(series.to_numpy(), errors="coerce")
        self._series = pd.Series(values, index=index).dropna().sort_index()

    def resolve_trading_day(self, timestamp: Any, instrument: str | None = None) -> pd.Timestamp:
        ts = _normalise_timestamp_key(timestamp)
        try:
            day = self._series.loc[ts]
        except KeyError as exc:
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
            sort_columns.insert(0, "_contract_scope_priority")
        row = candidates.sort_values(by=sort_columns).iloc[-1]
        return HistoricalFieldValue(
            instrument=identity.product_code,
            field_name=field_name,
            value=_decode_value(row["value"], row.get("value_type")),
            effective_trading_day=_normalise_trading_day(row["effective_trading_day"]),
            effective_timestamp=_optional_timestamp(row.get("effective_timestamp")),
            source_key=str(row.get("source_key") or ""),
            provider=str(row.get("provider") or ""),
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
        values: list[Any] = []
        timestamps: list[pd.Timestamp] = []
        for timestamp in index:
            ts = _normalise_timestamp_key(timestamp)
            values.append(
                self.resolve_at(
                    instrument,
                    field_name,
                    ts,
                    trading_day_resolver=trading_day_resolver,
                    instrument_type=instrument_type,
                    fallback=fallback,
                ).value
            )
            timestamps.append(ts)
        return pd.Series(values, index=pd.DatetimeIndex(timestamps), name=field_name)

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
        storage_df.to_sql(HISTORICAL_FIELD_TABLE, conn, if_exists="append", index=False)
    return path


def load_historical_field_frame(*, store_key: str = "openctp") -> pd.DataFrame:
    hub = DataHub.get_instance()
    try:
        with hub.connect_store(store_key) as conn:
            _ensure_schema(conn)
            return pd.read_sql_query(f'SELECT * FROM "{HISTORICAL_FIELD_TABLE}"', conn)
    except sqlite3.Error:
        return pd.DataFrame(columns=FIELD_HISTORY_COLUMNS)


def load_historical_field_provider(*, store_key: str = "openctp") -> FieldHistoryProvider:
    return FieldHistoryProvider(load_historical_field_frame(store_key=store_key))


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
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{HISTORICAL_FIELD_TABLE}_lookup
        ON {HISTORICAL_FIELD_TABLE} (instrument, field_name, effective_trading_day, effective_timestamp)
        """
    )


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
        ts = ts.tz_convert("UTC").tz_localize(None)
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
            by=["_contract_scope_priority", "effective_trading_day", "effective_timestamp"],
        )
        return scoped
    return cast(pd.DataFrame, df[product_level].copy())


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


def main(argv: Sequence[str] | None = None) -> int:
    """Small manual query entrypoint for VS Code / terminal debugging."""
    import argparse

    try:
        from settings import CACHE_DB_PATH
        default_db_path = str(CACHE_DB_PATH)
    except Exception:
        default_db_path = "/Users/maxdeux/Documents/GTHT/data/sqlite/unifieddata.sqlite"

    parser = argparse.ArgumentParser(description="Query historical market-rule fields by product/contract and timestamp.")
    parser.add_argument("instrument", nargs="?", default="BZ2606.DCE", help="Product/contract, e.g. BZ, BZ2606.DCE, ME2607.CZC")
    parser.add_argument("timestamp", nargs="?", default="2026-06-24 09:01:00", help="Timestamp to query")
    parser.add_argument(
        "--fields",
        nargs="+",
        default=["MaxLimitOrderVolume", "MaxMarketOrderVolume", "MinLimitOrderVolume"],
        help="Field names to query",
    )
    parser.add_argument("--instrument-type", default="future", choices=["future", "option", "unknown"], help="Instrument type")
    parser.add_argument("--db", default=default_db_path, help="SQLite DB path")
    parser.add_argument(
        "--calendar-day",
        action="store_true",
        default=True,
        help="Use calendar date as trading day. For real night-session checks, pass a trading-day resolver in code.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    provider = _load_provider_from_sqlite_path(args.db)
    resolver = CalendarDateTradingDayResolver()
    timestamp = pd.Timestamp(args.timestamp)

    print(f"db={args.db}")
    print(f"instrument={args.instrument} timestamp={timestamp} instrument_type={args.instrument_type}")
    for field_name in args.fields:
        resolved = provider.resolve_at(
            args.instrument,
            field_name,
            timestamp,
            trading_day_resolver=resolver,
            instrument_type=args.instrument_type,
        )
        print(
            f"{field_name}: value={resolved.value} "
            f"product={resolved.instrument} contract={resolved.contract_code or '-'} "
            f"effective_day={resolved.effective_trading_day.date()} "
            f"provider={resolved.provider}/{resolved.source_key}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

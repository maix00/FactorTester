"""Unified LimitOrderVolume historical-field view.

Agent-cleaned and provider-normalized rows are appended to
``historical_field_values``. This module fuses those rows into a deduplicated
field view with multi-source evidence attached.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, cast

import pandas as pd

from tools.data.field_history import (
    FIELD_HISTORY_COLUMNS,
    HISTORICAL_FIELD_TABLE,
    FieldHistoryProvider,
    _ensure_store_registered,
    load_historical_field_frame,
)
from tools.data.hub import DataHub


FIELDS = ("MinLimitOrderVolume", "MaxLimitOrderVolume", "MaxMarketOrderVolume")
UNIFIED_TABLE = "field_history_limit_order_volume_unified"

_GROUP_COLUMNS = [
    "instrument",
    "instrument_label",
    "instrument_type",
    "field_name",
    "effective_trading_day",
    "effective_timestamp",
    "value",
    "value_type",
    "contract_codes",
]


def load_source_frame(*, store_key: str = "openctp") -> pd.DataFrame:
    frame = load_historical_field_frame(store_key=store_key)
    if frame.empty:
        return pd.DataFrame(columns=FIELD_HISTORY_COLUMNS)
    return cast(pd.DataFrame, frame[frame["field_name"].isin(FIELDS)].copy())


def build_unified_frame(source_frame: pd.DataFrame | None = None, *, store_key: str = "openctp") -> pd.DataFrame:
    frame = load_source_frame(store_key=store_key) if source_frame is None else source_frame.copy()
    if frame.empty:
        return _empty_unified_frame()
    for column in FIELD_HISTORY_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame = frame[frame["field_name"].isin(FIELDS)].copy()
    if frame.empty:
        return _empty_unified_frame()
    frame["contract_codes"] = cast(pd.Series, frame["contract_codes"]).map(_normalise_contract_codes_json)
    rows: list[dict[str, Any]] = []
    for _, group in frame.groupby(_GROUP_COLUMNS, dropna=False, sort=True):
        group_df = cast(pd.DataFrame, group)
        first = group_df.iloc[0]
        row: dict[str, Any] = {column: first[column] for column in _GROUP_COLUMNS}
        row["providers"] = _json_unique(group_df["provider"])
        row["source_keys"] = _json_unique(group_df["source_key"])
        row["source_urls"] = _json_unique(group_df["source_url"])
        row["source_dates"] = _json_unique(group_df["source_date"])
        row["source_notice_ids"] = _json_unique(group_df["source_notice_id"])
        row["source_count"] = int(len(set(zip(group_df["provider"], group_df["source_key"]))))
        row["evidence_count"] = int(len(group_df))
        row["raw_notes"] = _json_unique(group_df["raw_note"])
        rows.append(row)
    return pd.DataFrame(rows, columns=_unified_columns())


def save_unified_table(*, store_key: str = "openctp") -> str:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    path = hub._get_sqlite_store(store_key).path()
    frame = _serialise_unified_frame(build_unified_frame(store_key=store_key))
    with hub.connect_store(store_key) as conn:
        frame.to_sql(UNIFIED_TABLE, conn, if_exists="replace", index=False)
    return path


def load_unified_provider(*, store_key: str = "openctp") -> FieldHistoryProvider:
    return build_unified_provider(build_unified_frame(store_key=store_key))


def build_unified_provider(frame: pd.DataFrame) -> FieldHistoryProvider:
    if frame.empty:
        return FieldHistoryProvider(frame)
    provider_frame = frame.copy()
    provider_frame["provider"] = "Unified"
    provider_frame["source_key"] = provider_frame["source_keys"]
    provider_frame["source_url"] = provider_frame["source_urls"]
    provider_frame["source_date"] = provider_frame["source_dates"]
    provider_frame["source_notice_id"] = provider_frame["source_notice_ids"]
    provider_frame["raw_note"] = provider_frame["raw_notes"]
    return FieldHistoryProvider(cast(pd.DataFrame, provider_frame[FIELD_HISTORY_COLUMNS].copy()))


def _empty_unified_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=_unified_columns())


def _unified_columns() -> list[str]:
    return [
        *_GROUP_COLUMNS,
        "providers",
        "source_keys",
        "source_urls",
        "source_dates",
        "source_notice_ids",
        "source_count",
        "evidence_count",
        "raw_notes",
    ]


def _json_unique(values: Iterable[Any]) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        text = str(value).strip()
        if not text or text.lower() in {"nan", "nat", "none"}:
            continue
        if text not in seen:
            seen.add(text)
            cleaned.append(text)
    return json.dumps(sorted(cleaned), ensure_ascii=False)


def _normalise_contract_codes_json(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "[]"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "[]"
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = [item.strip() for item in text.split(",") if item.strip()]
    else:
        parsed = value
    if not isinstance(parsed, Iterable) or isinstance(parsed, (str, bytes)):
        parsed = [parsed]
    codes = sorted({str(item).strip() for item in parsed if str(item).strip()})
    return json.dumps(codes, ensure_ascii=False)


def _serialise_unified_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    result["effective_trading_day"] = cast(
        pd.Series,
        pd.to_datetime(result["effective_trading_day"], errors="coerce"),
    ).dt.strftime("%Y-%m-%d")
    result["effective_timestamp"] = cast(
        pd.Series,
        pd.to_datetime(result["effective_timestamp"], errors="coerce"),
    ).map(lambda value: "" if pd.isna(value) else pd.Timestamp(value).isoformat())
    return result

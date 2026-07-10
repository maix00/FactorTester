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
    FieldHistoryProvider,
    _ensure_store_registered,
    _clean_optional_text,
    _normalise_change_type,
    _normalise_contract_scope_type,
    load_historical_field_frame,
)
from tools.data.hub import DataHub


FIELDS = ("MinLimitOrderVolume", "MaxLimitOrderVolume", "MaxMarketOrderVolume")
UNIFIED_TABLE = "field_history_limit_order_volume_unified"

_GROUP_COLUMNS = [
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
    "contract_codes",
    "contract_scope_type",
    "contract_code_start",
    "contract_code_end",
    "change_type",
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
    frame = _normalise_scope_columns(frame)
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


def load_unified_frame(*, store_key: str = "openctp") -> pd.DataFrame:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    with hub.connect_store(store_key) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (UNIFIED_TABLE,),
        ).fetchone()
        if not exists:
            raise RuntimeError(
                f"{UNIFIED_TABLE} is not materialized; run save_unified_table() after ingesting FieldHistory events"
            )
        return pd.read_sql_query(f'SELECT * FROM "{UNIFIED_TABLE}"', conn)


def load_unified_provider(*, store_key: str = "openctp") -> FieldHistoryProvider:
    return build_unified_provider(load_unified_frame(store_key=store_key))


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
    for column in FIELD_HISTORY_COLUMNS:
        if column not in provider_frame.columns:
            provider_frame[column] = ""
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


def _normalise_scope_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["contract_codes"] = cast(pd.Series, result["contract_codes"]).map(_normalise_contract_codes_json)
    result["contract_scope_type"] = [
        _normalise_contract_scope_type(scope_type, contract_codes=contract_codes, start=start, end=end)
        for scope_type, contract_codes, start, end in zip(
            result["contract_scope_type"],
            result["contract_codes"],
            result["contract_code_start"],
            result["contract_code_end"],
        )
    ]
    result["contract_code_start"] = cast(pd.Series, result["contract_code_start"]).map(
        lambda value: _clean_optional_text(value).upper()
    )
    result["contract_code_end"] = cast(pd.Series, result["contract_code_end"]).map(
        lambda value: _clean_optional_text(value).upper()
    )
    result["change_type"] = cast(pd.Series, result["change_type"]).map(_normalise_change_type)
    return result


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

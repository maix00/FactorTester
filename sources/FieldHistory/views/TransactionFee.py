"""Unified transaction-fee historical-field view.

Historical exchange notices and provider baselines are appended to
``historical_field_values``. This view deduplicates those rows and includes
OpenCTP's latest contract snapshot as a current baseline so MarketDataModule can
read one provider for both historical events and today's listed contracts.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, cast

import pandas as pd

from tools.data.field_history import (
    FIELD_HISTORY_COLUMNS,
    OPENCTP_LATEST_FIELD_PROVIDER,
    TRANSACTION_FEE_SOURCE_EXCHANGE,
    TRANSACTION_FEE_SOURCE_OPENCTP,
    TRANSACTION_FEE_SOURCES,
    TRANSACTION_FEE_FIELD_NAMES,
    FieldHistoryProvider,
    _ensure_store_registered,
    _normalise_transaction_fee_source,
    load_historical_field_frame,
    load_openctp_latest_market_rule_frame,
)
from tools.data.hub import DataHub


FIELDS = (*TRANSACTION_FEE_FIELD_NAMES, "VolumeMultiple")
UNIFIED_TABLE = "field_history_transaction_fee_unified"
EXCHANGE_UNIFIED_TABLE = "field_history_transaction_fee_exchange"
BROKER_OPENCTP_UNIFIED_TABLE = "field_history_transaction_fee_broker_openctp"
FEE_UNIT_CLASSIFICATION_TABLE = "field_history_transaction_fee_unit_classification"
FEE_VERIFICATION_TABLE = "field_history_transaction_fee_verification"

_TABLE_BY_SOURCE = {
    TRANSACTION_FEE_SOURCE_EXCHANGE: EXCHANGE_UNIFIED_TABLE,
    TRANSACTION_FEE_SOURCE_OPENCTP: BROKER_OPENCTP_UNIFIED_TABLE,
}

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


def load_source_frame(
    *,
    store_key: str = "openctp",
    transaction_fee_source: str | None = None,
) -> pd.DataFrame:
    historical = load_historical_field_frame(store_key=store_key)
    latest = load_openctp_latest_market_rule_frame(store_key=store_key)
    frames = [frame for frame in (historical, latest) if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=FIELD_HISTORY_COLUMNS)
    frame = cast(pd.DataFrame, pd.concat(frames, ignore_index=True, sort=False))
    for column in FIELD_HISTORY_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame = cast(pd.DataFrame, frame[frame["field_name"].isin(FIELDS)][FIELD_HISTORY_COLUMNS].copy())
    if transaction_fee_source is None:
        return frame
    return _filter_source_frame(frame, transaction_fee_source=transaction_fee_source)


def build_unified_frame(
    source_frame: pd.DataFrame | None = None,
    *,
    store_key: str = "openctp",
    transaction_fee_source: str | None = None,
) -> pd.DataFrame:
    frame = (
        load_source_frame(store_key=store_key, transaction_fee_source=transaction_fee_source)
        if source_frame is None else source_frame.copy()
    )
    if transaction_fee_source is not None:
        frame = _filter_source_frame(frame, transaction_fee_source=transaction_fee_source)
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
        for source in TRANSACTION_FEE_SOURCES:
            source_frame = _serialise_unified_frame(build_unified_frame(
                store_key=store_key,
                transaction_fee_source=source,
            ))
            source_frame.to_sql(_TABLE_BY_SOURCE[source], conn, if_exists="replace", index=False)
        build_fee_unit_classification_frame(store_key=store_key).to_sql(
            FEE_UNIT_CLASSIFICATION_TABLE,
            conn,
            if_exists="replace",
            index=False,
        )
        build_fee_verification_frame(store_key=store_key).to_sql(
            FEE_VERIFICATION_TABLE,
            conn,
            if_exists="replace",
            index=False,
        )
    return path


def load_unified_frame(
    *,
    store_key: str = "openctp",
    transaction_fee_source: str | None = None,
) -> pd.DataFrame:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    with hub.connect_store(store_key) as conn:
        table_name = _TABLE_BY_SOURCE.get(
            _normalise_transaction_fee_source(transaction_fee_source),
            UNIFIED_TABLE,
        ) if transaction_fee_source is not None else UNIFIED_TABLE
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (table_name,),
        ).fetchone()
        if not exists:
            raise RuntimeError(
                f"{table_name} is not materialized; run save_unified_table() after ingesting FieldHistory events"
            )
        return pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)


def load_unified_provider(
    *,
    store_key: str = "openctp",
    transaction_fee_source: str | None = None,
) -> FieldHistoryProvider:
    return build_unified_provider(load_unified_frame(
        store_key=store_key,
        transaction_fee_source=transaction_fee_source,
    ))


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


def build_fee_unit_classification_frame(
    exchange_frame: pd.DataFrame | None = None,
    *,
    store_key: str = "openctp",
) -> pd.DataFrame:
    frame = (
        build_unified_frame(store_key=store_key, transaction_fee_source=TRANSACTION_FEE_SOURCE_EXCHANGE)
        if exchange_frame is None else exchange_frame.copy()
    )
    if frame.empty:
        return pd.DataFrame(columns=_classification_columns())
    fee_fields = set(TRANSACTION_FEE_FIELD_NAMES)
    frame = frame[frame["field_name"].isin(fee_fields)].copy()
    if frame.empty:
        return pd.DataFrame(columns=_classification_columns())
    frame["value_num"] = pd.to_numeric(frame["value"], errors="coerce").fillna(0.0)
    key_cols = [
        "instrument",
        "instrument_type",
        "effective_trading_day",
        "effective_timestamp",
        "contract_codes",
    ]
    pivot = (
        frame.pivot_table(index=key_cols, columns="field_name", values="value_num", aggfunc="max")
        .reset_index()
    )
    pivot = _forward_fill_fee_snapshot_fields(pivot)
    evidence = (
        frame.groupby(key_cols, dropna=False)
        .agg(
            instrument_label=("instrument_label", "last"),
            source_notice_ids=("source_notice_ids", _json_union),
            source_urls=("source_urls", _json_union),
            providers=("providers", _json_union),
            raw_notes=("raw_notes", _json_union),
        )
        .reset_index()
    )
    result = pivot.merge(evidence, on=key_cols, how="left")
    for leg_name, money_field, volume_field in _fee_leg_fields():
        money = _numeric_column(result, money_field)
        volume = _numeric_column(result, volume_field)
        result[f"{leg_name}_unit"] = [
            _classify_fee_unit(money_value, volume_value)
            for money_value, volume_value in zip(money, volume)
        ]
        result[f"{leg_name}_money"] = money
        result[f"{leg_name}_volume"] = volume
    result["classification_status"] = result[
        ["open_unit", "close_unit", "close_today_unit"]
    ].apply(lambda row: "conflict" if "conflict" in set(row) else "ok", axis=1)
    return cast(pd.DataFrame, result[_classification_columns()].copy())


def _forward_fill_fee_snapshot_fields(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    fee_fields = [field for field in TRANSACTION_FEE_FIELD_NAMES if field in result.columns]
    if not fee_fields:
        return result
    static_cols = [
        "instrument",
        "instrument_type",
        "contract_codes",
    ]
    sort_cols = [
        *static_cols,
        "effective_trading_day",
        "effective_timestamp",
    ]
    result = result.sort_values(sort_cols).copy()
    result[fee_fields] = (
        result.groupby(static_cols, dropna=False, sort=False)[fee_fields]
        .ffill()
        .fillna(0.0)
    )
    return result


def build_fee_verification_frame(
    exchange_frame: pd.DataFrame | None = None,
    openctp_frame: pd.DataFrame | None = None,
    *,
    store_key: str = "openctp",
) -> pd.DataFrame:
    classification = build_fee_unit_classification_frame(exchange_frame, store_key=store_key)
    if classification.empty:
        return pd.DataFrame(columns=_verification_columns())
    openctp = (
        build_unified_frame(store_key=store_key, transaction_fee_source=TRANSACTION_FEE_SOURCE_OPENCTP)
        if openctp_frame is None else openctp_frame.copy()
    )
    openctp_values = _openctp_product_fee_values(openctp)
    rows: list[dict[str, Any]] = []
    for item in classification.itertuples(index=False):
        source_urls = str(getattr(item, "source_urls"))
        source_notice_ids = str(getattr(item, "source_notice_ids"))
        for leg_name, money_field, volume_field in _fee_leg_fields():
            unit = str(getattr(item, f"{leg_name}_unit"))
            money_value = float(getattr(item, f"{leg_name}_money"))
            volume_value = float(getattr(item, f"{leg_name}_volume"))
            active_field = money_field if unit == "money" else volume_field if unit == "volume" else ""
            exchange_value = money_value if unit == "money" else volume_value if unit == "volume" else 0.0
            openctp_money = openctp_values.get((item.instrument, money_field))
            openctp_volume = openctp_values.get((item.instrument, volume_field))
            openctp_active = openctp_values.get((item.instrument, active_field)) if active_field else None
            rows.append({
                "instrument": item.instrument,
                "instrument_label": item.instrument_label,
                "instrument_type": item.instrument_type,
                "effective_trading_day": item.effective_trading_day,
                "effective_timestamp": item.effective_timestamp,
                "contract_codes": item.contract_codes,
                "leg": leg_name,
                "unit": unit,
                "exchange_value": exchange_value,
                "openctp_money": openctp_money,
                "openctp_volume": openctp_volume,
                "openctp_active_value": openctp_active,
                "openctp_delta": None if openctp_active is None else float(openctp_active - exchange_value),
                "verification_status": _verification_status(
                    unit=unit,
                    exchange_value=exchange_value,
                    openctp_active=openctp_active,
                    source_urls=source_urls,
                    source_notice_ids=source_notice_ids,
                ),
                "source_notice_ids": source_notice_ids,
                "source_urls": source_urls,
                "providers": getattr(item, "providers"),
            })
    return pd.DataFrame(rows, columns=_verification_columns())


def _empty_unified_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=_unified_columns())


def _fee_leg_fields() -> tuple[tuple[str, str, str], ...]:
    return (
        ("open", "OpenRatioByMoney", "OpenRatioByVolume"),
        ("close", "CloseRatioByMoney", "CloseRatioByVolume"),
        ("close_today", "CloseTodayRatioByMoney", "CloseTodayRatioByVolume"),
    )


def _classify_fee_unit(money_value: float, volume_value: float) -> str:
    money_nonzero = abs(float(money_value or 0.0)) > 1e-15
    volume_nonzero = abs(float(volume_value or 0.0)) > 1e-15
    if money_nonzero and not volume_nonzero:
        return "money"
    if volume_nonzero and not money_nonzero:
        return "volume"
    if not money_nonzero and not volume_nonzero:
        return "zero"
    return "conflict"


def _numeric_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([0.0] * len(frame), index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _json_union(values: Iterable[Any]) -> str:
    items: list[Any] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = [text]
        if not isinstance(parsed, list):
            parsed = [parsed]
        items.extend(parsed)
    return _json_unique(items)


def _openctp_product_fee_values(openctp_frame: pd.DataFrame) -> dict[tuple[str, str], float]:
    if openctp_frame.empty:
        return {}
    frame = openctp_frame.copy()
    frame = frame[frame["field_name"].isin(TRANSACTION_FEE_FIELD_NAMES)].copy()
    if frame.empty:
        return {}
    frame["contract_codes_norm"] = frame["contract_codes"].map(_normalise_contract_codes_json)
    frame = frame[frame["contract_codes_norm"] == "[]"].copy()
    frame["value_num"] = pd.to_numeric(frame["value"], errors="coerce")
    result: dict[tuple[str, str], float] = {}
    for (instrument, field_name), group in frame.groupby(["instrument", "field_name"], sort=False):
        values = group["value_num"].dropna()
        if not values.empty:
            result[(str(instrument), str(field_name))] = float(values.iloc[-1])
    return result


def _verification_status(
    *,
    unit: str,
    exchange_value: float,
    openctp_active: float | None,
    source_urls: str,
    source_notice_ids: str,
) -> str:
    if unit == "conflict":
        return "conflict_exchange_units"
    if unit == "zero":
        return "zero_fee"
    is_baseline = "exchange-baseline-user-table" in source_notice_ids
    if not is_baseline:
        if _has_exchange_official_url(source_urls):
            return "official_notice"
        if source_notice_ids.strip() not in {"", "[]"}:
            return "historical_notice_secondary"
        return "needs_source_notice"
    if openctp_active is None:
        return "needs_cross_check"
    addon = 0.0000008 if unit == "money" else 0.01
    delta = float(openctp_active - exchange_value)
    if abs(delta) <= 1e-12 or abs(delta - addon) <= 1e-9:
        return "cross_checked_openctp"
    return "conflict_openctp"


def _has_exchange_official_url(source_urls: str) -> bool:
    return any(domain in source_urls for domain in (
        "cffex.com.cn",
        "czce.com.cn",
        "dce.com.cn",
        "gfex.com.cn",
        "ine.cn",
        "shfe.com.cn",
    ))


def _filter_source_frame(frame: pd.DataFrame, *, transaction_fee_source: str) -> pd.DataFrame:
    source = _normalise_transaction_fee_source(transaction_fee_source)
    provider = cast(pd.Series, frame["provider"]).astype(str)
    is_openctp = provider == OPENCTP_LATEST_FIELD_PROVIDER
    if source == TRANSACTION_FEE_SOURCE_EXCHANGE:
        mask = ~is_openctp
    elif source == TRANSACTION_FEE_SOURCE_OPENCTP:
        mask = is_openctp
    else:  # pragma: no cover - normalizer validates.
        raise ValueError(f"unsupported transaction_fee_source: {source!r}")
    return cast(pd.DataFrame, frame.loc[mask].copy())


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


def _classification_columns() -> list[str]:
    return [
        "instrument",
        "instrument_label",
        "instrument_type",
        "effective_trading_day",
        "effective_timestamp",
        "contract_codes",
        "open_unit",
        "open_money",
        "open_volume",
        "close_unit",
        "close_money",
        "close_volume",
        "close_today_unit",
        "close_today_money",
        "close_today_volume",
        "classification_status",
        "source_notice_ids",
        "source_urls",
        "providers",
        "raw_notes",
    ]


def _verification_columns() -> list[str]:
    return [
        "instrument",
        "instrument_label",
        "instrument_type",
        "effective_trading_day",
        "effective_timestamp",
        "contract_codes",
        "leg",
        "unit",
        "exchange_value",
        "openctp_money",
        "openctp_volume",
        "openctp_active_value",
        "openctp_delta",
        "verification_status",
        "source_notice_ids",
        "source_urls",
        "providers",
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

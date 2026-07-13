"""Unified contract-lifecycle schema, normalization, and storage.

Six CN futures exchanges each publish contract base info with different field
names (see ``client.py``). This module maps all six shapes onto one schema
and stores them in ``src_akshare_contract_lifecycle``, keyed by
``(exchange, contract_code)``.

Because a contract's list/last-trading/delivery dates are fixed at listing
and never change afterward, storage is insert-once: an existing
``(exchange, contract_code)`` row is never overwritten unless the caller
explicitly asks to (``overwrite=True``). Callers should use
``known_contract_codes`` to skip contracts already on file before spending a
network call's worth of exchange data on them.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd

from scripts.data_dir import CACHE_DB_PATH
from sources.OpenCTP.client import normalise_instrument_code
from tools.data.sqlite.db import connect_sqlite

CONTRACT_LIFECYCLE_TABLE = "src_akshare_contract_lifecycle"

DATE_PARAM_EXCHANGES = ("SHFE", "INE", "CZCE", "CFFEX")
ONE_SHOT_EXCHANGES = ("DCE", "GFEX")
ALL_EXCHANGES = DATE_PARAM_EXCHANGES + ONE_SHOT_EXCHANGES

_COLUMNS = (
    "exchange",
    "product_code",
    "contract_code",
    "list_date",
    "last_trading_date",
    "delivery_start_date",
    "delivery_notice_date",
    "last_delivery_date",
    "listing_base_price",
    "source_query_date",
    "source_function",
    "raw_json",
    "fetched_at",
)

# CZCE's XML tag rename bakes a 2025-holiday-schedule caveat into the column
# name itself; this is the literal column akshare produces (see
# akshare/futures_derivative/futures_contract_info_czce.py).
_CZCE_LAST_TRADING_DAY_COLUMN = "最后交易日待国家公布2025年节假日安排后进行调整"


def _source_function(df: pd.DataFrame, default: str) -> str:
    value = df.attrs.get("source_function")
    if value not in (None, ""):
        return str(value)
    return default


def ensure_schema(conn) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CONTRACT_LIFECYCLE_TABLE} (
            exchange TEXT NOT NULL,
            product_code TEXT,
            contract_code TEXT NOT NULL,
            list_date TEXT,
            last_trading_date TEXT,
            delivery_start_date TEXT,
            delivery_notice_date TEXT,
            last_delivery_date TEXT,
            listing_base_price REAL,
            source_query_date TEXT,
            source_function TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            fetched_at REAL NOT NULL,
            PRIMARY KEY (exchange, contract_code)
        )
        """
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{CONTRACT_LIFECYCLE_TABLE}_product "
        f"ON {CONTRACT_LIFECYCLE_TABLE}(exchange, product_code)"
    )


def _col(row: pd.Series, name: str) -> Any:
    if name not in row.index:
        return None
    value = row[name]
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return value


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if pd.isna(value):
        return None
    return str(value)


def _product_code(contract_code: str) -> str | None:
    match = re.match(r"^([A-Z]+)", contract_code)
    return match.group(1) if match else None


def _base_row(
    *,
    exchange: str,
    raw_contract_code: Any,
    product_code: Any,
    list_date: Any,
    last_trading_date: Any,
    delivery_start_date: Any = None,
    delivery_notice_date: Any = None,
    last_delivery_date: Any = None,
    listing_base_price: Any = None,
    source_query_date: str | None,
    source_function: str,
    raw_row: dict[str, Any],
) -> dict[str, Any] | None:
    contract_code = normalise_instrument_code(raw_contract_code)
    if not contract_code:
        return None
    return {
        "exchange": exchange,
        "product_code": (str(product_code).strip().upper() if product_code not in (None, "") else _product_code(contract_code)),
        "contract_code": contract_code,
        "list_date": _to_iso(list_date),
        "last_trading_date": _to_iso(last_trading_date),
        "delivery_start_date": _to_iso(delivery_start_date),
        "delivery_notice_date": _to_iso(delivery_notice_date),
        "last_delivery_date": _to_iso(last_delivery_date),
        "listing_base_price": float(listing_base_price) if listing_base_price not in (None, "") and not pd.isna(listing_base_price) else None,
        "source_query_date": source_query_date,
        "source_function": source_function,
        "raw_json": json.dumps(raw_row, ensure_ascii=False, default=str),
        "fetched_at": time.time(),
    }


def _normalize_shfe_like(df: pd.DataFrame, *, exchange: str, source_function: str, query_date: str) -> list[dict[str, Any]]:
    rows = []
    for _, row in df.iterrows():
        raw = row.to_dict()
        item = _base_row(
            exchange=exchange,
            raw_contract_code=_col(row, "合约代码"),
            product_code=None,
            list_date=_col(row, "上市日"),
            last_trading_date=_col(row, "到期日"),
            delivery_start_date=_col(row, "开始交割日"),
            last_delivery_date=_col(row, "最后交割日"),
            listing_base_price=_col(row, "挂牌基准价"),
            source_query_date=query_date,
            source_function=source_function,
            raw_row=raw,
        )
        if item is not None:
            rows.append(item)
    return rows


def normalize_shfe(df: pd.DataFrame, query_date: str) -> list[dict[str, Any]]:
    return _normalize_shfe_like(
        df,
        exchange="SHFE",
        source_function=_source_function(df, "futures_contract_info_shfe"),
        query_date=query_date,
    )


def normalize_ine(df: pd.DataFrame, query_date: str) -> list[dict[str, Any]]:
    return _normalize_shfe_like(
        df,
        exchange="INE",
        source_function=_source_function(df, "futures_contract_info_ine"),
        query_date=query_date,
    )


def normalize_dce(df: pd.DataFrame) -> list[dict[str, Any]]:
    source_function = _source_function(df, "futures_contract_info_dce")
    rows = []
    for _, row in df.iterrows():
        raw = row.to_dict()
        item = _base_row(
            exchange="DCE",
            raw_contract_code=_col(row, "合约"),
            product_code=None,
            list_date=_col(row, "开始交易日"),
            last_trading_date=_col(row, "最后交易日"),
            last_delivery_date=_col(row, "最后交割日"),
            source_query_date=None,
            source_function=source_function,
            raw_row=raw,
        )
        if item is not None:
            rows.append(item)
    return rows


def normalize_gfex(df: pd.DataFrame) -> list[dict[str, Any]]:
    source_function = _source_function(df, "futures_contract_info_gfex")
    rows = []
    for _, row in df.iterrows():
        raw = row.to_dict()
        item = _base_row(
            exchange="GFEX",
            raw_contract_code=_col(row, "合约代码"),
            product_code=_col(row, "品种"),
            list_date=_col(row, "开始交易日"),
            last_trading_date=_col(row, "最后交易日"),
            last_delivery_date=_col(row, "最后交割日"),
            source_query_date=None,
            source_function=source_function,
            raw_row=raw,
        )
        if item is not None:
            rows.append(item)
    return rows


def normalize_czce(df: pd.DataFrame, query_date: str) -> list[dict[str, Any]]:
    source_function = _source_function(df, "futures_contract_info_czce")
    rows = []
    for _, row in df.iterrows():
        raw = row.to_dict()
        item = _base_row(
            exchange="CZCE",
            raw_contract_code=_col(row, "合约代码"),
            product_code=_col(row, "产品代码"),
            list_date=_col(row, "第一交易日"),
            last_trading_date=_col(row, _CZCE_LAST_TRADING_DAY_COLUMN),
            delivery_notice_date=_col(row, "交割通知日"),
            last_delivery_date=_col(row, "最后交割日"),
            source_query_date=query_date,
            source_function=source_function,
            raw_row=raw,
        )
        if item is not None:
            rows.append(item)
    return rows


def normalize_cffex(df: pd.DataFrame, query_date: str) -> list[dict[str, Any]]:
    source_function = _source_function(df, "futures_contract_info_cffex")
    rows = []
    for _, row in df.iterrows():
        raw = row.to_dict()
        item = _base_row(
            exchange="CFFEX",
            raw_contract_code=_col(row, "合约代码"),
            product_code=_col(row, "品种"),
            list_date=_col(row, "上市日"),
            last_trading_date=_col(row, "最后交易日"),
            listing_base_price=_col(row, "挂盘基准价"),
            source_query_date=query_date,
            source_function=source_function,
            raw_row=raw,
        )
        if item is not None:
            rows.append(item)
    return rows


_NORMALIZERS = {
    "SHFE": lambda df, query_date: normalize_shfe(df, query_date),
    "INE": lambda df, query_date: normalize_ine(df, query_date),
    "DCE": lambda df, query_date: normalize_dce(df),
    "GFEX": lambda df, query_date: normalize_gfex(df),
    "CZCE": lambda df, query_date: normalize_czce(df, query_date),
    "CFFEX": lambda df, query_date: normalize_cffex(df, query_date),
}


def normalize_contract_info(exchange: str, df: pd.DataFrame, *, query_date: str | None = None) -> list[dict[str, Any]]:
    exchange = exchange.upper()
    if exchange not in _NORMALIZERS:
        raise ValueError(f"unknown exchange: {exchange!r}")
    if df.empty:
        return []
    return _NORMALIZERS[exchange](df, query_date)


def known_contract_codes(exchange: str, *, db_path: str | None = None) -> set[str]:
    with connect_sqlite(db_path or CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            f"SELECT contract_code FROM {CONTRACT_LIFECYCLE_TABLE} WHERE exchange = ?",
            (exchange.upper(),),
        ).fetchall()
    return {str(row["contract_code"]) for row in rows}


def upsert_contract_lifecycle(
    rows: Iterable[dict[str, Any]],
    *,
    overwrite: bool = False,
    db_path: str | None = None,
) -> dict[str, int]:
    """Insert-once by ``(exchange, contract_code)``; skip existing unless ``overwrite``."""
    rows = list(rows)
    if not rows:
        return {"inserted": 0, "skipped_existing": 0}
    placeholders = ", ".join("?" for _ in _COLUMNS)
    column_list = ", ".join(_COLUMNS)
    if overwrite:
        conflict_clause = "DO UPDATE SET " + ", ".join(
            f"{col} = excluded.{col}" for col in _COLUMNS if col not in ("exchange", "contract_code")
        )
    else:
        conflict_clause = "DO NOTHING"
    sql = (
        f"INSERT INTO {CONTRACT_LIFECYCLE_TABLE} ({column_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(exchange, contract_code) {conflict_clause}"
    )
    with connect_sqlite(db_path or CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        before = conn.total_changes
        for row in rows:
            conn.execute(sql, tuple(row[col] for col in _COLUMNS))
        applied = conn.total_changes - before
    return {"inserted": applied, "skipped_existing": len(rows) - applied}


def fetch_and_store_live(
    exchange: str,
    *,
    max_date_attempts: int = 7,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch one exchange's current contract state live and persist it.

    For ``ONE_SHOT_EXCHANGES`` (DCE/GFEX) that means "whatever is currently
    listed" — these endpoints only ever expose a recent rolling window, not
    full history, so this is meant as an on-demand top-up for contracts that
    are current *right now*, not a substitute for the offline backfill script.
    For ``DATE_PARAM_EXCHANGES`` this walks backward from today over
    ``max_date_attempts`` calendar days to skip weekends/holidays that have no
    published snapshot.
    """
    from . import client

    exchange = exchange.upper()
    fetcher = getattr(client, f"fetch_contract_info_{exchange.lower()}", None)
    if fetcher is None:
        raise ValueError(f"unknown exchange: {exchange!r}")

    if exchange in ONE_SHOT_EXCHANGES:
        df = fetcher(db_path=db_path)
        rows = normalize_contract_info(exchange, df)
    else:
        rows = []
        for offset in range(max_date_attempts):
            query_date = (pd.Timestamp.today() - pd.Timedelta(days=offset)).strftime("%Y%m%d")
            try:
                df = fetcher(query_date, db_path=db_path)
            except Exception:
                continue
            rows = normalize_contract_info(exchange, df, query_date=query_date)
            if rows:
                break
    if rows:
        upsert_contract_lifecycle(rows, db_path=db_path)
    return rows


def read_contract_lifecycle(
    *,
    exchange: str | None = None,
    product_code: str | None = None,
    contract_code: str | None = None,
    db_path: str | None = None,
) -> pd.DataFrame:
    clauses = []
    params: list[Any] = []
    if exchange:
        clauses.append("exchange = ?")
        params.append(exchange.upper())
    if product_code:
        clauses.append("product_code = ?")
        params.append(product_code.upper())
    if contract_code:
        clauses.append("contract_code = ?")
        params.append(normalise_instrument_code(contract_code))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        f"SELECT exchange, product_code, contract_code, list_date, last_trading_date, "
        f"delivery_start_date, delivery_notice_date, last_delivery_date, listing_base_price, "
        f"source_query_date, source_function, fetched_at "
        f"FROM {CONTRACT_LIFECYCLE_TABLE}{where} ORDER BY exchange, contract_code"
    )
    with connect_sqlite(db_path or CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        return pd.read_sql_query(sql, conn, params=params)

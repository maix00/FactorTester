"""Exchange contract-info lifecycle client, with a raw-response cache.

Each exchange publishes its own "contract base info" feed.  This module uses
direct official endpoints where practical and keeps AKShare-compatible fallback
shapes for callers that already depend on this package:

- ``futures_contract_info_shfe(date)`` / ``futures_contract_info_ine(date)``:
  a daily snapshot of contracts listed as of ``date`` (YYYYMMDD). Building
  full history requires querying several historical trading days.
- DCE is fetched from the official portal in a browser context; the old
  AKShare DCE endpoint is not used.
- GFEX takes no date argument and returns the exchange's contract history.
- ``futures_contract_info_czce(date)`` / ``futures_contract_info_cffex(date)``:
  same daily-snapshot shape as SHFE/INE.

This module caches the raw response so repeated runs do not hit the network
again. Field normalization lives in ``lifecycle.py``.
"""
from __future__ import annotations

import json
import os
import time
import xml.etree.ElementTree as ET
from typing import Any

import pandas as pd

from scripts.data_dir import CACHE_DB_PATH
from tools.data.sqlite.db import connect_sqlite

RESPONSES_TABLE = "src_akshare_responses"

_DCE_USER_AGENT_ENV = "GTHT_DCE_USER_AGENT"
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = (3, 8)


def _connect_cache(db_path: str | None = None):
    conn = connect_sqlite(db_path or CACHE_DB_PATH)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {RESPONSES_TABLE} (
            source_function TEXT NOT NULL,
            query_key TEXT NOT NULL,
            data_json TEXT NOT NULL,
            fetched_at REAL NOT NULL,
            PRIMARY KEY (source_function, query_key)
        )
        """
    )
    return conn


def _read_cache(source_function: str, query_key: str, *, db_path: str | None = None) -> pd.DataFrame | None:
    with _connect_cache(db_path) as conn:
        row = conn.execute(
            f"SELECT data_json FROM {RESPONSES_TABLE} WHERE source_function = ? AND query_key = ?",
            (source_function, query_key),
        ).fetchone()
    if row is None:
        return None
    df = pd.DataFrame(json.loads(row["data_json"]))
    df.attrs["source_function"] = source_function
    return df


def _write_cache(source_function: str, query_key: str, df: pd.DataFrame, *, db_path: str | None = None) -> None:
    payload = json.dumps(_json_records(df), ensure_ascii=False, default=str)
    with _connect_cache(db_path) as conn:
        conn.execute(
            f"""
            INSERT INTO {RESPONSES_TABLE} (source_function, query_key, data_json, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_function, query_key) DO UPDATE SET
                data_json = excluded.data_json,
                fetched_at = excluded.fetched_at
            """,
            (source_function, query_key, payload, time.time()),
        )


def _json_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def _fetch(source_function: str, query_key: str, *, refresh: bool, db_path: str | None, call: Any) -> pd.DataFrame:
    if not refresh:
        cached = _read_cache(source_function, query_key, db_path=db_path)
        if cached is not None:
            return cached
    df = call()
    df.attrs["source_function"] = source_function
    _write_cache(source_function, query_key, df, db_path=db_path)
    return df


def _fetch_first_available(
    candidates: list[tuple[str, str, Any]],
    *,
    refresh: bool,
    db_path: str | None,
) -> pd.DataFrame:
    """Fetch from the preferred official feed, then compatible fallbacks."""
    if not refresh:
        for source_function, query_key, _call in candidates:
            cached = _read_cache(source_function, query_key, db_path=db_path)
            if cached is not None:
                return cached
    errors: list[str] = []
    for source_function, query_key, call in candidates:
        try:
            df = call()
        except Exception as exc:
            errors.append(f"{source_function}: {type(exc).__name__}: {exc}")
            continue
        df.attrs["source_function"] = source_function
        _write_cache(source_function, query_key, df, db_path=db_path)
        return df
    raise RuntimeError("all contract lifecycle sources failed: " + "; ".join(errors))


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": os.environ.get(_DCE_USER_AGENT_ENV) or _DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    }


def _official_contract_info_shfe_like(exchange: str, date: str) -> pd.DataFrame:
    import requests

    base_url = {
        "SHFE": "https://www.shfe.com.cn/data/busiparamdata/future/ContractBaseInfo{date}.dat",
        "INE": "https://www.ine.cn/data/busiparamdata/future/ContractBaseInfo{date}.dat",
    }[exchange]
    response = requests.get(base_url.format(date=date), headers=_default_headers(), timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("o_curinstrument") or payload.get("o_cursor") or payload.get("data") or []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["合约代码", "上市日", "到期日", "开始交割日", "最后交割日", "挂牌基准价"])
    return frame.rename(columns={
        "INSTRUMENTID": "合约代码",
        "PRODUCTID": "产品代码",
        "STARTDELIVDATE": "开始交割日",
        "ENDDELIVDATE": "最后交割日",
        "EXPIREDATE": "到期日",
        "OPENDATE": "上市日",
        "BASISPRICE": "挂牌基准价",
    })


def _official_contract_info_czce(date: str) -> pd.DataFrame:
    import requests

    year = str(date)[:4]
    url = f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{date}/FutureDataReferenceData.xml"
    response = requests.get(url, headers=_default_headers(), timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    text = response.content.decode(response.encoding or "utf-8", errors="replace").replace("&nbsp;", " ")
    root = ET.fromstring(text)
    rows: list[dict[str, Any]] = []
    for contract in root.findall(".//Contract"):
        row = {child.tag: (child.text or "").strip() for child in list(contract)}
        if row:
            rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["合约代码", "产品代码", "第一交易日", "交割通知日", "最后交割日"])
    return frame.rename(columns={
        "contractId": "合约代码",
        "productId": "产品代码",
        "firstTradingDay": "第一交易日",
        "lastTradingDay": "最后交易日待国家公布2025年节假日安排后进行调整",
        "deliveryNoticeDay": "交割通知日",
        "lastDeliveryDay": "最后交割日",
    })


def _official_contract_info_cffex(date: str) -> pd.DataFrame:
    import requests

    url = f"http://www.cffex.com.cn/sj/jycs/{date[:6]}/{date[6:]}/index.xml"
    response = requests.get(url, headers=_default_headers(), timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    text = response.content.decode(response.encoding or "utf-8", errors="replace").replace("&nbsp;", " ")
    root = ET.fromstring(text)
    rows: list[dict[str, Any]] = []
    for contract in [*root.findall(".//contract"), *root.findall(".//INDEX")]:
        row = {child.tag: (child.text or "").strip() for child in list(contract)}
        if row:
            rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["查询交易日", "品种", "合约代码", "挂盘基准价", "上市日", "最后交易日"])
    if "INSTRUMENT_ID" in frame.columns:
        frame = frame[~frame["INSTRUMENT_ID"].astype(str).str.contains("-", regex=False)].copy()
    frame = frame.rename(columns={
        "instrumentid": "合约代码",
        "INSTRUMENT_ID": "合约代码",
        "productid": "品种",
        "PRODUCT_ID": "品种",
        "basisprice": "挂盘基准价",
        "BASIS_PRICE": "挂盘基准价",
        "opendate": "上市日",
        "OPEN_DATE": "上市日",
        "expiredate": "最后交易日",
        "END_TRADING_DAY": "最后交易日",
    })
    frame["查询交易日"] = date
    return frame


def fetch_contract_info_shfe(date: str, *, refresh: bool = False, db_path: str | None = None) -> pd.DataFrame:
    import akshare as ak

    return _fetch_first_available(
        [
            ("official_contract_info_shfe", date, lambda: _official_contract_info_shfe_like("SHFE", date)),
            ("futures_contract_info_shfe", date, lambda: ak.futures_contract_info_shfe(date=date)),
        ],
        refresh=refresh,
        db_path=db_path,
    )


def fetch_contract_info_ine(date: str, *, refresh: bool = False, db_path: str | None = None) -> pd.DataFrame:
    import akshare as ak

    return _fetch_first_available(
        [
            ("official_contract_info_ine", date, lambda: _official_contract_info_shfe_like("INE", date)),
            ("futures_contract_info_ine", date, lambda: ak.futures_contract_info_ine(date=date)),
        ],
        refresh=refresh,
        db_path=db_path,
    )


def fetch_contract_info_dce(*, refresh: bool = False, db_path: str | None = None) -> pd.DataFrame:
    from sources.DCE.portal import fetch_contract_info

    return _fetch(
        "official_dce_portal_contract_info",
        "all",
        refresh=refresh,
        db_path=db_path,
        call=fetch_contract_info,
    )


def fetch_contract_info_czce(date: str, *, refresh: bool = False, db_path: str | None = None) -> pd.DataFrame:
    import akshare as ak

    return _fetch_first_available(
        [
            ("official_contract_info_czce", date, lambda: _official_contract_info_czce(date)),
            ("futures_contract_info_czce", date, lambda: ak.futures_contract_info_czce(date=date)),
        ],
        refresh=refresh,
        db_path=db_path,
    )


def fetch_contract_info_cffex(date: str, *, refresh: bool = False, db_path: str | None = None) -> pd.DataFrame:
    import akshare as ak

    return _fetch_first_available(
        [
            ("official_contract_info_cffex", date, lambda: _official_contract_info_cffex(date)),
            ("futures_contract_info_cffex", date, lambda: ak.futures_contract_info_cffex(date=date)),
        ],
        refresh=refresh,
        db_path=db_path,
    )


def fetch_contract_info_gfex(*, refresh: bool = False, db_path: str | None = None) -> pd.DataFrame:
    import akshare as ak

    return _fetch(
        "futures_contract_info_gfex", "all", refresh=refresh, db_path=db_path,
        call=lambda: ak.futures_contract_info_gfex(),
    )

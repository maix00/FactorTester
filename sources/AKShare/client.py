"""AKShare exchange contract-info HTTP client, with a raw-response cache.

Each exchange publishes its own "contract base info" feed and ``akshare``
wraps them as one function per exchange (see ``akshare.futures_derivative``):

- ``futures_contract_info_shfe(date)`` / ``futures_contract_info_ine(date)``:
  a daily snapshot of contracts listed as of ``date`` (YYYYMMDD). Building
  full history requires querying several historical trading days.
- ``futures_contract_info_dce()`` / ``futures_contract_info_gfex()``: no date
  argument, one call returns the exchange's entire contract history.
- ``futures_contract_info_czce(date)`` / ``futures_contract_info_cffex(date)``:
  same daily-snapshot shape as SHFE/INE.

This module only wraps those calls and caches the raw response so repeated
runs (e.g. re-polling the same historical date) do not hit the network again.
Field normalization lives in ``lifecycle.py``.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import pandas as pd

from scripts.data_dir import CACHE_DB_PATH
from tools.data.sqlite.db import connect_sqlite

RESPONSES_TABLE = "src_akshare_responses"

# DCE's WAF blocks akshare's plain requests.post() outright (412, even from a
# real headless-browser session — see AGENT session notes on this branch).
# As a manual escape hatch, a cookie string copied from a real logged-in
# browser tab (DevTools → Network → any dce.com.cn request → Copy as cURL, or
# Application → Cookies) can be supplied via this env var; the cookie is
# short-lived and this is not a substitute for a real fix.
_DCE_COOKIE_ENV = "GTHT_DCE_COOKIE"
_DCE_USER_AGENT_ENV = "GTHT_DCE_USER_AGENT"
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
)


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
    return pd.DataFrame(json.loads(row["data_json"]))


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
    _write_cache(source_function, query_key, df, db_path=db_path)
    return df


def fetch_contract_info_shfe(date: str, *, refresh: bool = False, db_path: str | None = None) -> pd.DataFrame:
    import akshare as ak

    return _fetch(
        "futures_contract_info_shfe", date, refresh=refresh, db_path=db_path,
        call=lambda: ak.futures_contract_info_shfe(date=date),
    )


def fetch_contract_info_ine(date: str, *, refresh: bool = False, db_path: str | None = None) -> pd.DataFrame:
    import akshare as ak

    return _fetch(
        "futures_contract_info_ine", date, refresh=refresh, db_path=db_path,
        call=lambda: ak.futures_contract_info_ine(date=date),
    )


def _fetch_contract_info_dce_with_cookie(cookie: str) -> pd.DataFrame:
    """Reimplements akshare's futures_contract_info_dce() with a manual Cookie
    header, since akshare's own call takes no headers/session argument and
    DCE's WAF rejects the plain request outright."""
    import requests

    url = "http://www.dce.com.cn/dcereport/publicweb/tradepara/contractInfo"
    payload = {"lang": "zh", "tradeType": "1", "varietyId": "all"}
    headers = {
        "User-Agent": os.environ.get(_DCE_USER_AGENT_ENV) or _DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": "http://www.dce.com.cn/dalianshangpin/ywfw/ywcs/jycs/hyxxcx/index.html",
        "Cookie": cookie,
    }
    response = requests.post(url, json=payload, headers=headers, timeout=20)
    response.raise_for_status()
    data_json = response.json()
    df = pd.DataFrame(data_json["data"])
    df = df.rename(columns={
        "contractId": "合约",
        "variety": "品种名称",
        "varietyOrder": "品种代码",
        "unit": "交易单位",
        "tick": "最小变动价位",
        "startTradeDate": "开始交易日",
        "endTradeDate": "最后交易日",
        "endDeliveryDate": "最后交割日",
    })
    df = df[["品种名称", "合约", "交易单位", "最小变动价位", "开始交易日", "最后交易日", "最后交割日"]]
    df["交易单位"] = pd.to_numeric(df["交易单位"], errors="coerce")
    df["最小变动价位"] = pd.to_numeric(df["最小变动价位"], errors="coerce")
    for column in ("开始交易日", "最后交易日", "最后交割日"):
        df[column] = pd.to_datetime(df[column], format="%Y%m%d", errors="coerce").dt.date
    return df


def fetch_contract_info_dce(*, refresh: bool = False, db_path: str | None = None) -> pd.DataFrame:
    cookie = os.environ.get(_DCE_COOKIE_ENV)
    if cookie:
        return _fetch(
            "futures_contract_info_dce", "all", refresh=refresh, db_path=db_path,
            call=lambda: _fetch_contract_info_dce_with_cookie(cookie),
        )
    import akshare as ak

    return _fetch(
        "futures_contract_info_dce", "all", refresh=refresh, db_path=db_path,
        call=lambda: ak.futures_contract_info_dce(),
    )


def fetch_contract_info_czce(date: str, *, refresh: bool = False, db_path: str | None = None) -> pd.DataFrame:
    import akshare as ak

    return _fetch(
        "futures_contract_info_czce", date, refresh=refresh, db_path=db_path,
        call=lambda: ak.futures_contract_info_czce(date=date),
    )


def fetch_contract_info_cffex(date: str, *, refresh: bool = False, db_path: str | None = None) -> pd.DataFrame:
    import akshare as ak

    return _fetch(
        "futures_contract_info_cffex", date, refresh=refresh, db_path=db_path,
        call=lambda: ak.futures_contract_info_cffex(date=date),
    )


def fetch_contract_info_gfex(*, refresh: bool = False, db_path: str | None = None) -> pd.DataFrame:
    import akshare as ak

    return _fetch(
        "futures_contract_info_gfex", "all", refresh=refresh, db_path=db_path,
        call=lambda: ak.futures_contract_info_gfex(),
    )

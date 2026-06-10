"""OpenCTP online field-data HTTP client.

The OpenCTP data center exposes five public JSON endpoints:
markets, products, instruments, prices, and times.  This module keeps the
provider-specific CTP field names at the boundary and offers small normalized
DataFrames for local consumers that need stable snake_case columns.

This package deliberately does not manage local OHLCV/K-line files.  Local
price storage remains under ``sources.LocalCNFutures``; OpenCTP is only the
online reference source for exchange/product/contract specs, live quotes, and
trading sessions.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from scripts.data_dir import DATA_DIR


BASE_URL = "http://dict.openctp.cn"
CACHE_DIR = Path(DATA_DIR) / "cache" / "openctp"
CACHE_DB_PATH = CACHE_DIR / "openctp.sqlite"
ENDPOINTS = {
    "markets": "/markets",
    "products": "/products",
    "instruments": "/instruments",
    "prices": "/prices",
    "times": "/times",
}


def _comma(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return ",".join(str(item) for item in value)
    except TypeError:
        return str(value)


def _cache_key(query: dict[str, str]) -> str:
    return urlencode(sorted(query.items()))


def _connect_cache() -> sqlite3.Connection:
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS openctp_responses (
            endpoint TEXT NOT NULL,
            query_key TEXT NOT NULL,
            query_json TEXT NOT NULL,
            url TEXT NOT NULL,
            data_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (endpoint, query_key)
        )
        """
    )
    return conn


def _read_cache(endpoint: str, query: dict[str, str]) -> list[dict[str, Any]] | None:
    try:
        with _connect_cache() as conn:
            row = conn.execute(
                "SELECT data_json FROM openctp_responses WHERE endpoint = ? AND query_key = ?",
                (endpoint, _cache_key(query)),
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _write_cache(endpoint: str, query: dict[str, str], data: list[dict[str, Any]], *, url: str) -> None:
    try:
        with _connect_cache() as conn:
            conn.execute(
                """
                INSERT INTO openctp_responses
                    (endpoint, query_key, query_json, url, data_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(endpoint, query_key) DO UPDATE SET
                    query_json = excluded.query_json,
                    url = excluded.url,
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at
                """,
                (
                    endpoint,
                    _cache_key(query),
                    json.dumps(query, ensure_ascii=False, sort_keys=True),
                    url,
                    json.dumps(data, ensure_ascii=False),
                    time.time(),
                ),
            )
    except Exception:
        pass


def _request(endpoint: str, *, refresh: bool = False, **params: Any) -> list[dict[str, Any]]:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown OpenCTP endpoint: {endpoint!r}")
    query = {
        key: _comma(value)
        for key, value in params.items()
        if value is not None and _comma(value) not in (None, "")
    }
    if not refresh:
        cached = _read_cache(endpoint, query)
        if cached is not None:
            return cached
    url = BASE_URL + ENDPOINTS[endpoint]
    if query:
        url += "?" + urlencode(query)
    with urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if int(payload.get("rsp_code", -1)) != 0:
        raise RuntimeError(f"OpenCTP {endpoint} failed: {payload.get('rsp_message')}")
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise TypeError(f"OpenCTP {endpoint} returned non-list data")
    _write_cache(endpoint, query, data, url=url)
    return data


def _frame(endpoint: str, **params: Any) -> pd.DataFrame:
    return pd.DataFrame(_request(endpoint, **params))


def fetch_markets(*, areas: Any = None, refresh: bool = False) -> list[dict[str, Any]]:
    return _request("markets", areas=areas, refresh=refresh)


def fetch_products(
    *,
    types: Any = None,
    areas: Any = None,
    markets: Any = None,
    products: Any = None,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    return _request("products", types=types, areas=areas, markets=markets, products=products, refresh=refresh)


def fetch_instruments(
    *,
    types: Any = None,
    areas: Any = None,
    markets: Any = None,
    products: Any = None,
    instruments: Any = None,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    return _request(
        "instruments",
        types=types,
        areas=areas,
        markets=markets,
        products=products,
        instruments=instruments,
        refresh=refresh,
    )


def fetch_prices(
    *,
    types: Any = None,
    areas: Any = None,
    markets: Any = None,
    products: Any = None,
    instruments: Any = None,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    return _request(
        "prices",
        types=types,
        areas=areas,
        markets=markets,
        products=products,
        instruments=instruments,
        refresh=refresh,
    )


def fetch_times(
    *,
    types: Any = None,
    areas: Any = None,
    markets: Any = None,
    products: Any = None,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    return _request("times", types=types, areas=areas, markets=markets, products=products, refresh=refresh)


def frame_markets(**params: Any) -> pd.DataFrame:
    return _frame("markets", **params)


def frame_products(**params: Any) -> pd.DataFrame:
    return _frame("products", **params)


def frame_instruments(**params: Any) -> pd.DataFrame:
    return _frame("instruments", **params)


def frame_prices(**params: Any) -> pd.DataFrame:
    return _frame("prices", **params)


def frame_times(**params: Any) -> pd.DataFrame:
    return _frame("times", **params)


def normalise_instrument_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = text.split(".")[0]
    return re.sub(r"[^A-Z0-9]", "", text)


def instruments_to_contract_specs(rows: pd.DataFrame | list[dict[str, Any]]) -> pd.DataFrame:
    """Convert OpenCTP instrument rows to local contract spec columns."""
    df = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame()

    out = pd.DataFrame({
        "exchange": df.get("ExchangeID"),
        "contract_code": df.get("InstrumentID"),
        "contract_name": df.get("InstrumentName"),
        "variety_code": df.get("ProductID"),
        "product_class": df.get("ProductClass"),
        "multiplier": df.get("VolumeMultiple"),
        "min_tick": df.get("PriceTick"),
        "min_trade_quantity": df.get("MinLimitOrderVolume"),
        "max_trade_quantity": df.get("MaxLimitOrderVolume"),
        "long_margin_ratio": df.get("LongMarginRatioByMoney"),
        "long_margin_fixed": df.get("LongMarginRatioByVolume"),
        "short_margin_ratio": df.get("ShortMarginRatioByMoney"),
        "short_margin_fixed": df.get("ShortMarginRatioByVolume"),
        "open_ratio": df.get("OpenRatioByMoney"),
        "open_fixed": df.get("OpenRatioByVolume"),
        "close_ratio": df.get("CloseRatioByMoney"),
        "close_fixed": df.get("CloseRatioByVolume"),
        "closetoday_ratio": df.get("CloseTodayRatioByMoney"),
        "closetoday_fixed": df.get("CloseTodayRatioByVolume"),
        "delivery_year": df.get("DeliveryYear"),
        "delivery_month": df.get("DeliveryMonth"),
        "open_date": df.get("OpenDate"),
        "expire_date": df.get("ExpireDate"),
        "delivery_date": df.get("DeliveryDate"),
        "underlying_instrument_id": df.get("UnderlyingInstrID"),
        "underlying_multiple": df.get("UnderlyingMultiple"),
        "options_type": df.get("OptionsType"),
        "strike_price": df.get("StrikePrice"),
        "life_phase": df.get("InstLifePhase"),
    })
    for col in [
        "multiplier", "min_tick", "min_trade_quantity", "max_trade_quantity",
        "long_margin_ratio", "long_margin_fixed", "short_margin_ratio", "short_margin_fixed",
        "open_ratio", "open_fixed", "close_ratio", "close_fixed",
        "closetoday_ratio", "closetoday_fixed", "underlying_multiple", "strike_price",
    ]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out["contract_key"] = out["contract_code"].map(normalise_instrument_code)
    out["variety_code"] = out["variety_code"].astype(str).str.strip().str.upper()
    out["exchange"] = out["exchange"].astype(str).str.strip()
    out["contract_code"] = out["contract_code"].astype(str).str.strip()
    out["contract_name"] = out["contract_name"].astype(str).str.strip()
    out = out[out["contract_key"].str.len() > 0]
    return out.reset_index(drop=True)

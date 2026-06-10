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
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from scripts.data_dir import DATA_DIR


BASE_URL = "http://dict.openctp.cn"
CACHE_DIR = Path(DATA_DIR) / "cache" / "openctp"
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


def _cache_path(endpoint: str, query: dict[str, str]) -> Path:
    cache_key = urlencode(sorted(query.items()))
    digest = sha1(cache_key.encode("utf-8")).hexdigest()[:16] if cache_key else "all"
    return CACHE_DIR / endpoint / f"{digest}.json"


def _read_cache(path: Path) -> list[dict[str, Any]] | None:
    try:
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        data = payload.get("data", payload)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _write_cache(path: Path, data: list[dict[str, Any]], *, url: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"url": url, "data": data}, ensure_ascii=False, indent=2),
            encoding="utf-8",
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
    cache_path = _cache_path(endpoint, query)
    if not refresh:
        cached = _read_cache(cache_path)
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
    _write_cache(cache_path, data, url=url)
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
